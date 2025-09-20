from decimal import Decimal

from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404, render, redirect
from django.db import transaction
from django.contrib.auth.models import Group
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.contrib.auth.forms import UserCreationForm
from django import forms
from django.forms import ModelForm
from django.http import HttpResponseRedirect, JsonResponse
from bakery_app.settings import MIN_ORDER_AMOUNT_ZAR
from .models import CustomUser, Profile, Category, Product, Cart, Order, OrderItem, VendorSettings
from .serializers import (
    UserSerializer, ProfileSerializer, CategorySerializer,
    ProductSerializer, CartSerializer, OrderSerializer, OrderItemSerializer)
from .forms import ProfileForm, VendorProfileForm, VendorSettingsForm
from django.http import HttpResponse
from reportlab.pdfgen import canvas
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum, Prefetch, F, DecimalField, ExpressionWrapper
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
import io
import stripe
from django.conf import settings

stripe.api_key = settings.STRIPE_SECRET_KEY


# BASIC PAGES
def index(request):
    categories = Category.objects.all()
    return render(request, "index.html", {"categories": categories})


def category_detail(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    products = Product.objects.filter(category=category)
    return render(request, "category_detail.html", {
        "category": category,
        "products": products,
    })


# USERS
class UserViewSet(viewsets.ModelViewSet):
    queryset = CustomUser.objects.all()
    serializer_class = UserSerializer

    @action(detail=False, methods=['post'])
    def register(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        email = request.data.get('email')
        user_type = request.data.get('user_type', '').lower()

        if user_type not in ['customer', 'vendor']:
            return Response({'error': 'Invalid user_type. Must be "customer" or "vendor".'},
                            status=status.HTTP_400_BAD_REQUEST)

        if CustomUser.objects.filter(username=username).exists():
            return Response({'error': 'Username already exists'}, status=status.HTTP_400_BAD_REQUEST)

        user = CustomUser.objects.create_user(
            username=username,
            password=password,
            email=email,
            user_type=user_type
        )

        Profile.objects.create(user=user)

        group_name = 'Customers' if user_type == 'customer' else 'Vendors'
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)

        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class ProfileViewSet(viewsets.ModelViewSet):
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer


# PRODUCTS
class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer


# CART
class CartViewSet(viewsets.ModelViewSet):
    queryset = Cart.objects.all()
    serializer_class = CartSerializer

    @action(detail=False, methods=['post'])
    def add(self, request):
        user = request.user
        product_id = request.data.get('product_id')
        quantity = int(request.data.get('quantity', 1))

        product = get_object_or_404(Product, id=product_id)

        if product.stock_quantity < quantity:
            return Response({'error': 'Not enough stock'}, status=status.HTTP_400_BAD_REQUEST)

        cart_item, created = Cart.objects.get_or_create(user=user, product=product)
        if not created:
            cart_item.quantity += quantity
        else:
            cart_item.quantity = quantity
        cart_item.save()

        return Response(CartSerializer(cart_item).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def remove(self, request):
        user = request.user
        product_id = request.data.get('product_id')

        cart_item = Cart.objects.filter(user=user, product_id=product_id).first()
        if cart_item:
            cart_item.delete()
            return Response({'success': 'Item removed from cart'}, status=status.HTTP_200_OK)
        return Response({'error': 'Item not found in cart'}, status=status.HTTP_404_NOT_FOUND)


def add_to_cart(request, product_id):
    if request.method == "POST":
        qty = int(request.POST.get("qty", 1))

        if request.user.is_authenticated:
            product = get_object_or_404(Product, id=product_id)
            cart_item, created = Cart.objects.get_or_create(
                user=request.user,
                product=product,
                defaults={"quantity": qty}
            )
            if not created:
                cart_item.quantity += qty
                cart_item.save()

            # ✅ Stay on same page
            return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))
        else:
            request.session["pending_cart"] = {
                "product_id": product_id,
                "qty": qty
            }
            return redirect("login")
    return redirect("index")


@login_required
def cart_view(request):
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)

    # Handle quantity changes
    if request.method == "POST":
        product_id = request.POST.get("product_id")
        action = request.POST.get("action")
        qty_input = request.POST.get("quantity")

        if product_id and action:
            cart_item = get_object_or_404(Cart, user=user, product_id=product_id)
            product = cart_item.product

            # Determine new quantity
            if action == "increment":
                if cart_item.quantity < product.stock_quantity:
                    cart_item.quantity += 1
                else:
                    messages.warning(request, f"Cannot add more. Only {product.stock_quantity} in stock.")
            elif action == "decrement":
                cart_item.quantity -= 1
                if cart_item.quantity <= 0:
                    cart_item.delete()
                    messages.info(request, f"{product.name} removed from cart.")
                else:
                    cart_item.save()
            elif action == "update":
                try:
                    new_qty = int(qty_input)
                    if new_qty <= 0:
                        cart_item.delete()
                        messages.info(request, f"{product.name} removed from cart.")
                    elif new_qty > product.stock_quantity:
                        messages.warning(request, f"Cannot set quantity higher than stock ({product.stock_quantity}).")
                    else:
                        cart_item.quantity = new_qty
                        cart_item.save()
                        messages.success(request, f"{product.name} quantity updated.")
                except ValueError:
                    messages.error(request, "Invalid quantity input.")

        return redirect("cart")

    # GET request: display cart
    cart_items = Cart.objects.filter(user=user)
    cart_data = []
    total = Decimal(0)
    for item in cart_items:
        subtotal = item.product.price * item.quantity
        total += subtotal
        cart_data.append({
            "product": item.product,
            "quantity": item.quantity,
            "price": item.product.price,
            "subtotal": subtotal,
        })

    return render(request, "cart.html", {
        "cart_items": cart_data,
        "total": total,
        "profile": profile,
    })
# ORDERS
class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def checkout(self, request):
        user = request.user
        delivery_address = request.data.get('delivery_address')

        cart_items = Cart.objects.filter(user=user)
        if not cart_items.exists():
            return Response({'error': 'Cart is empty'}, status=status.HTTP_400_BAD_REQUEST)

        total_price = 0
        order = Order.objects.create(user=user, total_price=0, delivery_address=delivery_address)

        for item in cart_items:
            product = item.product
            if product.stock_quantity < item.quantity:
                transaction.set_rollback(True)
                return Response({'error': f'Not enough stock for {product.name}'}, status=status.HTTP_400_BAD_REQUEST)

            product.stock_quantity -= item.quantity
            product.save()

            OrderItem.objects.create(order=order, product=product, quantity=item.quantity, price=product.price)
            total_price += product.price * item.quantity

        order.total_price = total_price
        order.save()
        cart_items.delete()

        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


@login_required
def checkout_view(request):
    if request.method != "POST":
        return redirect('cart')

    user = request.user
    delivery_address = request.POST.get('delivery_address')
    payment_method = request.POST.get('payment_method')
    cart_items = Cart.objects.filter(user=user)

    if not cart_items.exists():
        return JsonResponse({'error': 'Cart is empty'}, status=400)

    # Calculate total
    total = sum(item.product.price * item.quantity for item in cart_items)

    # Create pending order
    order = Order.objects.create(
        user=user,
        delivery_address=delivery_address,
        total_price=total,
        payment_method=payment_method,
        status='pending'
    )

    # Add order items
    for item in cart_items:
        OrderItem.objects.create(
            order=order,
            product=item.product,
            quantity=item.quantity,
            price=item.product.price
        )

    if payment_method == 'cash':
        # COD: mark as paid immediately
        for item in cart_items:
            product = item.product
            product.stock_quantity -= item.quantity
            product.save()
        cart_items.delete()
        order.status = 'paid'
        order.save()
        return redirect('customer_orders')

    elif payment_method == 'card':
        # Stripe payment: create checkout session
        line_items = [
            {
                "price_data": {
                    "currency": "zar",
                    "product_data": {"name": item.product.name},
                    "unit_amount": int(item.price * 100),
                },
                "quantity": item.quantity,
            }
            for item in order.orderitem_set.all()
        ]

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url=request.build_absolute_uri(reverse('stripe_success', args=[order.id])),
            cancel_url=request.build_absolute_uri(reverse('stripe_cancel', args=[order.id])),
            metadata={'order_id': str(order.id)}
        )

        return JsonResponse({'checkout_url': session.url})

    else:
        return JsonResponse({'error': 'Unsupported payment method'}, status=400)




@login_required
def order_confirmation(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    order_items = OrderItem.objects.filter(order=order)

    return render(request, "order_confirmation.html", {
        "order": order,
        "order_items": order_items,
    })


# REGISTER
class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)
    cell = forms.CharField(max_length=15, required=True, label="Cell Number")
    user_type = forms.ChoiceField(
        choices=[("customer", "Customer"), ("vendor", "Vendor")],
        widget=forms.RadioSelect,
        required=True
    )

    class Meta:
        model = CustomUser
        fields = ("username", "email", "cell", "user_type", "password1", "password2")


def register_view(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.email = form.cleaned_data["email"]
            user.cell = form.cleaned_data["cell"]
            user.user_type = form.cleaned_data["user_type"]
            user.save()
            messages.success(request, "Account created successfully. You can now log in.")
            return redirect("login")
    else:
        form = RegisterForm()

    return render(request, "register.html", {"form": form})


# LOGIN
class CustomLoginView(LoginView):
    template_name = "login.html"

    def form_valid(self, form):
        response = super().form_valid(form)

        pending_cart = self.request.session.pop("pending_cart", None)
        if pending_cart:
            product = Product.objects.get(id=pending_cart["product_id"])
            qty = int(pending_cart["qty"])

            cart_item, created = Cart.objects.get_or_create(
                user=self.request.user,
                product=product,
                defaults={"quantity": qty}
            )
            if not created:
                cart_item.quantity += qty
                cart_item.save()

        return response

    def get_success_url(self):
        user = self.request.user
        if user.user_type == "customer":
            return "/cart/"
        elif user.user_type == "vendor":
            return "/vendor_dash/"
        return "/"


# PRODUCT FORMS
class ProductForm(ModelForm):
    class Meta:
        model = Product
        fields = ["name", "category", "price", "stock_quantity", "image", "description"]


# VENDOR PRODUCT MANAGEMENT
@login_required
def vendor_dash(request):
    if request.user.user_type != "vendor":
        messages.error(request, "You don’t have permission to view this page.")
        return redirect("index")

    products = Product.objects.filter(vendor=request.user)
    return render(request, "vendor_dash.html", {"products": products})


@login_required
def add_product(request):
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can add products.")
        return redirect("index")

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            product.vendor = request.user
            product.save()
            messages.success(request, "Product added successfully.")
            return redirect("vendor_dash")
    else:
        form = ProductForm()

    return render(request, "product_form.html", {"form": form, "title": "Add Product"})


@login_required
def edit_product(request, product_id):
    product = get_object_or_404(Product, id=product_id, vendor=request.user)

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, "Product updated successfully.")
            return redirect("vendor_products")
    else:
        form = ProductForm(instance=product)

    return render(request, "product_form.html", {"form": form, "title": "Edit Product"})


@login_required
def delete_product(request, product_id):
    product = get_object_or_404(Product, id=product_id, vendor=request.user)
    if request.method == "POST":
        product.delete()
        messages.success(request, "Product deleted successfully.")
        return redirect("vendor_products")

    return render(request, "vendor/confirm_delete.html", {"product": product})


@require_POST
@login_required(login_url='/accounts/login/')
def remove_from_cart(request, product_id):
    cart_item = Cart.objects.filter(user=request.user, product_id=product_id).first()
    if cart_item:
        cart_item.delete()
        messages.success(request, "Item removed from your cart.")
    else:
        messages.error(request, "Item not found in your cart.")
    return redirect("cart")


@login_required
def profile_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.user.user_type == "vendor":
        products = Product.objects.filter(vendor=request.user)
        sales = OrderItem.objects.filter(product__vendor=request.user).select_related("order", "product")
        for s in sales:
            s.line_total = s.price * s.quantity

        return render(request, "vendor/vendor_profile.html", {
            "profile": profile,
            "products": products,
            "sales": sales,
        })

    else:  # customer
        if request.method == "POST":
            form = ProfileForm(request.POST, instance=profile, user=request.user)
            if form.is_valid():
                form.save()
                messages.success(request, "Profile updated successfully!")
                return redirect("profile")
            else:
                messages.error(request, "Please correct the errors below.")
        else:
            form = ProfileForm(instance=profile, user=request.user)

        orders = Order.objects.filter(user=request.user).order_by("-created_at")

        return render(request, "profile.html", {
            "form": form,
            "profile": profile,
            "orders": orders,
        })



@login_required
def profile_edit(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            request.user.email = request.POST.get("email", request.user.email)
            request.user.save()
            messages.success(request, "Profile updated successfully!")
            return redirect("profile")
    else:
        form = ProfileForm(instance=profile)

    return render(request, "profile_edit.html", {
        "form": form,
        "user": request.user,
    })


@login_required
def invoice_view(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)

    # Display PDF in browser instead of forcing download
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="invoice_{order.id}.pdf"'

    p = canvas.Canvas(response, pagesize=A4)
    width, height = A4

    # Header
    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, height - 50, "Nyarie's Market - Invoice")

    # Order details
    p.setFont("Helvetica", 12)
    p.drawString(100, height - 100, f"Order ID: {order.id}")
    p.drawString(100, height - 120, f"Date: {order.created_at.strftime('%Y-%m-%d')}")
    p.drawString(100, height - 140, f"Customer: {order.user.username}")
    p.drawString(100, height - 160, f"Delivery Address: {order.delivery_address}")

    # Items
    y = height - 200
    total = 0
    for item in order.orderitem_set.all():
        line = f"{item.product.name} (x{item.quantity}) - R{item.price * item.quantity:.2f}"
        p.drawString(100, y, line)
        y -= 20
        total += item.price * item.quantity

    # Total
    p.drawString(100, y - 20, f"Total: R{total:.2f}")

    p.showPage()
    p.save()

    return response


@receiver(post_save, sender=CustomUser)
def create_profile_for_new_user(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)


@login_required
def vendor_edit_profile(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = VendorProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully!")
            return redirect("profile")   # ✅ goes back to profile_view
    else:
        form = VendorProfileForm(
            instance=profile,
            initial={
                "first_name": request.user.first_name,
                "last_name": request.user.last_name,
                "email": request.user.email,
            }
        )

    return render(request, "vendor/vendor_edit_profile.html", {"form": form})


@login_required
def category_list(request):
    categories = Category.objects.all()
    return render(request, "category_list.html", {"categories": categories})


@login_required
def inventory_view(request):
    products = Product.objects.filter(vendor=request.user)
    return render(request, "vendor/inventory.html", {"products": products})


@login_required
def customer_orders_view(request):
    orders = Order.objects.filter(
        user=request.user, status="pending"
    ).order_by("-created_at")
    return render(request, "customer_orders.html", {"orders": orders})


@login_required
def order_history_view(request):
    if request.user.user_type == "customer":
        completed_orders = Order.objects.filter(
            user=request.user,
            status="paid"
        ).order_by("-created_at")

        cancelled_orders = Order.objects.filter(
            user=request.user,
            status="cancelled"
        ).order_by("-created_at")

        return render(request, "order_history.html", {
            "completed_orders": completed_orders,
            "cancelled_orders": cancelled_orders,
        })

    elif request.user.user_type == "vendor":
        completed_orders = Order.objects.filter(
            orderitem__product__vendor=request.user,
            status="paid"
        ).distinct().order_by("-created_at")

        cancelled_orders = Order.objects.filter(
            orderitem__product__vendor=request.user,
            status="cancelled"
        ).distinct().order_by("-created_at")

        return render(request, "vendor/vendor_order_history.html", {
            "completed_orders": completed_orders,
            "cancelled_orders": cancelled_orders,
        })

    else:
        messages.error(request, "You do not have permission to view this page.")
        return redirect("index")


@login_required
def customer_list(request):
    # vendors can see their customers (from orders)
    if request.user.user_type != "vendor":
        messages.error(request, "You don’t have permission to view this page.")
        return redirect("index")

    customers = CustomUser.objects.filter(
        orders__orderitem__product__vendor=request.user,
        user_type="customer"
    ).distinct()

    return render(request, "customer_list.html", {"customers": customers})

@login_required
def reports_view(request):
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can view reports.")
        return redirect("index")

    # default filter
    period = request.GET.get("period", "all")

    # only PAID sales
    sales = OrderItem.objects.filter(
        product__vendor=request.user,
        order__status="paid"
    )

    now = timezone.now()

    if period == "day":
        start_date = now - timedelta(days=1)
        sales = sales.filter(order__created_at__gte=start_date)
    elif period == "week":
        start_date = now - timedelta(weeks=1)
        sales = sales.filter(order__created_at__gte=start_date)
    elif period == "month":
        start_date = now - timedelta(days=30)
        sales = sales.filter(order__created_at__gte=start_date)
    # "all" → no date filter

    # Calculate the vendor's total sales correctly
    total_sales = sales.aggregate(
        total=Sum(F("price") * F("quantity"), output_field=DecimalField())
    )["total"] or 0

    return render(request, "vendor/reports.html", {
        "sales": sales,
        "total_sales": total_sales,
        "period": period,
    })


@login_required
def vendor_profile_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    return render(request, "vendor/vendor_profile.html", {"profile": profile})


@login_required
def settings_view(request):
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can access settings.")
        return redirect("index")

    settings_obj, _ = VendorSettings.objects.get_or_create(vendor=request.user)

    if request.method == "POST":
        form = VendorSettingsForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            settings_obj.default_currency = data["default_currency"]
            settings_obj.low_stock_threshold = data["low_stock_threshold"]
            settings_obj.notify_new_order = data["notify_new_order"]
            settings_obj.notify_low_stock = data["notify_low_stock"]
            settings_obj.default_report_period = data["default_report_period"]
            settings_obj.save()
            messages.success(request, "Settings saved successfully.")
            return redirect("settings")
    else:
        form = VendorSettingsForm(initial={
            "default_currency": settings_obj.default_currency,
            "low_stock_threshold": settings_obj.low_stock_threshold,
            "notify_new_order": settings_obj.notify_new_order,
            "notify_low_stock": settings_obj.notify_low_stock,
            "default_report_period": settings_obj.default_report_period,
        })

    return render(request, "vendor/settings.html", {"form": form})


@login_required
def product_list(request):
    products = Product.objects.filter(vendor=request.user)  # only vendor's products
    return render(request, "vendor/product_list.html", {"products": products})


@login_required
def vendor_products(request):
    if request.user.user_type != "vendor":
        messages.error(request, "You don’t have permission to view this page.")
        return redirect("index")

    products = Product.objects.filter(vendor=request.user)
    return render(request, "vendor/vendor_products.html", {"products": products})


@login_required
def sales_view(request):
    if request.user.user_type != "vendor":
        messages.error(request, "You don’t have permission to view this page.")
        return redirect("index")

    sales = (
        OrderItem.objects.filter(product__vendor=request.user)
        .select_related("order", "product")
        .order_by("-order__created_at")
    )

    now = timezone.now()
    today = now.date()
    start_of_week = today - timedelta(days=today.weekday())  # Monday
    start_of_month = today.replace(day=1)

    # Totals
    total_sales = 0
    sales_today = 0
    sales_week = 0
    sales_month = 0

    for item in sales:
        total_sales += item.subtotal

        order_date = item.order.created_at.date()
        if order_date == today:
            sales_today += item.subtotal
        if order_date >= start_of_week:
            sales_week += item.subtotal
        if order_date >= start_of_month:
            sales_month += item.subtotal

    # === Chart Data (Last 30 Days) ===
    start_date = today - timedelta(days=29)
    daily_sales = (
        OrderItem.objects.filter(product__vendor=request.user, order__created_at__date__gte=start_date)
        .values("order__created_at__date")
        .annotate(total=Sum("price"))
        .order_by("order__created_at__date")
    )

    # Prepare labels and values
    labels = []
    data = []
    for i in range(30):
        day = start_date + timedelta(days=i)
        labels.append(day.strftime("%Y-%m-%d"))
        day_sales = next((x["total"] for x in daily_sales if x["order__created_at__date"] == day), 0)
        data.append(float(day_sales))

    return render(request, "vendor/sales.html", {
        "sales": sales,
        "total_sales": total_sales,
        "sales_today": sales_today,
        "sales_week": sales_week,
        "sales_month": sales_month,
        "chart_labels": labels,
        "chart_data": data,
    })


def filter_sales_by_period(user, period):
    sales = OrderItem.objects.filter(product__vendor=user)
    now = timezone.now()

    if period == "day":
        sales = sales.filter(order__created_at__gte=now - timedelta(days=1))
    elif period == "week":
        sales = sales.filter(order__created_at__gte=now - timedelta(weeks=1))
    elif period == "month":
        sales = sales.filter(order__created_at__gte=now - timedelta(days=30))
    # "all" = no filter

    return sales


@login_required
def download_report(request):
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can download reports.")
        return redirect("index")

    period = request.GET.get("period", "all")
    sales = OrderItem.objects.filter(product__vendor=request.user)

    now = timezone.now()
    if period == "day":
        sales = sales.filter(order__created_at__gte=now - timedelta(days=1))
    elif period == "week":
        sales = sales.filter(order__created_at__gte=now - timedelta(weeks=1))
    elif period == "month":
        sales = sales.filter(order__created_at__gte=now - timedelta(days=30))

    total_sales = sum(item.price * item.quantity for item in sales)

    # Create PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)

    styles = getSampleStyleSheet()
    elements = []

    # Title
    elements.append(Paragraph(f"Sales Report ({period.title()})", styles["Title"]))
    elements.append(Spacer(1, 12))

    # Table data
    data = [["Order ID", "Product", "Qty", "Unit Price", "Total", "Date"]]
    for item in sales:
        data.append([
            str(item.order.id),
            item.product.name,
            str(item.quantity),
            f"R{item.price:.2f}",
            f"R{item.price * item.quantity:.2f}",
            item.order.created_at.strftime("%Y-%m-%d %H:%M"),
        ])

    # Add total row
    data.append(["", "", "", "Total Sales", f"R{total_sales:.2f}", ""])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
        ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
    ]))

    elements.append(table)

    # Build PDF
    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="report_{period}.pdf"'
    return response


@login_required
def print_report(request):
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can print reports.")
        return redirect("index")

    period = request.GET.get("period", "all")
    sales = OrderItem.objects.filter(product__vendor=request.user)

    now = timezone.now()
    if period == "day":
        sales = sales.filter(order__created_at__gte=now - timedelta(days=1))
    elif period == "week":
        sales = sales.filter(order__created_at__gte=now - timedelta(weeks=1))
    elif period == "month":
        sales = sales.filter(order__created_at__gte=now - timedelta(days=30))

    total_sales = sum(item.price * item.quantity for item in sales)

    return render(request, "vendor/print_report.html", {
        "sales": sales,
        "total_sales": total_sales,
        "period": period,
    })


def product_search(request):
    query = request.GET.get("q", "").strip()
    category_id = request.GET.get("category", "")

    products = Product.objects.all()

    if query:
        products = products.filter(name__icontains=query)

    if category_id:
        products = products.filter(category_id=category_id)

    context = {
        "products": products,
        "query": query,
        "category_id": category_id,
        "categories": Category.objects.all(),
    }
    return render(request, "search_results.html", context)


def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    return render(request, "product_detail.html", {"product": product})


@login_required
def vendor_orders(request):
    if request.user.user_type != "vendor":
        messages.error(request, "Access denied.")
        return redirect("index")

    orders = Order.objects.filter(
        orderitem__product__vendor=request.user,
        status="pending"
    ).distinct().order_by("-created_at")

    return render(request, "vendor/vendor_orders.html", {"orders": orders})


@login_required
def customer_orders(request):
    orders = request.user.orders.filter(status="pending").order_by("-created_at")
    return render(request, "customer_orders.html", {"orders": orders})


@login_required
def customer_order_history(request):
    completed_orders = request.user.orders.filter(
        status="paid"
    ).order_by("-created_at")

    cancelled_orders = request.user.orders.filter(
        status="cancelled"
    ).order_by("-created_at")

    return render(request, "customer_order_history.html", {
        "completed_orders": completed_orders,
        "cancelled_orders": cancelled_orders,
    })


@login_required
def update_order_status(request, order_id):
    """
    Vendor updates status of their own orders.
    Only updates items that belong to the vendor.
    """
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can update orders.")
        return redirect("vendor_orders")

    order = (
        Order.objects.filter(id=order_id, orderitem__product__vendor=request.user)
        .distinct()
        .first()
    )

    if not order:
        messages.error(request, "Order not found or not linked to your products.")
        return redirect("vendor_orders")

    if request.method == "POST":
        new_status = request.POST.get("status")
        if new_status in dict(Order.STATUS_CHOICES).keys():
            order.status = new_status
            order.save()

            # Only update vendor-specific items
            if new_status == "paid":
                for item in order.orderitem_set.filter(product__vendor=request.user):
                    item.product.stock_quantity -= item.quantity
                    item.product.save()

            messages.success(request, f"Order #{order.id} updated to {new_status}.")
        else:
            messages.error(request, "Invalid status update.")

    return redirect("vendor_orders")


@login_required
def mark_order_paid(request, order_id):
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can update orders.")
        return redirect("orders")

    order = get_object_or_404(Order, id=order_id)

    # make sure this order has at least one product from this vendor
    if not order.orderitem_set.filter(product__vendor=request.user).exists():
        messages.error(request, "You cannot update this order.")
        return redirect("orders")

    # mark order as paid
    order.status = "paid"
    order.save()

    # update vendor's inventory and sales
    for item in order.orderitem_set.filter(product__vendor=request.user):
        product = item.product
        product.stock_quantity -= item.quantity
        product.save()
        # (optional: add sales tracking model if you want)

    messages.success(request, f"Order #{order.id} marked as Paid.")
    return redirect("orders")


@csrf_exempt
def create_checkout_session(request):
    if request.method == "POST":
        # Get the current user's cart
        cart_items = Cart.objects.filter(user=request.user)
        if not cart_items.exists():
            return redirect("cart")  # or show a message

        # ✅ Create a pending order
        order = Order.objects.create(
            user=request.user,
            total_price=0,
            status="pending",
        )

        line_items = []
        total_price = 0
        for item in cart_items:
            line_total = item.product.price * item.quantity
            OrderItem.objects.create(
                order=order,
                product=item.product,
                quantity=item.quantity,
                price=item.product.price,
            )
            total_price += line_total

            # Stripe line items
            line_items.append({
                "price_data": {
                    "currency": "zar",
                    "product_data": {"name": item.product.name},
                    "unit_amount": int(item.product.price * 100),
                },
                "quantity": item.quantity,
            })

        order.total_price = total_price
        order.save()
        cart_items.delete()

        # ✅ Create Stripe Checkout session
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=line_items,
            mode="payment",
            success_url=request.build_absolute_uri(
                reverse("success", args=[order.id])
            ),
            cancel_url=request.build_absolute_uri(
                reverse("cancel", args=[order.id])
            ),
            metadata={"order_id": str(order.id)},
        )

        return redirect(session.url, code=303)

    return redirect("cart")


@login_required
def success(request, order_id):
    # Get the order
    order = Order.objects.get(id=order_id, user=request.user)

    # Update customer order status
    order.status = "paid"
    order.save()

    # Automatically update vendor-specific items
    for item in order.orderitem_set.all():
        # You could have a separate status per item if needed
        # For now, just ensure the vendor's pending orders reflect the order status
        pass  # No extra DB update needed if you rely on Order.status in vendor view

    # Render the success page
    return render(request, "success.html", {"order": order})


@login_required
def cancel(request, order_id):
    order = Order.objects.get(id=order_id, user=request.user)
    order.status = "cancelled"
    order.save()

    order_items = order.orderitem_set.all()

    return render(request, "cancel.html", {"order": order, "order_items": order_items})


def customer_dashboard(request):
    orders = request.user.orders.all() if request.user.is_authenticated else []
    return render(request, "customer_order_history.html", {"orders": orders})


@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse(status=400)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        order_id = session["metadata"]["order_id"]

        try:
            order = Order.objects.get(id=order_id)
            if order.status != "paid":
                order.status = "paid"
                order.save()

                # Reduce stock for all items
                for item in order.orderitem_set.all():
                    product = item.product
                    if product.stock_quantity >= item.quantity:
                        product.stock_quantity -= item.quantity
                        product.save()
        except Order.DoesNotExist:
            return HttpResponse(status=404)

    return HttpResponse(status=200)


@login_required
def stripe_success(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)

    if order.status != "paid":
        order.status = "paid"
        order.save()

        # Reduce inventory for card payments
        for item in order.orderitem_set.all():
            product = item.product
            if product.stock_quantity >= item.quantity:
                product.stock_quantity -= item.quantity
                product.save()

    return render(request, "success.html", {"order": order})



def get_vendor_orders(vendor, status_list=None):
    """
    Returns orders containing the vendor's products.
    Optionally filter by status.
    """
    qs = OrderItem.objects.filter(product__vendor=vendor)
    orders = Order.objects.filter(
        orderitem__product__vendor=vendor
    )
    if status_list:
        orders = orders.filter(status__in=status_list)

    vendor_items_qs = qs.select_related("product")
    orders = orders.prefetch_related(
        Prefetch("orderitem_set", queryset=vendor_items_qs, to_attr="vendor_items_list")
    ).distinct().order_by("-created_at")

    # add vendor subtotal
    for order in orders:
        order.vendor_subtotal = sum(item.subtotal for item in order.vendor_items_list)

    return orders


@login_required
def vendor_orders_view(request):
    if request.user.user_type != "vendor":
        messages.error(request, "Access denied.")
        return redirect("index")

    orders = get_vendor_orders(request.user, status_list=["pending"])
    return render(request, "vendor/vendor_orders.html", {"orders": orders})


@login_required
def vendor_order_history(request):
    if request.user.user_type != "vendor":
        messages.error(request, "Access denied.")
        return redirect("index")

    orders = get_vendor_orders(request.user, status_list=["paid", "cancelled"])
    return render(request, "vendor/vendor_order_history.html", {"orders": orders})


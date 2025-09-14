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
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django import forms
from django.forms import ModelForm
from django.http import HttpResponseRedirect
from .models import CustomUser, Profile, Category, Product, Cart, Order, OrderItem
from .serializers import (
    UserSerializer, ProfileSerializer, CategorySerializer,
    ProductSerializer, CartSerializer, OrderSerializer, OrderItemSerializer)
from django.shortcuts import render, redirect
from .forms import ProfileForm, VendorProfileForm
from .models import Profile, Order
from django.http import HttpResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import CustomUser, Profile
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum


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
    cart_items = Cart.objects.filter(user=request.user)
    profile, _ = Profile.objects.get_or_create(user=request.user)

    cart_data = []
    total = 0
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


@login_required(login_url='/accounts/login/')
def checkout_view(request):
    if request.method == "POST":
        delivery_address = request.POST.get("delivery_address", "").strip()
        payment_method = request.POST.get("payment_method", "").strip()
        cart_items = Cart.objects.filter(user=request.user)

        if not cart_items.exists():
            messages.error(request, "Your cart is empty.")
            return redirect("cart")

        if not delivery_address:
            messages.error(request, "Please provide a delivery address.")
            return redirect("cart")

        total_price = 0
        order = Order.objects.create(
            user=request.user,
            total_price=0,
            delivery_address=delivery_address,
            created_at=timezone.now(),
        )

        for item in cart_items:
            OrderItem.objects.create(
                order=order,
                product=item.product,
                quantity=item.quantity,
                price=item.product.price,
            )
            total_price += item.product.price * item.quantity

            item.product.stock_quantity -= item.quantity
            item.product.save()

        order.total_price = total_price
        order.save()
        cart_items.delete()

        # Save to profile defaults
        profile, _ = Profile.objects.get_or_create(user=request.user)
        profile.delivery_address = delivery_address
        profile.payment_method = payment_method
        profile.save()

        return redirect("order_confirmation", order_id=order.id)

    return redirect("cart")


@login_required(login_url='/accounts/login/')
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


# VENDOR DASH
@login_required
def vendor_dash(request):
    return render(request, "vendor_dash.html")


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
            return redirect("vendor_dash")
    else:
        form = ProductForm(instance=product)

    return render(request, "product_form.html", {"form": form, "title": "Edit Product"})


@login_required
def delete_product(request, product_id):
    product = get_object_or_404(Product, id=product_id, vendor=request.user)
    if request.method == "POST":
        product.delete()
        messages.success(request, "Product deleted successfully.")
        return redirect("vendor_dash")

    return render(request, "confirm_delete.html", {"product": product})


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

        return render(request, "vendor_profile.html", {
            "profile": profile,
            "products": products,
            "sales": sales,
        })

    else:  # customer
        if request.method == "POST":
            form = ProfileForm(request.POST, instance=profile)
            if form.is_valid():
                form.save()
                messages.success(request, "Profile updated successfully!")
                return redirect("profile")
            else:
                messages.error(request, "Please correct the errors below.")
        else:
            form = ProfileForm(instance=profile)

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
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="invoice_{order.id}.pdf"'

    p = canvas.Canvas(response, pagesize=A4)
    width, height = A4

    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, height - 50, "My Bakery - Invoice")

    p.setFont("Helvetica", 12)
    p.drawString(100, height - 100, f"Order ID: {order.id}")
    p.drawString(100, height - 120, f"Date: {order.created_at.strftime('%Y-%m-%d')}")
    p.drawString(100, height - 140, f"Customer: {order.user.username}")
    p.drawString(100, height - 160, f"Delivery Address: {order.delivery_address}")

    y = height - 200
    total = 0
    for item in order.items.all():
        line = f"{item.product.name} (x{item.quantity}) - ${item.price * item.quantity:.2f}"
        p.drawString(100, y, line)
        y -= 20
        total += item.price * item.quantity

    p.drawString(100, y - 20, f"Total: ${total:.2f}")

    p.showPage()
    p.save()
    return response


@receiver(post_save, sender=CustomUser)
def create_profile_for_new_user(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)


@login_required
def download_report(request):
    # Later you’ll generate a PDF/CSV here
    return HttpResponse("Download report (to be implemented)", content_type="text/plain")


@login_required
def print_report(request):
    # Later you’ll render a printable HTML report
    return HttpResponse("Print report (to be implemented)", content_type="text/plain")


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

    return render(request, "vendor_edit_profile.html", {"form": form})


@login_required
def category_list(request):
    categories = Category.objects.all()
    return render(request, "category_list.html", {"categories": categories})


@login_required
def inventory_view(request):
    products = Product.objects.filter(vendor=request.user)
    return render(request, "inventory.html", {"products": products})


@login_required
def orders_view(request):
    if request.user.user_type == "customer":
        orders = Order.objects.filter(user=request.user)
    else:  # vendor
        orders = Order.objects.filter(orderitem__product__vendor=request.user).distinct()

    return render(request, "orders.html", {"orders": orders})


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
    return render(request, "reports.html")


@login_required
def vendor_profile_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    return render(request, "vendor_profile.html", {"profile": profile})


@login_required
def settings_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = VendorProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Settings updated successfully.")
            return redirect("settings")  # stay on same page
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = VendorProfileForm(
            instance=profile,
            initial={
                "first_name": request.user.first_name,
                "last_name": request.user.last_name,
                "email": request.user.email,
            }
        )

    return render(request, "settings.html", {"form": form})


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
        item.subtotal = item.price * item.quantity
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

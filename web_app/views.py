from decimal import Decimal
from functools import wraps

from django.contrib.staticfiles import finders
from django.core.paginator import Paginator
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404, render, redirect
from django.db import transaction
from django.contrib.auth.models import Group
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.contrib.auth.forms import UserCreationForm
from django import forms
from django.forms import ModelForm
from django.http import HttpResponseRedirect, JsonResponse
from bakery_app.settings import MIN_ORDER_AMOUNT_ZAR
from .decorators import vendor_required, admin_required
from .models import CustomUser, Profile, Category, Product, Cart, Order, OrderItem, VendorSettings, ActivityLog
from .serializers import (
    UserSerializer, ProfileSerializer, CategorySerializer,
    ProductSerializer, CartSerializer, OrderSerializer, OrderItemSerializer)
from .forms import ProfileForm, VendorProfileForm, VendorSettingsForm, VendorLoginForm, VendorForm, CustomerForm, \
    CategoryForm
from django.http import HttpResponse
from reportlab.pdfgen import canvas
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum, Prefetch, F, DecimalField, ExpressionWrapper, Max, Count
import io
import stripe
from django.conf import settings
import logging
from .utils import log_activity
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import os
import uuid
from django.utils.text import slugify


logger = logging.getLogger('portal')
stripe.api_key = settings.STRIPE_SECRET_KEY


# BASIC PAGES AND NAVIGATION
# Public-facing pages for browsing categories and products

def index(request):
    """Homepage displaying all categories"""
    categories = Category.objects.all()
    return render(request, "index.html", {"categories": categories})


def category_detail(request, category_id):
    """Display products within a specific category"""
    category = get_object_or_404(Category, id=category_id)
    products = Product.objects.filter(category=category)

    # ✅ Calculate cart item count if user is authenticated
    cart_item_count = 0
    if request.user.is_authenticated:
        cart_item_count = Cart.objects.filter(user=request.user).aggregate(
            total=Sum('quantity')
        )['total'] or 0

    return render(request, "category_detail.html", {
        "category": category,
        "products": products,
        "cart_item_count": cart_item_count,  # pass to template
    })


@login_required
def category_list(request):
    """List all categories for logged-in users"""
    categories = Category.objects.all()
    return render(request, "category_list.html", {"categories": categories})


def product_detail(request, product_id):
    """Display detailed view of a single product"""
    product = get_object_or_404(Product, id=product_id)
    return render(request, "vendor/product_detail.html", {"product": product})


def product_search(request):
    """Search and filter products by name and category"""
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


# USER MANAGEMENT AND AUTHENTICATION
# Functions for user registration, login, and profile management

class UserViewSet(viewsets.ModelViewSet):
    """API viewset for user management"""
    queryset = CustomUser.objects.all()
    serializer_class = UserSerializer

    @action(detail=False, methods=['post'])
    def register(self, request):
        """API endpoint for user registration"""
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
    """API viewset for profile management"""
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer


class RegisterForm(UserCreationForm):
    """Form for user registration"""
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
    """Handle user registration form"""
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


class CustomLoginView(LoginView):
    """Custom login view with cart persistence"""
    template_name = "login.html"
    authentication_form = VendorLoginForm

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


@receiver(post_save, sender=CustomUser)
def create_profile_for_new_user(sender, instance, created, **kwargs):
    """Automatically create profile for new users"""
    if created:
        Profile.objects.get_or_create(user=instance)


# PROFILE MANAGEMENT
# Functions for viewing and editing user profiles

@login_required
def profile_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.user.user_type == "vendor":
        products = Product.objects.filter(vendor=request.user)
        sales = OrderItem.objects.filter(product__vendor=request.user).select_related("order", "product")
        for s in sales:
            s.line_total = s.price * s.quantity

        # Log viewing profile
        log_activity(request.user, "Viewed Vendor Profile", "Vendor accessed profile page", request.META.get("REMOTE_ADDR"))

        return render(request, "vendor/vendor_profile.html", {
            "profile": profile,
            "products": products,
            "sales": sales,
        })

    else:  # customer
        # Log viewing profile
        log_activity(request.user, "Viewed Customer Profile", "Customer accessed profile page", request.META.get("REMOTE_ADDR"))

        orders = Order.objects.filter(user=request.user).order_by("-created_at")

        return render(request, "profile.html", {
            "profile": profile,
            "orders": orders,
        })


@login_required
def profile_edit(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile, user=request.user)
        if form.is_valid():
            form.save()
            log_activity(request.user, "Edited Profile", "Customer updated profile details", request.META.get("REMOTE_ADDR"))
            messages.success(request, "Profile updated successfully!")
            return redirect("profile")  # Redirect back to profile view
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = ProfileForm(instance=profile, user=request.user)

    return render(request, "profile_edit.html", {"form": form, "user": request.user})

@login_required
def vendor_edit_profile(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = VendorProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            log_activity(request.user, "Edited Profile", "Vendor updated profile details", request.META.get("REMOTE_ADDR"))
            messages.success(request, "Profile updated successfully!")
            return redirect("profile")
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
def vendor_profile_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    log_activity(request.user, "Viewed Vendor Profile", "Vendor accessed profile page", request.META.get("REMOTE_ADDR"))
    return render(request, "vendor/vendor_profile.html", {"profile": profile})


# PRODUCT MANAGEMENT
# Functions for managing product catalog (vendors only)

class CategoryViewSet(viewsets.ModelViewSet):
    """API viewset for category management"""
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class ProductViewSet(viewsets.ModelViewSet):
    """API viewset for product management"""
    queryset = Product.objects.all()
    serializer_class = ProductSerializer


class ProductForm(ModelForm):
    """Form for adding/editing products"""
    class Meta:
        model = Product
        fields = ["name", "category", "price", "stock_quantity", "image", "description"]


@login_required
def vendor_dash(request):
    """Vendor dashboard showing their products"""
    if request.user.user_type != "vendor" and request.user.user_type != "admin":
        messages.error(request, "You don't have permission to view this page.")
        return redirect("index")

    products = Product.objects.filter(vendor=request.user)
    return render(request, "vendor_dash.html", {"products": products})


@login_required
def add_product(request):
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can add products.")
        log_activity(request.user, "Unauthorized add_product attempt")
        return redirect("index")

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            product.vendor = request.user
            product.save()

            # ✅ Log activity
            log_activity(
                user=request.user,
                action="Added Product",
                details=f"Product: {product.name} (ID {product.id})"
            )

            messages.success(request, "Product added successfully.")
            return redirect("vendor_dash")
    else:
        form = ProductForm()

    return render(request, "product_form.html", {"form": form, "title": "Add Product"})


@login_required
def edit_product(request, product_id):
    """Edit existing product (vendors only)"""
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
    """Delete product (vendors only)"""
    product = get_object_or_404(Product, id=product_id, vendor=request.user)
    if request.method == "POST":
        log_activity(
            user=request.user,
            action="Deleted Product",
            details=f"Product: {product.name} (ID {product.id})"
        )

        product.delete()
        messages.success(request, "Product deleted successfully.")
        return redirect("vendor_products")

    return render(request, "vendor/confirm_delete.html", {"product": product})


@login_required
def product_list(request):
    """List vendor's products with pagination"""
    products_queryset = Product.objects.filter(vendor=request.user).order_by('name')  # order by name

    # Pagination: 10 products per page
    paginator = Paginator(products_queryset, 6)
    page_number = request.GET.get('page')
    products = paginator.get_page(page_number)

    return render(request, "vendor/product_list.html", {"products": products})


@login_required
def vendor_products(request):
    """Display vendor's product list"""
    if request.user.user_type != "vendor":
        messages.error(request, "You don't have permission to view this page.")
        return redirect("index")

    products = Product.objects.filter(vendor=request.user)
    return render(request, "vendor/vendor_products.html", {"products": products})


def product_image_upload_path(instance, filename):
    """Generate upload path based on product category"""

    if instance.category:
        category_folder = slugify(instance.category.name).replace('-', '_')
    else:
        category_folder = 'uncategorized'

    name, ext = os.path.splitext(filename)
    unique_filename = f'{slugify(name)}_{uuid.uuid4().hex[:8]}{ext}'

    return f'products/{category_folder}/{unique_filename}'


@login_required
def inventory_view(request):
    """View vendor inventory with stock tracking, low-stock prioritized and summary"""
    # Fetch all products for this vendor, ordered by stock and name
    products_queryset = Product.objects.filter(vendor=request.user).order_by('stock_quantity', 'name')

    total_items_sold = 0  # Initialize total sold counter

    # Attach total sold to each product
    for product in products_queryset:
        product.total_sold = OrderItem.objects.filter(
            product=product, order__status='paid'
        ).aggregate(total=Sum('quantity'))['total'] or 0
        total_items_sold += product.total_sold  # sum for all products

    # Pagination: 10 products per page
    paginator = Paginator(products_queryset, 9)
    page_number = request.GET.get('page')
    products = paginator.get_page(page_number)

    # Low stock products and totals
    low_stock_products = products_queryset.filter(stock_quantity__lt=5)
    total_low_stock = low_stock_products.count()
    total_products = products_queryset.count()

    return render(request, "vendor/inventory.html", {
        "products": products,
        "low_stock_products": low_stock_products,
        "total_products": total_products,
        "total_items_sold": total_items_sold,
        "total_low_stock": total_low_stock,
    })


# SHOPPING CART MANAGEMENT
# Functions for adding, removing, and viewing cart items
class CartViewSet(viewsets.ModelViewSet):
    """API viewset for cart management"""
    queryset = Cart.objects.all()
    serializer_class = CartSerializer

    @action(detail=False, methods=['post'])
    def add(self, request):
        """API endpoint to add item to cart"""
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
        """API endpoint to remove item from cart"""
        user = request.user
        product_id = request.data.get('product_id')

        cart_item = Cart.objects.filter(user=user, product_id=product_id).first()
        if cart_item:
            cart_item.delete()
            return Response({'success': 'Item removed from cart'}, status=status.HTTP_200_OK)
        return Response({'error': 'Item not found in cart'}, status=status.HTTP_404_NOT_FOUND)


def add_to_cart(request, product_id):
    """Add product to cart from product page"""
    if request.method == "POST":
        # ✅ Prevent admin and vendor from adding to cart
        if request.user.is_authenticated and request.user.user_type in ['admin', 'vendor']:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'error': True,
                    'message': 'Admins and vendors cannot purchase products.'
                }, status=403)
            messages.error(request, 'Admins and vendors cannot purchase products.')
            return redirect('index')

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

            # ✅ Calculate total cart count
            cart_count = Cart.objects.filter(user=request.user).count()

            # ✅ If AJAX request, return JSON for snackbar
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    "message": f'"{product.name}" added to cart!',
                    "quantity": cart_item.quantity,
                    "product_id": product.id,
                    "cart_count": cart_count
                })

            # Normal form submission: redirect back
            return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))

        else:
            # Store pending cart in session
            request.session["pending_cart"] = {
                "product_id": product_id,
                "qty": qty
            }

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    "message": "Please log in to add items to your cart.",
                    "error": True
                }, status=401)

            return redirect("login")

    return redirect("index")


def update_cart(request):
    """Update cart quantities or remove items"""
    if request.method == "POST" and request.user.is_authenticated:
        # ✅ Prevent admin and vendor from updating cart
        if request.user.user_type in ['admin', 'vendor']:
            return JsonResponse({
                "error": "Admins and vendors cannot modify cart."
            }, status=403)

        product_id = request.POST.get("product_id")
        quantity = int(request.POST.get("quantity", 0))

        product = get_object_or_404(Product, id=product_id)
        cart_item = Cart.objects.filter(user=request.user, product=product).first()

        if cart_item:
            if quantity > 0:
                cart_item.quantity = quantity
                cart_item.save()
            else:
                cart_item.delete()

        # Return updated cart count
        cart_count = Cart.objects.filter(user=request.user).count()

        return JsonResponse({"cart_count": cart_count})

    return JsonResponse({"error": "Unauthorized"}, status=401)


@login_required
def cart_view(request):
    """Display and manage shopping cart"""
    user = request.user

    # ✅ Redirect admin and vendor away from cart page
    if user.user_type in ['admin', 'vendor']:
        messages.warning(request, 'Admins and vendors cannot access the shopping cart.')
        return redirect('index')

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
                    cart_item.save()
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


@require_POST
@login_required(login_url='/accounts/login/')
def remove_from_cart(request, product_id):
    """Remove specific item from cart"""
    # ✅ Prevent admin and vendor from removing cart items
    if request.user.user_type in ['admin', 'vendor']:
        messages.error(request, 'Admins and vendors cannot modify cart.')
        return redirect('index')

    cart_item = Cart.objects.filter(user=request.user, product_id=product_id).first()
    if cart_item:
        cart_item.delete()
        messages.success(request, "Item removed from your cart.")
    else:
        messages.error(request, "Item not found in your cart.")
    return redirect("cart")

# ORDER MANAGEMENT
# Functions for creating and managing orders

class OrderViewSet(viewsets.ModelViewSet):
    """API viewset for order management"""
    queryset = Order.objects.all()
    serializer_class = OrderSerializer

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def checkout(self, request):
        """API endpoint for checkout process"""
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
    """Handle checkout process with payment options"""
    if request.method != "POST":
        return redirect('cart')

    user = request.user
    delivery_address = request.POST.get('delivery_address')
    payment_method = request.POST.get('payment_method')
    cart_items = Cart.objects.filter(user=user)

    if not cart_items.exists():
        return JsonResponse({'error': 'Cart is empty'}, status=400)

    total = sum(item.product.price * item.quantity for item in cart_items)

    order = Order.objects.create(
        user=user,
        delivery_address=delivery_address,
        total_price=total,
        payment_method=payment_method,
        status='pending'
    )

    for item in cart_items:
        OrderItem.objects.create(
            order=order,
            product=item.product,
            quantity=item.quantity,
            price=item.product.price
        )

    log_activity(
        user=user,
        action="Order Checkout",
        details=f"Order ID: {order.id}, Total: R{order.total_price}"
    )

    cart_items.delete()  # Clear cart for all payment methods

    if payment_method == 'cash':
        # Respond with JSON for JS to handle
        return JsonResponse({
            'success': True,
            'cod': True,
            'message': 'Your order has been placed and will be released once the vendor approves it.',
            'redirect_url': reverse('customer_orders')
        })

    elif payment_method == 'card':
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

        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=line_items,
                mode='payment',
                success_url=request.build_absolute_uri(reverse('success', args=[order.id])),
                cancel_url=request.build_absolute_uri(reverse('cancel', args=[order.id])),
                metadata={'order_id': str(order.id)}
            )

            return JsonResponse({'checkout_url': session.url})

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    else:
        return JsonResponse({'error': 'PayPal payment method NOT active yet!! '}, status=400)



@login_required
def order_confirmation(request, order_id):
    """Display order confirmation page"""
    order = get_object_or_404(Order, id=order_id, user=request.user)
    order_items = OrderItem.objects.filter(order=order)

    return render(request, "order_confirmation.html", {
        "order": order,
        "order_items": order_items,
    })


@login_required
def customer_orders_view(request):
    """View pending customer orders"""
    orders = Order.objects.filter(
        user=request.user, status="pending"
    ).order_by("-created_at")
    return render(request, "customer_orders.html", {"orders": orders})


@login_required
def customer_orders(request):
    """View customer's pending orders"""
    orders = request.user.orders.filter(status="pending").order_by("-created_at")
    return render(request, "customer_orders.html", {"orders": orders})


@vendor_required
def order_history_view(request):
    """View order history for both customers and vendors"""
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
def customer_order_history(request):
    """View customer's order history"""
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


def customer_dashboard(request):
    """Customer dashboard showing all orders"""
    orders = request.user.orders.all() if request.user.is_authenticated else []
    return render(request, "customer_order_history.html", {"orders": orders})


# VENDOR ORDER MANAGEMENT
# Functions for vendors to manage their orders

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
def vendor_orders(request):
    """View vendor's pending orders"""
    if request.user.user_type != "vendor":
        messages.error(request, "Access denied.")
        return redirect("index")

    orders = Order.objects.filter(
        orderitem__product__vendor=request.user,
        status="pending"
    ).distinct().order_by("-created_at")

    return render(request, "vendor/vendor_orders.html", {"orders": orders})


@login_required
def vendor_orders_view(request):
    """View vendor's pending orders with enhanced details"""
    if request.user.user_type != "vendor":
        messages.error(request, "Access denied.")
        return redirect("index")

    orders = get_vendor_orders(request.user, status_list=["pending"])
    return render(request, "vendor/vendor_orders.html", {"orders": orders})


@login_required
def vendor_order_history(request):
    """View vendor's completed and cancelled orders"""
    if request.user.user_type != "vendor":
        messages.error(request, "Access denied.")
        return redirect("index")

    orders = get_vendor_orders(request.user, status_list=["paid", "cancelled"])
    return render(request, "vendor/vendor_order_history.html", {"orders": orders})


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

            # Only update vendor-specific items and log activity
            for item in order.orderitem_set.filter(product__vendor=request.user):
                if new_status == "paid":
                    item.product.stock_quantity -= item.quantity
                    item.product.save()

            # Log activity with correct details
            log_activity(
                user=request.user,
                action="Updated Order",
                details=f"Order #{order.id} marked as {new_status}"
            )

            messages.success(request, f"Order #{order.id} updated to {new_status}.")
        else:
            messages.error(request, "Invalid status update.")

    return redirect("vendor_orders")



@login_required
def mark_order_paid(request, order_id):
    """Mark vendor order as paid and update inventory"""
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


# VENDOR ANALYTICS AND REPORTS
# Functions for sales tracking, reports, and analytics

@login_required
def sales_view(request):
    """Display vendor sales dashboard with analytics"""
    if request.user.user_type != "vendor":
        messages.error(request, "You don't have permission to view this page.")
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
    """Helper function to filter sales by time period"""
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
def sales_dashboard(request):
    """Display vendor sales dashboard with analytics for day/week/month"""
    if request.user.user_type != "vendor":
        messages.error(request, "You don't have permission to view this page.")
        return redirect("index")

    now = timezone.now()
    today = now.date()

    # GET parameter: period = 'day', 'week', or 'month'; default = 'month'
    period = request.GET.get("period", "month")

    # Start date based on period
    if period == "day":
        start_date = today
    elif period == "week":
        start_date = today - timedelta(days=today.weekday())  # Monday
    else:  # month
        start_date = today.replace(day=1)

    # Filter sales
    sales = OrderItem.objects.filter(
        product__vendor=request.user,
        order__created_at__date__gte=start_date
    ).select_related("order", "product")

    # Summary totals
    total_sales = sales.aggregate(total=Sum("subtotal"))["total"] or 0
    total_orders = sales.count()
    avg_sale = sales.aggregate(avg=Sum("subtotal") / Count("id"))["avg"] or 0

    # Previous period for growth (simplified example)
    prev_start_date = start_date - timedelta(days=(today - start_date).days + 1)
    prev_sales = OrderItem.objects.filter(
        product__vendor=request.user,
        order__created_at__date__gte=prev_start_date,
        order__created_at__date__lt=start_date
    ).aggregate(total=Sum("subtotal"))["total"] or 1
    growth_rate = round((total_sales - prev_sales) / prev_sales * 100, 2)

    # Chart: Daily sales within the period
    num_days = (today - start_date).days + 1
    labels = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num_days)]
    daily_sales = sales.values("order__created_at__date").annotate(total=Sum("subtotal"))
    data = [next((x["total"] for x in daily_sales if x["order__created_at__date"] == start_date + timedelta(days=i)), 0) for i in range(num_days)]

    # Charts by category and product
    category_data = sales.values(category_name=F("product__category__name")).annotate(total=Sum("subtotal"))
    category_chart_labels = [c["category_name"] for c in category_data]
    category_chart_data = [{
        "label": "Sales by Category",
        "data": [c["total"] for c in category_data],
        "borderColor": "rgba(75, 192, 192, 1)",
        "backgroundColor": "rgba(75, 192, 192, 0.2)",
        "tension": 0.3,
        "fill": True
    }]

    product_data = sales.values(product_name=F("product__name")).annotate(total=Sum("subtotal"))
    product_chart_labels = [p["product_name"] for p in product_data]
    product_chart_data = [{
        "label": "Sales per Product",
        "data": [p["total"] for p in product_data],
        "backgroundColor": "rgba(54, 162, 235, 0.6)",
        "borderColor": "rgba(54, 162, 235, 1)",
        "borderWidth": 1
    }]

    context = {
        "period": period,
        "total_sales": total_sales,
        "total_orders": total_orders,
        "avg_sale": round(avg_sale, 2),
        "growth_rate": growth_rate,
        "chart_labels": json.dumps(labels),
        "chart_data": json.dumps(data),
        "category_chart_labels": json.dumps(category_chart_labels),
        "category_chart_data": json.dumps(category_chart_data),
        "product_chart_labels": json.dumps(product_chart_labels),
        "product_chart_data": json.dumps(product_chart_data),
    }

    return render(request, "vendor/sales.html", context)


@login_required
def reports_view(request):
    """Generate and display sales reports"""
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
def download_report(request):
    """Download PDF sales report"""
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can download reports.")
        return redirect("index")

    period = request.GET.get("period", "all")
    sales = OrderItem.objects.filter(product__vendor=request.user, order__status = "paid")

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
    """Print-friendly vendor sales report"""
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can print reports.")
        return redirect("index")

    period = request.GET.get("period", "all")
    sales_qs = OrderItem.objects.filter(product__vendor=request.user, order__status="paid")

    now = timezone.now()
    if period == "day":
        sales_qs = sales_qs.filter(order__created_at__gte=now - timedelta(days=1))
    elif period == "week":
        sales_qs = sales_qs.filter(order__created_at__gte=now - timedelta(weeks=1))
    elif period == "month":
        sales_qs = sales_qs.filter(order__created_at__gte=now - timedelta(days=30))

    # Prepare a list of items with calculated total per item
    sales = []
    total_sales = 0
    for item in sales_qs:
        item_total = item.price * item.quantity
        sales.append({
            "order_id": item.order.id,
            "product_name": item.product.name,
            "quantity": item.quantity,
            "unit_price": item.price,
            "total": item_total,
            "date": item.order.created_at,
        })
        total_sales += item_total

    return render(request, "vendor/print_report.html", {
        "sales": sales,
        "total_sales": total_sales,
        "period": period,
    })

# VENDOR SETTINGS AND CONFIGURATION
# Functions for managing vendor-specific settings

@login_required
def settings_view(request):
    """Manage vendor settings and preferences"""
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
def customer_list(request):
    """List customers who have purchased from this vendor"""
    if request.user.user_type != "vendor":
        messages.error(request, "You don't have permission to view this page.")
        return redirect("index")

    customers = CustomUser.objects.filter(
        orders__orderitem__product__vendor=request.user,
        user_type="customer"
    ).distinct()

    # Annotate extra info for template
    customer_data = []
    for customer in customers:
        orders = customer.orders.filter(orderitem__product__vendor=request.user)
        total_orders = orders.count()
        total_spent = orders.aggregate(total=Sum('orderitem__price'))['total'] or 0
        last_order = orders.aggregate(last=Max('created_at'))['last']

        # Add computed fields
        customer.get_full_name = f"{customer.first_name} {customer.last_name}".strip()
        customer.total_orders = total_orders
        customer.total_spent = total_spent
        customer.last_order = last_order

        customer_data.append(customer)

    return render(request, "vendor/customer_list.html", {"customers": customer_data})


# INVOICE AND DOCUMENT GENERATION
# Functions for generating invoices and order documents
@login_required
def invoice_view(request, order_id):
    """Generate and display order invoice"""
    order = get_object_or_404(Order, id=order_id, user=request.user)

    # Display PDF in browser instead of forcing download
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="invoice_{order.id}.pdf"'

    p = canvas.Canvas(response, pagesize=A4)
    width, height = A4

    # Header
    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, height - 50, "Crumb & Co. - Invoice")

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


# CUSTOMER REPORTS GENERATION
@login_required
def download_customer_order_history(request):
    """Download PDF of customer order history"""
    completed_orders = Order.objects.filter(user=request.user, status='paid').order_by("-created_at")
    cancelled_orders = Order.objects.filter(user=request.user, status='cancelled').order_by("-created_at")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()

    # Custom styles
    styles.add(ParagraphStyle(name='CenterTitle', fontSize=18, leading=22, alignment=TA_CENTER, spaceAfter=10))
    styles.add(ParagraphStyle(name='CenterSubTitle', fontSize=12, leading=14, alignment=TA_CENTER, spaceAfter=20))
    styles.add(ParagraphStyle(name='HeadingLeft', fontSize=14, leading=16, alignment=TA_LEFT, spaceAfter=10))

    elements = []

    # path to the logo
    logo_path = finders.find('images/logo.png')

    if logo_path:
        try:
            logo = Image(logo_path, width=80, height=80)
            logo.hAlign = 'CENTER'
            elements.append(logo)
        except Exception as e:
            print("Error loading logo:", e)
    else:
        print("Logo not found by staticfiles finder!")

    # Company name and slogan
    elements.append(Paragraph("<strong>Crumb & Co.</strong>", styles['CenterTitle']))
    elements.append(Paragraph("You Buy, We Serve", styles['CenterSubTitle']))

    # Report title
    elements.append(Paragraph("<strong>Order History Report</strong>", styles['CenterTitle']))
    elements.append(Spacer(1, 12))

    # Customer details table
    customer_data = [
        ["Name:", request.user.get_full_name()],
        ["Email:", request.user.email]
    ]
    if hasattr(request.user, 'profile'):
        if getattr(request.user.profile, 'phone', None):
            customer_data.append(["Phone:", request.user.profile.phone])
        if getattr(request.user.profile, 'address', None):
            customer_data.append(["Address:", request.user.profile.address])

    customer_table = Table(customer_data, colWidths=[100, 350])
    customer_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey)
    ]))
    elements.append(customer_table)
    elements.append(Spacer(1, 20))

    # Function to create order tables
    def create_order_table(orders, title, status_color):
        elements.append(Paragraph(title, styles['HeadingLeft']))
        if orders:
            data = [["Order #", "Date", "Total", "Delivery Address", "Status"]]
            for order in orders:
                data.append([
                    str(order.id),
                    order.created_at.strftime("%Y-%m-%d %H:%M"),
                    f"R{order.total_price:.2f}",
                    order.delivery_address,
                    order.status.title()
                ])
            table = Table(data, repeatRows=1, colWidths=[50, 80, 60, 180, 60])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("TEXTCOLOR", (-1, 1), (-1, -1), status_color),
            ]))
            elements.append(table)
        else:
            elements.append(Paragraph(f"No {title.lower()}.", styles['Normal']))
        elements.append(Spacer(1, 12))

    # Completed Orders (green)
    create_order_table(completed_orders, "Completed Orders", colors.green)

    # Cancelled Orders (red)
    create_order_table(cancelled_orders, "Cancelled Orders", colors.red)

    # Timestamp
    timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")
    elements.append(Spacer(1, 24))
    elements.append(Paragraph(f"Report generated on: {timestamp}", styles['Normal']))

    # Build PDF
    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="order_history.pdf"'
    return response


@login_required
def print_customer_order_history(request):
    """Print-friendly customer order history"""
    customer = request.user
    # Fetch completed and cancelled orders separately
    completed_orders = Order.objects.filter(user=customer, status="paid").order_by("-created_at")
    cancelled_orders = Order.objects.filter(user=customer, status="cancelled").order_by("-created_at")

    return render(request, "print_order_history.html", {
        "completed_orders": completed_orders,
        "cancelled_orders": cancelled_orders,
    })


# PAYMENTS AND STRIPE INTEGRATION
# Functions for handling Stripe payments and webhooks

@csrf_exempt
def create_checkout_session(request):
    """Create Stripe checkout session for cart items"""
    if request.method == "POST":
        # Get the current user's cart
        cart_items = Cart.objects.filter(user=request.user)
        if not cart_items.exists():
            return JsonResponse({'error': 'Cart is empty'}, status=400)

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
        try:
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

            # Return JSON response for frontend to handle
            return JsonResponse({'checkout_url': session.url})

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return redirect("cart")

@login_required
def success(request, order_id):
    """Handle successful payment completion"""
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
    """Handle payment cancellation"""
    order = Order.objects.get(id=order_id, user=request.user)
    order.status = "cancelled"
    order.save()

    order_items = order.orderitem_set.all()

    return render(request, "cancel.html", {"order": order, "order_items": order_items})


@csrf_exempt
def stripe_webhook(request):
    """Handle Stripe webhook events"""
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
    """Handle Stripe payment success callback"""
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


@admin_required
def activity_log_view(request):
    if request.user.user_type != "admin":
        messages.error(request, "Access denied.")
        return redirect("index")

    # Fetch last 100 logs, with related user to avoid extra queries
    logs = ActivityLog.objects.select_related('user', 'user__profile').order_by('-timestamp')[:100]

    return render(request, "admins/activity_logs.html", {"logs": logs})


def handle_paypal_payment(request, order):
    """
    PayPal payment handler - Currently not implemented
    Returns error message prompting user to select alternative payment
    """
    log_activity(
        user=order.user,
        action="PayPal Attempted",
        details=f"User tried PayPal for Order #{order.id} (not yet active)"
    )

    return JsonResponse({
        'error': 'PayPal payment method is not active yet. Please use Card or Cash on Delivery.',
        'alternative_methods': ['card', 'cash']
    }, status=400)


# Admin Dashboard
@admin_required
def admin_dashboard(request):
    total_products = Product.objects.count()
    total_vendors = CustomUser.objects.filter(user_type="vendor").count()
    total_customers = CustomUser.objects.filter(user_type="customer").count()

    context = {
        "total_products": total_products,
        "total_vendors": total_vendors,
        "total_customers": total_customers,
    }
    return render(request, "admins/admin_dashboard.html", context)


# Admin Profile: View all products
@admin_required
def admin_all_products(request):
    products = Product.objects.select_related("vendor", "category").all()
    return render(request, "admins/admin_all_products.html", {"products": products})


# Admin: Manage Vendors
@admin_required
def admin_vendors(request):
    vendors = CustomUser.objects.filter(user_type="vendor")
    return render(request, "admins/admin_vendors.html", {"vendors": vendors})


# Admin: Manage Customers
@admin_required
def admin_customers(request):
    customers = CustomUser.objects.filter(user_type="customer")
    return render(request, "admins/admin_customers.html", {"customers": customers})


# Admin: Categories
@admin_required
def admin_categories(request):
    admin_categories = Category.objects.all()
    return render(request, "admins/admin_categories.html", {"categories": admin_categories})


def admin_required(view_func):
    return user_passes_test(lambda u: u.is_authenticated and u.user_type == "admin")(view_func)


@admin_required
def admin_all_orders(request):
    return render(request, "admins/admin_all_orders.html")


@admin_required
def admin_analytics(request):
    # Example context — you can add real analytics later
    context = {
        "total_products": 100,
        "total_orders": 50,
        "total_customers": 25,
    }
    return render(request, "admins/admin_analytics.html", context)


@admin_required
def admin_reports(request):
    # Replace with actual report logic later
    context = {}
    return render(request, "admins/admin_reports.html", context)


@admin_required
def admin_settings(request):
    # Replace with real settings logic later
    context = {}
    return render(request, "admins/admin_settings.html", context)


# View Vendor Details
@admin_required
def admin_vendor_detail(request, id):
    vendor = get_object_or_404(CustomUser, id=id, user_type="vendor")
    return render(request, "admins/admin_vendor_detail.html", {"vendor": vendor})


# Edit Vendor
@admin_required
def admin_vendor_edit(request, id):
    vendor = get_object_or_404(CustomUser, id=id, user_type="vendor")
    if request.method == "POST":
        form = VendorForm(request.POST, instance=vendor)
        if form.is_valid():
            form.save()
            messages.success(request, f"Vendor {vendor.username} updated successfully.")
            return redirect("admin_vendors")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = VendorForm(instance=vendor)
    return render(request, "admins/admin_vendor_edit.html", {"form": form, "vendor": vendor})



# Delete Vendor
@admin_required
def admin_vendor_delete(request, id):
    vendor = get_object_or_404(CustomUser, id=id, user_type="vendor")
    if request.method == "POST":
        vendor.delete()
        messages.success(request, f"Vendor {vendor.username} deleted successfully.")
        return redirect("admin_vendors")
    return render(request, "admins/admin_vendor_delete_confirm.html", {"vendor": vendor})


# Admin: Customer detail
@admin_required
def admin_customer_detail(request, id):
    customer = CustomUser.objects.get(id=id, user_type="customer")
    return render(request, "admins/admin_customer_detail.html", {"customer": customer})


# Admin: Edit customer
@admin_required
def admin_customer_edit(request, id):
    customer = CustomUser.objects.get(id=id, user_type="customer")
    if request.method == "POST":
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, "Customer updated successfully.")
            return redirect("admin_customers")
    else:
        form = CustomerForm(instance=customer)
    return render(request, "admins/admin_customer_edit.html", {"form": form, "customer": customer})


# Admin: Delete customer
@admin_required
def admin_customer_delete(request, id):
    customer = CustomUser.objects.get(id=id, user_type="customer")
    if request.method == "POST":
        customer.delete()
        messages.success(request, "Customer deleted successfully.")
        return redirect("admin_customers")
    return render(request, "admins/admin_customer_delete.html", {"customer": customer})


# List categories



# Add new category
@admin_required
def admin_category_add(request):
    if request.method == "POST":
        form = CategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Category added successfully")
            return redirect("admin_categories")
    else:
        form = CategoryForm()
    return render(request, "admins/admin_category_form.html", {"form": form, "title": "Add Category"})


# Edit category
@admin_required
def admin_category_edit(request, id):
    category = get_object_or_404(Category, id=id)
    if request.method == "POST":
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, "Category updated successfully")
            return redirect("admin_categories")
    else:
        form = CategoryForm(instance=category)
    return render(request, "admins/admin_category_form.html", {"form": form, "title": "Edit Category"})


# Delete category
@admin_required
def admin_category_delete(request, id):
    category = get_object_or_404(Category, id=id)
    category.delete()
    messages.success(request, "Category deleted successfully")
    return redirect("admin_categories")
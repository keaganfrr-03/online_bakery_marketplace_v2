from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from web_app.models import Category, Product, Cart, Order, OrderItem

User = get_user_model()


class Command(BaseCommand):
    help = "Seeds the database with sample users, categories, products, carts, and orders."

    def handle(self, *args, **kwargs):
        self.stdout.write("🌱 Seeding database...")

        # === USERS ===
        admin_user, _ = User.objects.get_or_create(
            username="admin_user",
            defaults={
                "email": "admin@example.com",
                "user_type": "vendor",  # admin acting as vendor for now
                "is_staff": True,
                "is_superuser": True,
            },
        )
        admin_user.set_password("adminpass")
        admin_user.save()

        vendor_user, _ = User.objects.get_or_create(
            username="vendor_user",
            defaults={"email": "vendor@example.com", "user_type": "vendor"},
        )
        vendor_user.set_password("vendorpass")
        vendor_user.save()

        customer_user, _ = User.objects.get_or_create(
            username="customer_user",
            defaults={"email": "customer@example.com", "user_type": "customer"},
        )
        customer_user.set_password("customerpass")
        customer_user.save()

        # === CATEGORIES ===
        categories = ["Cakes", "Breads", "Pastries", "Cookies", "Donuts", "Muffins"]
        category_objs = {}
        for name in categories:
            obj, _ = Category.objects.get_or_create(name=name)
            category_objs[name] = obj

        # === PRODUCTS (5 per category with images) ===
        products_data = [
            # Cakes
            ("Chocolate Cake", "Rich chocolate cake", "Cakes", 15.99, 10, "products/cakes/cake1.jpg"),
            ("Vanilla Cake", "Classic vanilla cake", "Cakes", 12.99, 8, "products/cakes/cake2.jpg"),
            ("Red Velvet Cake", "Smooth red velvet cake", "Cakes", 16.50, 5, "products/cakes/cake3.jpg"),
            ("Lemon Cake", "Tangy lemon cake", "Cakes", 14.99, 7, "products/cakes/cake4.jpg"),
            ("Carrot Cake", "Moist carrot cake with cream cheese frosting", "Cakes", 13.99, 6, "products/cakes/cake5.jpg"),

            # Breads
            ("Banana Bread", "Moist banana bread", "Breads", 6.99, 20, "products/breads/bread1.jpg"),
            ("Sourdough Bread", "Artisan sourdough", "Breads", 5.99, 15, "products/breads/bread2.jpg"),
            ("Whole Wheat Bread", "Healthy whole wheat bread", "Breads", 4.99, 18, "products/breads/bread3.jpg"),
            ("Rye Bread", "Classic rye bread", "Breads", 5.50, 12, "products/breads/bread4.jpg"),
            ("Baguette", "French baguette", "Breads", 3.99, 25, "products/breads/bread5.jpg"),

            # Pastries
            ("Croissant", "Buttery croissant", "Pastries", 3.99, 25, "products/pastries/pastry1.jpg"),
            ("Danish Pastry", "Fruit-filled danish", "Pastries", 4.50, 18, "products/pastries/pastry2.jpg"),
            ("Apple Turnover", "Crispy apple turnover", "Pastries", 3.75, 20, "products/pastries/pastry3.jpg"),
            ("Cheese Danish", "Soft cheese-filled pastry", "Pastries", 4.00, 15, "products/pastries/pastry4.jpg"),
            ("Éclair", "Chocolate-covered éclair", "Pastries", 4.25, 10, "products/pastries/pastry5.jpg"),

            # Cookies
            ("Chocolate Chip Cookie", "Loaded with chocolate chips", "Cookies", 1.99, 50, "products/cookies/cookie1.jpg"),
            ("Oatmeal Cookie", "Healthy oatmeal cookie", "Cookies", 1.50, 40, "products/cookies/cookie2.jpg"),
            ("Peanut Butter Cookie", "Rich peanut butter flavor", "Cookies", 1.75, 35, "products/cookies/cookie3.jpg"),
            ("Sugar Cookie", "Classic sweet cookie", "Cookies", 1.25, 45, "products/cookies/cookie4.jpg"),
            ("Double Chocolate Cookie", "Extra chocolatey goodness", "Cookies", 2.25, 30, "products/cookies/cookie5.jpg"),

            # Donuts
            ("Glazed Donut", "Sweet glazed donut", "Donuts", 1.25, 30, "products/donuts/donut1.jpg"),
            ("Chocolate Donut", "Chocolate-covered donut", "Donuts", 1.50, 25, "products/donuts/donut2.jpg"),
            ("Strawberry Donut", "Fruity strawberry donut", "Donuts", 1.40, 20, "products/donuts/donut3.jpg"),
            ("Boston Cream Donut", "Filled with cream", "Donuts", 1.60, 18, "products/donuts/donut4.jpg"),
            ("Cinnamon Donut", "Coated with cinnamon sugar", "Donuts", 1.35, 22, "products/donuts/donut5.jpg"),

            # Muffins
            ("Blueberry Muffin", "Soft muffin with fresh blueberries", "Muffins", 2.50, 20,
             "products/muffins/muffin1.jpg"),
            ("Chocolate Chip Muffin", "Muffin loaded with chocolate chips", "Muffins", 2.75, 18,
             "products/muffins/muffin2.jpg"),
            ("Banana Nut Muffin", "Banana muffin with crunchy nuts", "Muffins", 2.60, 15,
             "products/muffins/muffin3.jpg"),
            ("Lemon Poppyseed Muffin", "Tangy lemon muffin with poppy seeds", "Muffins", 2.80, 12,
             "products/muffins/muffin4.jpg"),
            ("Cranberry Orange Muffin", "Sweet and tart cranberry orange muffin", "Muffins", 2.70, 10,
             "products/muffins/muffin5.jpg"),
        ]

        product_objs = {}
        for name, desc, cat_name, price, stock, image in products_data:
            prod, _ = Product.objects.get_or_create(
                name=name,
                vendor=vendor_user,
                category=category_objs[cat_name],
                defaults={
                    "description": desc,
                    "price": price,
                    "stock_quantity": stock,
                    "availability": True,
                    "image": image,
                },
            )
            product_objs[name] = prod

        # === CART ===
        Cart.objects.get_or_create(user=customer_user, product=product_objs["Chocolate Cake"], defaults={"quantity": 2})
        Cart.objects.get_or_create(user=customer_user, product=product_objs["Glazed Donut"], defaults={"quantity": 4})

        # === ORDERS ===
        order1, _ = Order.objects.get_or_create(
            user=customer_user,
            defaults={
                "total_price": 45.00,
                "delivery_address": "123 Customer Lane",
                "created_at": timezone.now(),
            },
        )
        OrderItem.objects.get_or_create(order=order1, product=product_objs["Chocolate Cake"], defaults={"quantity": 2, "price": 15.99})
        OrderItem.objects.get_or_create(order=order1, product=product_objs["Glazed Donut"], defaults={"quantity": 4, "price": 1.25})

        self.stdout.write(self.style.SUCCESS("✅ Database seeded successfully with 25 products and images!"))

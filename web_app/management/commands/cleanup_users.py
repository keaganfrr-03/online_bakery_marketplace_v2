from django.core.management.base import BaseCommand
from web_app.models import Product, Order, CustomUser
from django.db import transaction


class Command(BaseCommand):
    help = "Reassign all products to vendor1 and all orders to customer1, then delete other users."

    def handle(self, *args, **kwargs):
        try:
            with transaction.atomic():
                # Get main vendor and main customer
                vendor1 = CustomUser.objects.filter(user_type="vendor").first()
                customer1 = CustomUser.objects.filter(user_type="customer").first()

                if not vendor1:
                    self.stdout.write(self.style.ERROR("❌ No vendor found (user_type='vendor')."))
                    return

                if not customer1:
                    self.stdout.write(self.style.ERROR("❌ No customer found (user_type='customer')."))
                    return

                # Reassign all products
                Product.objects.all().update(vendor=vendor1)
                self.stdout.write(self.style.SUCCESS("✅ All products reassigned to Vendor1."))

                # Reassign all orders
                Order.objects.all().update(user=customer1)
                self.stdout.write(self.style.SUCCESS("✅ All orders reassigned to Customer1."))

                # Delete other vendors & customers
                CustomUser.objects.filter(user_type="vendor").exclude(id=vendor1.id).delete()
                CustomUser.objects.filter(user_type="customer").exclude(id=customer1.id).delete()
                self.stdout.write(self.style.SUCCESS("🧹 Removed other vendors and customers."))

                self.stdout.write(self.style.SUCCESS("🎉 Cleanup completed successfully."))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"⚠️ Error: {str(e)}"))

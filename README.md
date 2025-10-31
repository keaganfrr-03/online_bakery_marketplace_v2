This is a virtual marketplace, where vendors and customers buy and sell bakery products conveniently. The app runs on Django, with external MySQL DB

Setup
1. Clone the repo git clone: git clone https://github.com/eddiecns/online_bakery_market.git 
2. and then run: cd online_bakery_market
3. Create a branch and switch to it: git checkout -b my_version
4. Create virtual environment: python -m venv .venv
5. Activate the venv source: .\.venv\Scripts\activate
6. Install dependencies: pip install -r requirements.txt
7. Copy the config file: cp .env.example .env
8. Edit .env and update your local settings: with MYSQl DB username, password and the Django secret key
9. To reveal the Django secret key type: python manage.py shell and then: 
from decouple import config
print(config("SECRET_KEY"))
10. Make migrations: python manage.py makemigrations
11. Run the migrations: python manage.py migrate
12. Create local admin user: python manage.py createsuperuser
13. Start the app server: python manage.py runserver
14. Enter admin name, password  and email
15. Register for a demo account on https://dashboard.stripe.com/
16. Open Developers--> API keys --> copy and paste into the .env file the Publishable key and Secret key

Main app page will be accessed in browser on http://localhost:8000
Django/system dashboard is accessed on http://localhost:8000/admin
To expose the API endpoints documentation visit http://localhost:8000/swagger
You can also test the API using the Postman collection included in the repository.

Features

User account creation, login, and logout
Staff users can create, view, edit, and delete products and ingredients
Users can create orders with any number of products/ingredients
Users can view their own orders

Card number: 4242 4242 4242 4242
Expiration date: any future date (e.g., 12/34)
CVC: any 3 digits (e.g., 123)
ZIP: any 5 digits (e.g., 12345)

| Card Type        | Number              | Notes                           |
| ---------------- | ------------------- |---------------------------------|
| Visa             | 4242 4242 4242 4242 | Always succeeds                 |
| Visa             | 4000 0000 0000 9995 | Always fails(insufficient funds |
| Mastercard       | 5555 5555 5555 4444 | Always succeeds                 |
| American Express | 3782 822463 10005   | Always succeeds                 |


| Group                         | Function Name                     | Description                                            |
| ----------------------------- | --------------------------------- | ------------------------------------------------------ |
| **BASIC PAGES**               | `index`                           | Show homepage with categories.                         |
|                               | `category_detail`                 | Show products in a specific category.                  |
| **USERS**                     | `UserViewSet.register`            | API endpoint to register a new user.                   |
|                               | `ProfileViewSet`                  | API endpoint for profile CRUD.                         |
| **PRODUCTS**                  | `CategoryViewSet`                 | API endpoint for category CRUD.                        |
|                               | `ProductViewSet`                  | API endpoint for product CRUD.                         |
| **CART**                      | `CartViewSet.add`                 | API endpoint to add items to cart.                     |
|                               | `CartViewSet.remove`              | API endpoint to remove items from cart.                |
|                               | `add_to_cart`                     | Add product to cart via POST request.                  |
|                               | `cart_view`                       | View cart, update quantities, delete items.            |
|                               | `remove_from_cart`                | Remove item from cart via POST.                        |
| **ORDERS**                    | `OrderViewSet.checkout`           | API endpoint to checkout cart and create order.        |
|                               | `checkout_view`                   | Handle order creation and payment methods (cash/card). |
|                               | `order_confirmation`              | Display order confirmation page.                       |
|                               | `customer_orders`                 | View current customer orders.                          |
|                               | `customer_order_history`          | View customer completed and cancelled orders.          |
|                               | `update_order_status`             | Vendor updates status of their orders.                 |
|                               | `mark_order_paid`                 | Vendor marks an order as paid.                         |
|                               | `get_vendor_orders`               | Helper to get vendor-specific orders.                  |
|                               | `vendor_orders_view`              | View vendor pending orders.                            |
|                               | `vendor_order_history`            | View vendor paid and cancelled orders.                 |
| **REGISTER & LOGIN**          | `RegisterForm`                    | User registration form.                                |
|                               | `register_view`                   | Handle registration via form.                          |
|                               | `CustomLoginView.form_valid`      | Add pending cart items after login.                    |
|                               | `CustomLoginView.get_success_url` | Redirect users after login.                            |
| **VENDOR PRODUCT MANAGEMENT** | `vendor_dash`                     | Vendor dashboard with products.                        |
|                               | `add_product`                     | Add a new product.                                     |
|                               | `edit_product`                    | Edit existing product.                                 |
|                               | `delete_product`                  | Delete a product.                                      |
|                               | `product_list`                    | List vendor products.                                  |
|                               | `vendor_products`                 | Vendor products management page.                       |
|                               | `inventory_view`                  | View inventory list.                                   |
| **PROFILE MANAGEMENT**        | `profile_view`                    | View and update profile for customer/vendor.           |
|                               | `profile_edit`                    | Edit profile information.                              |
|                               | `vendor_edit_profile`             | Vendor-specific profile edit.                          |
| **REPORTS & INVOICES**        | `reports_view`                    | View vendor sales reports.                             |
|                               | `invoice_view`                    | Generate PDF invoice for order.                        |
|                               | `download_report`                 | Download sales report as PDF.                          |
|                               | `print_report`                    | Render printable report view.                          |
| **PAYMENTS & STRIPE**         | `create_checkout_session`         | Create Stripe checkout session.                        |
|                               | `stripe_success`                  | Handle Stripe payment success.                         |
|                               | `stripe_webhook`                  | Stripe webhook for checkout completion.                |


Reach out to me at eddie@ecns.co.za for any queries.


This is a virtual marketplace, where vendors and customers buy and sell bakery products conveniently. The app runs on Django, with external MySQL DB

Setup
1. Clone the repo git clone: git clone https://github.com/eddiecns/online_bakery_market.git 
2. and then run: cd online_bakery_market
3. Create a branch and switch to it: git checkout -b my_version
4. Create virtual environment: python3 -m venv venv
5. Activate the venv source: venv/bin/activate
6. Install dependencies: pip install -r requirements.txt
7. Copy the config file: .env.example .env
8. Edit .env and update your local settings: with MYSQl DB username, password and the Django secret key
9. To reveal the Django secret key type: python manage.py shell and then: 
from decouple import config
print(config("SECRET_KEY"))
10. Make migrations: python manage.py makemigrations
11. Run the migrations: python manage.py migrate
12. Create local admin user: python manage.py createsuperuser
13. Start the app server: python manage.py runserver
14. Enter admin name, password  and email

Main app page will be accessed in browser on http://localhost:8000
Django/system dashboard is accessed on http://localhost:8000/admin
To expose the API endpoints documentation visit http://localhost:8000/swagger
You can also test the API using the Postman collection included in the repository.

Features

User account creation, login, and logout
Staff users can create, view, edit, and delete products and ingredients
Users can create orders with any number of products/ingredients
Users can view their own orders

Reach out to me at eddie@ecns.co.za for any queries.

Card number: 4242 4242 4242 4242

Expiration date: any future date (e.g., 12/34)

CVC: any 3 digits (e.g., 123)

ZIP: any 5 digits (e.g., 12345)

| Card Type        | Number              | Notes           |
| ---------------- | ------------------- | --------------- |
| Visa             | 4242 4242 4242 4242 | Always succeeds |
| Visa             | 4000 0000 0000 9995 | Always fails    |
| Mastercard       | 5555 5555 5555 4444 | Always succeeds |
| American Express | 3782 822463 10005   | Always succeeds |


# Online Bakery Marketplace (v2)

A virtual marketplace where vendors and customers can conveniently buy and sell bakery products. The app runs on Django with an external MySQL database.

## Setup

1. Clone the repository:
   `git clone https://github.com/keaganfrr-03/online_bakery_marketplace_v2`
2. Enter the project folder: `cd online_bakery_marketplace_v2`
3. Create and activate a branch: `git checkout -b my_version`
4. Create a virtual environment: `python -m venv .venv`
5. Activate it on Windows: `.\.venv\Scripts\activate`
6. Install dependencies: `pip install -r requirements.txt`
7. Copy the config file: `cp .env.example .env`
8. Edit `.env` with your local MySQL username and password, and a Django secret key.
9. Make migrations: `python manage.py makemigrations`
10. Run migrations: `python manage.py migrate`
11. Create a local admin user: `python manage.py createsuperuser`
12. Seed demo users and products: `python manage.py seed_db` or `python manage.py seed_db --force`
13. Start the app server: `python manage.py runserver`
14. Enter the admin name, password, and email.
15. Register for a demo account at https://dashboard.stripe.com/
16. Open **Developers → API keys** and copy the Publishable key and Secret key into `.env`.

## Local URLs

- Main app: http://localhost:8000
- Django/system dashboard: http://localhost:8000/admin
- API documentation: http://localhost:8000/swagger
- API testing: use the Postman collection included in the repository.

## Demo Users

| Role | Username | Password | Notes |
| --- | --- | --- | --- |
| Django admin | `admin` | `admin` | |
| System Admin | `eddie` | `adminpass` | |
| Vendor | `vendor1` | `vendorpass` | VendorID: ISK254 |
| Vendor | `vendor2` | `vendorpass` | VendorID: LFE037 |
| Customer | `customer1` | `customerpass` | |

## Stripe Online Transactions

Use Stripe's demo card details below for online transactions:

- Card number: `4242 4242 4242 4242`
- Expiration date: any future date (for example, `12/34`)
- CVC: any 3 digits (for example, `123`)

| Card Type | Number | Notes |
| --- | --- | --- |
| Visa | 4242 4242 4242 4242 | Always succeeds |
| Visa | 4000 0000 0000 9995 | Always fails (insufficient funds) |
| Mastercard | 5555 5555 5555 4444 | Always succeeds |
| American Express | 3782 822463 10005 | Always succeeds |

## Vendor ID Management

Assign IDs to vendors who do not have one:

```bash
python manage.py assign_vendor_ids
```

Regenerate IDs for all vendors, including vendors who already have one:

```bash
python manage.py assign_vendor_ids --all
```

Assign an ID to one user:

```bash
python manage.py assign_vendor_ids --username john_vendor
```

## Contact

Reach out to me at keaganschutte16@gmail.com for any queries.

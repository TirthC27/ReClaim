import os, asyncio
os.environ["PYTHONIOENCODING"] = "utf-8"
from app.services.webhooks import process_checkout_create

payload = {
    "id": 9999999999,
    "token": "hWNGGW7L2WolzwLJNbQveIGA",
    "email": "test@example.com",
    "line_items": [
        {
            "product_id": 1122334455,
            "title": "Test Product",
            "price": "100.00",
            "quantity": 1
        }
    ]
}
print("Simulating checkout_create...")
res = process_checkout_create(payload)
print("Result:", res)

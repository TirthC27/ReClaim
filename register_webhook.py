import os, requests
os.environ["PYTHONIOENCODING"] = "utf-8"
from app.services.shopify_auth import get_shopify_access_token
from app.config import settings

token = get_shopify_access_token()
url = settings.SHOPIFY_STORE_URL + "/admin/api/2024-10/webhooks.json"
headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

payload = {
    "webhook": {
        "topic": "carts/update",
        "address": "https://autograph-alright-brewing.ngrok-free.dev/webhooks/shopify/cart-update",
        "format": "json"
    }
}

print("Registering carts/update webhook...")
r = requests.post(url, headers=headers, json=payload)
print(r.status_code, r.text)

print("\nCurrent Webhooks:")
r2 = requests.get(url, headers=headers)
for wh in r2.json().get("webhooks", []):
    print(f"  {wh['topic']} -> {wh['address']}")

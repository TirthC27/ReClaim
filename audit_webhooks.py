"""Step 6: Webhook audit using OAuth token."""
import os, json
os.environ["PYTHONIOENCODING"] = "utf-8"

import requests
from app.services.shopify_auth import get_shopify_access_token
from app.config import settings

token = get_shopify_access_token()
url = settings.SHOPIFY_STORE_URL + "/admin/api/2024-10/webhooks.json"
resp = requests.get(url, headers={"X-Shopify-Access-Token": token}, timeout=15)
print("Status:", resp.status_code)

data = resp.json()
webhooks = data.get("webhooks", [])
print("Total webhooks:", len(webhooks))
print()

# Group by topic
by_topic = {}
for wh in webhooks:
    topic = wh.get("topic", "unknown")
    if topic not in by_topic:
        by_topic[topic] = []
    by_topic[topic].append(wh)

for topic, whs in by_topic.items():
    dup_flag = " *** DUPLICATE ***" if len(whs) > 1 else ""
    print(f"Topic: {topic} (count: {len(whs)}){dup_flag}")
    for wh in whs:
        wid = wh.get("id")
        addr = wh.get("address", "")
        created = wh.get("created_at", "")
        print(f"  id={wid}  address={addr}  created={created}")
    print()

# Summary
checkout_count = len(by_topic.get("checkouts/create", []))
orders_count = len(by_topic.get("orders/create", []))
print("=" * 60)
print(f"checkouts/create count: {checkout_count}")
print(f"orders/create count: {orders_count}")

if checkout_count > 1:
    print("ACTION NEEDED: Delete duplicate checkouts/create webhooks")
    dupes = by_topic["checkouts/create"][1:]  # keep first
    for d in dupes:
        print(f"  DELETE webhook id={d['id']}")

if orders_count > 1:
    print("ACTION NEEDED: Delete duplicate orders/create webhooks")
    dupes = by_topic["orders/create"][1:]
    for d in dupes:
        print(f"  DELETE webhook id={d['id']}")

# Check for stale URLs (not current ngrok)
print()
print("Checking for stale webhook URLs...")
for wh in webhooks:
    addr = wh.get("address", "")
    topic = wh.get("topic", "")
    if "ngrok" in addr or "localhost" in addr:
        print(f"  {topic}: {addr} (ngrok/localhost)")
    else:
        print(f"  {topic}: {addr}")

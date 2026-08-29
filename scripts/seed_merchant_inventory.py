"""
Seed script — patch demo merchants with realistic inventory data.

Run once:  python scripts/seed_merchant_inventory.py

This gives each merchant a distinct inventory profile so the LLM
Strategy Agent produces different offer strategies:
  - DigiWorld  → high accessory stock, moderate warranty → leans toward bundles
  - ElectroStore → lower accessories, cheaper warranty → leans toward warranty/discount

Requires:
  - Backend server running at http://localhost:8000
  - Both merchants already onboarded (adjust UUIDs below to match your DB)

Usage:
  1. First, find your merchant UUIDs:
       curl http://localhost:8000/merchants | python -m json.tool
  2. Update the `merchants` list below with the correct UUIDs.
  3. Run:  python scripts/seed_merchant_inventory.py
"""

import sys
import requests

API_BASE = "http://localhost:8000"


# ┌─────────────────────────────────────────────────────────────────┐
# │  UPDATE THESE UUIDs to match your actual merchants in Supabase │
# └─────────────────────────────────────────────────────────────────┘
merchants = [
    {
        "id": "0f808b77-6384-443d-ab37-38105e9121a6",  # DigiWorld
        "name": "DigiWorld",
        "stock_data": {
            "available_qty": 25,
            "restock_lead_days": 7,
            "overstock_skus": ["LAPTOP-BAG-BLK", "USB-HUB-4P"],
        },
        "accessory_inventory": {
            "wireless_mouse": 15,
            "laptop_bag": 10,
            "usb_hub": 20,
            "screen_protector": 30,
            "phone_case": 25,
        },
        "warranty_cost_data": {
            "1yr_extended_cost_inr": 499,
            "2yr_extended_cost_inr": 899,
            "accidental_damage_cost_inr": 1299,
        },
    },
    {
        "id": "05498455-666c-414b-8a2d-43f263269580",  # ElectroStore
        "name": "ElectroStore",
        "stock_data": {
            "available_qty": 12,
            "restock_lead_days": 14,
            "overstock_skus": [],
        },
        "accessory_inventory": {
            "laptop_sleeve": 8,
            "fast_charger": 30,
            "usb_cable": 50,
        },
        "warranty_cost_data": {
            "1yr_extended_cost_inr": 349,
            "2yr_extended_cost_inr": 649,
            "accidental_damage_cost_inr": 999,
        },
    },
]


def main():
    print("Seeding merchant inventory data...")
    print(f"API Base: {API_BASE}\n")

    # First, fetch current merchants to validate UUIDs
    try:
        resp = requests.get(f"{API_BASE}/merchants", timeout=10)
        resp.raise_for_status()
        existing = resp.json()
        existing_ids = {m["id"] for m in existing}
        print(f"Found {len(existing)} merchants in DB:")
        for m in existing:
            print(f"  • {m['id']} — {m['name']}")
        print()
    except Exception as exc:
        print(f"⚠️  Could not fetch merchants: {exc}")
        print("Make sure the server is running at", API_BASE)
        sys.exit(1)

    for m in merchants:
        mid = m["id"]
        name = m["name"]

        if mid not in existing_ids:
            print(f"⚠️  Merchant {name} ({mid}) NOT FOUND in DB — skipping.")
            print(f"   Update the UUID in this script to match your DB.")
            continue

        payload = {
            "stock_data": m["stock_data"],
            "accessory_inventory": m["accessory_inventory"],
            "warranty_cost_data": m["warranty_cost_data"],
        }

        try:
            resp = requests.patch(
                f"{API_BASE}/merchants/{mid}",
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            result = resp.json()
            print(f"✅ {name} ({mid})")
            print(f"   stock_data:          {result.get('stock_data')}")
            print(f"   accessory_inventory: {result.get('accessory_inventory')}")
            print(f"   warranty_cost_data:  {result.get('warranty_cost_data')}")
            print()
        except Exception as exc:
            print(f"❌ {name} ({mid}): {exc}")

    print("Done.")


if __name__ == "__main__":
    main()

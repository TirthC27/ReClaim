import uuid
from app.db.client import get_supabase

sb = get_supabase()

merchants = [
    {"name": "DigiWorld", "shopify_vendor_name": "DigiWorld"},
    {"name": "ElectroStore", "shopify_vendor_name": "ElectroStore"},
    {"name": "LaptopHub", "shopify_vendor_name": "LaptopHub"},
    {"name": "SmartBuy", "shopify_vendor_name": "SmartBuy"},
    {"name": "TechMart", "shopify_vendor_name": "TechMart"}
]

for m in merchants:
    m["id"] = str(uuid.uuid4())
    m["is_active"] = True

sb.table("merchants").insert(merchants).execute()
print("Merchants created.")

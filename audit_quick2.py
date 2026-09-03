import os; os.environ["PYTHONIOENCODING"] = "utf-8"
from app.db.client import get_supabase
sb = get_supabase()

try:
    result = sb.table("cart_recoveries").select("id, shopify_draft_order_id").limit(1).execute()
    print("shopify_draft_order_id column already exists!")
except Exception as e:
    print(f"shopify_draft_order_id column does NOT exist yet: {e}")
    # We can't run ALTER TABLE directly through supabase python client if it's restricted, but let's try via postgres connection string if available, or just instruct the user.

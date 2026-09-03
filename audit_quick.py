"""Apply cart_token column migration via Supabase REST API."""
import os; os.environ["PYTHONIOENCODING"] = "utf-8"
from app.db.client import get_supabase
sb = get_supabase()

# Test if cart_token column already exists by querying with it
try:
    result = sb.table("carts").select("id, cart_token").limit(1).execute()
    print("cart_token column already exists!")
    print(result.data)
except Exception as e:
    print(f"cart_token column does NOT exist yet: {e}")
    print("You need to run this SQL in Supabase Dashboard > SQL Editor:")
    print("  ALTER TABLE carts ADD COLUMN IF NOT EXISTS cart_token TEXT;")
    print("  CREATE INDEX IF NOT EXISTS idx_carts_cart_token ON carts(cart_token);")

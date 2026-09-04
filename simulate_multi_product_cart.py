import asyncio
import os
import sys

# Setup python path to import app modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.client import get_supabase
from datetime import datetime, timedelta, timezone

async def run():
    sb = get_supabase()
    
    print("Creating synthetic multi-product cart...")
    # 1. Create a synthetic cart
    import uuid
    uid = str(uuid.uuid4())[:8]
    cart_res = sb.table("carts").insert({
        "shopify_checkout_id": f"test_multi_cart_{uid}",
        "customer_email": f"demo.multi.{uid}@example.com",
        "status": "active",
        "created_at": (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat() # Force abandonment
    }).execute()
    cart_id = cart_res.data[0]["id"]
    print(f"Cart created: {cart_id}")
    # 2. Get two different product groups and two products
    pg_res = sb.table("product_groups").select("id").limit(2).execute()
    p_res = sb.table("products").select("id").limit(2).execute()
    
    if len(pg_res.data) < 2 or len(p_res.data) < 2:
        print("Need at least 2 product groups and 2 products in the DB")
        return
        
    pg1 = pg_res.data[0]["id"]
    pg2 = pg_res.data[1]["id"]
    p1 = p_res.data[0]["id"]
    p2 = p_res.data[1]["id"]
    
    # 3. Create demand signals for these groups
    sb.table("demand_signals").insert([
        {
            "cart_id": cart_id,
            "product_id": p1,
            "product_group_id": pg1,
            "quantity": 1,
            "status": "pending"
        },
        {
            "cart_id": cart_id,
            "product_id": p2,
            "product_group_id": pg2,
            "quantity": 1,
            "status": "pending"
        }
    ]).execute()
    
    print(f"Added signals for groups: {pg1}, {pg2}")
    
    print("Running abandonment worker to process this cart...")
    from app.services.abandonment_worker import check_abandoned_carts
    check_abandoned_carts()
    
    print("Checking if multi-product pool was created...")
    mp_res = sb.table("multi_product_pools").select("*").order("created_at", desc=True).limit(1).execute()
    if mp_res.data:
        pool = mp_res.data[0]
        print(f"SUCCESS: Multi-product pool created! ID: {pool['id']}, Signature: {pool['basket_signature']}")
        print(f"Total carts in pool: {pool['cart_count']}")
    else:
        print("FAILED: No multi-product pool found.")

if __name__ == "__main__":
    asyncio.run(run())

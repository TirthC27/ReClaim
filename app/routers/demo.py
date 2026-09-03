import uuid
from fastapi import APIRouter
from pydantic import BaseModel
from app.db.client import get_supabase
from app.services.aggregation import aggregate_demand_for_group
from datetime import datetime, timedelta, timezone
from app.config import settings

router = APIRouter(tags=["demo"])

class SimulateBulkDemandReq(BaseModel):
    product_id: str
    customer_count: int

@router.post("/demo/simulate-bulk-demand")
def simulate_bulk_demand(req: SimulateBulkDemandReq):
    sb = get_supabase()
    
    # 1. Fetch product to get product_group_id
    prod_resp = sb.table("products").select("product_group_id").eq("id", req.product_id).execute()
    if not prod_resp.data:
        return {"error": "Product not found"}
        
    pg_id = prod_resp.data[0].get("product_group_id")
    
    # FIX: If the product isn't part of a group yet, create a dummy group and link it 
    # to a merchant so the demo aggregation actually works without crashing.
    if not pg_id:
        # Create a new product group
        pg_res = sb.table("product_groups").insert({
            "model_name": f"Demo Group {req.product_id[:8]}",
            "canonical_sku": f"demo-sku-{req.product_id[:8]}"
        }).execute()
        pg_id = pg_res.data[0]["id"]
        
        # Link the product to this new group
        sb.table("products").update({"product_group_id": pg_id}).eq("id", req.product_id).execute()
        
        # Link to all active merchants so Section 9A selection finds everyone to bid
        existing_mappings = sb.table("merchant_products").select("id").eq(
            "product_group_id", pg_id
        ).execute().data
        
        if not existing_mappings:
            merchant_res = sb.table("merchants").select("id").eq("is_active", True).execute()
            for merchant in merchant_res.data:
                sb.table("merchant_products").insert({
                    "merchant_id": merchant["id"],
                    "shopify_product_id": f"demo_shp_{req.product_id[:8]}",
                    "product_group_id": pg_id
                }).execute()
    
    carts_to_insert = []
    signals_to_insert = []
    
    # Store IDs for cart_recoveries
    cart_to_signal_map = {}
    
    for _ in range(req.customer_count):
        cart_id = str(uuid.uuid4())
        email = f"demo.{uuid.uuid4().hex[:8]}@example.com"
        carts_to_insert.append({
            "id": cart_id,
            "shopify_checkout_id": f"demo_chk_{uuid.uuid4().hex}",
            "customer_email": email,
            "status": "abandoned"
        })
        sig_id = str(uuid.uuid4())
        signals_to_insert.append({
            "id": sig_id,
            "cart_id": cart_id,
            "product_id": req.product_id,
            "product_group_id": pg_id,
            "quantity": 1,
            "status": "abandoned",
        })
        cart_to_signal_map[cart_id] = (sig_id, email)
        
    if carts_to_insert:
        sb.table("carts").insert(carts_to_insert).execute()
    if signals_to_insert:
        sb.table("demand_signals").insert(signals_to_insert).execute()
        
    # Insert cart_recoveries just like abandonment_worker
    recoveries_to_insert = []
    for cart_id, (sig_id, email) in cart_to_signal_map.items():
        recoveries_to_insert.append({
            "cart_id": cart_id,
            "customer_email": email,
            "status": "awaiting_offers",
            "expires_at": (datetime.now(timezone.utc) + timedelta(
                hours=settings.POOL_WINDOW_HOURS
            )).isoformat(),
        })
        
    if recoveries_to_insert:
        rec_result = sb.table("cart_recoveries").insert(recoveries_to_insert).execute().data
        if rec_result:
            recovery_items = []
            # We assume order of insertion matches the order of data returned by Supabase
            for rec, cart_id in zip(rec_result, cart_to_signal_map.keys()):
                recovery_items.append({
                    "cart_recovery_id": rec["id"],
                    "demand_signal_id": cart_to_signal_map[cart_id][0]
                })
            if recovery_items:
                sb.table("cart_recovery_items").insert(recovery_items).execute()
                
    # Aggregate demand so it shows up in pools immediately
    aggregate_demand_for_group(pg_id)
        
    return {"created_signals": len(signals_to_insert)}

@router.delete("/demo/cleanup-bulk-demand")
def cleanup_bulk_demand():
    sb = get_supabase()
    # Resolve the synthetic carts first so every dependent row can be removed
    # explicitly. Relying on the cart cascade is not sufficient because older
    # installations have non-cascading foreign keys on recovery items.
    demo_carts = sb.table("carts").select("id").like(
        "customer_email", "demo.%"
    ).execute().data or []
    cart_ids = [row["id"] for row in demo_carts]
    if not cart_ids:
        return {"deleted_count": 0}

    demo_signals = sb.table("demand_signals").select("id").in_(
        "cart_id", cart_ids
    ).execute().data or []
    signal_ids = [row["id"] for row in demo_signals]

    if signal_ids:
        # Remove rows whose FK may block demand-signal deletion.
        sb.table("order_allocations").delete().in_(
            "demand_signal_id", signal_ids
        ).execute()
        sb.table("cart_recovery_items").delete().in_(
            "demand_signal_id", signal_ids
        ).execute()
        # The deployed orders_demand_signal_id_fkey is non-cascading on some
        # installations, so remove synthetic orders before their signals.
        sb.table("orders").delete().in_(
            "demand_signal_id", signal_ids
        ).execute()

    # Delete by cart_id, not recovery email, so records remain removable even
    # if a recovery's email was edited after the demo data was created.
    sb.table("cart_recoveries").delete().in_("cart_id", cart_ids).execute()

    if signal_ids:
        sb.table("demand_signals").delete().in_("id", signal_ids).execute()

    result = sb.table("carts").delete().in_("id", cart_ids).execute()
    return {"deleted_count": len(result.data or [])}

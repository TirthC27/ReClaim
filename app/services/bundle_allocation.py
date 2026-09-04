"""
Bundle Allocation

Executes the buyer agent's per-customer allocation plan.
Handles creation of Shopify draft orders (single vs split) and unified Razorpay links.
"""

import logging
import uuid
from app.db.client import get_supabase

logger = logging.getLogger(__name__)
sb = get_supabase()


def allocate_bundle_orders(pool_id: str, allocation_plan: list[dict]) -> dict:
    """
    Execute the buyer agent's per-customer allocation plan.
    
    For each customer cart:
    1. Update cart_recovery_items with bundle_offer_id, merchant_id, price
    2. Compute total_price for cart_recovery
    3. Trigger split/single checkout logic
    """
    from app.services.allocation import send_finalized_offer_email
    
    if not allocation_plan:
        return {"error": "No allocation plan provided"}
        
    for cart in allocation_plan:
        cart_id = cart["cart_id"]
        assignments = cart["assignments"]
        total_price = cart.get("total_price", 0)
        
        # 1. Update cart_recovery
        # Find the cart_recovery for this cart
        recovery = (
            sb.table("cart_recoveries")
            .select("id")
            .eq("cart_id", cart_id)
            .execute()
            .data
        )
        if not recovery:
            logger.error(f"No cart_recovery found for cart {cart_id}")
            continue
            
        recovery_id = recovery[0]["id"]
        
        # 2. Update recovery items
        for item in assignments:
            gid = item["product_group_id"]
            
            # Find the recovery item corresponding to this product_group_id
            # via demand_signals
            signal = (
                sb.table("demand_signals")
                .select("id")
                .eq("cart_id", cart_id)
                .eq("product_group_id", gid)
                .execute()
                .data
            )
            
            if not signal:
                logger.warning(f"No demand signal for cart {cart_id}, gid {gid}")
                continue
                
            sig_id = signal[0]["id"]
            
            sb.table("cart_recovery_items").update({
                "bundle_offer_id": item.get("bundle_offer_id"),
                "merchant_id": item["merchant_id"],
                "price": item["price"]
            }).eq("cart_recovery_id", recovery_id).eq("demand_signal_id", sig_id).execute()
            
        # 3. Update cart_recovery total
        sb.table("cart_recoveries").update({
            "total_price": total_price,
            "status": "ready"
        }).eq("id", recovery_id).execute()
        
        # 4. Create Draft Orders and Email
        # We reuse the existing send_finalized_offer_email which already handles
        # mixed carts and generates a single draft order + payment link, implicitly handling splits.
        try:
            send_finalized_offer_email(recovery_id)
        except Exception as e:
            logger.error(f"Failed to create recovery checkout for cart {cart_id}: {e}")
                
    return {"status": "success", "carts_processed": len(allocation_plan)}

"""
Bundle Allocation — v3 (Agents Decide, Backend Computes)

Executes the Buyer Agent's validated allocation plan.
Uses backend-computed quantities, unit_prices, and line_totals
from the validated plan — never from LLM output.

Pipeline:
    Validated Plan (from AllocationBuilder + Validator in bundle_buyer_agent.py)
        ↓
    Update cart_recovery_items with merchant, bundle_offer_id, price, quantity
        ↓
    Compute total_price from validated line_totals
        ↓
    Create Draft Order + Razorpay payment link

Source of truth for prices:
    - unit_price comes from bundle_offers (computed by Backend Offer Calculator
      in bundle_offer_engine.py from Seller Agent's discount decision + Shopify base price)
    - line_total = unit_price × cart_quantity (computed by AllocationBuilder)
    - total_price = sum(line_totals) - bundle_discount (computed by AllocationBuilder)
"""

import logging
from app.db.client import get_supabase

logger = logging.getLogger(__name__)
sb = get_supabase()


def allocate_bundle_orders(pool_id: str, allocation_plan: list[dict]) -> dict:
    """
    Execute the buyer agent's validated per-customer allocation plan.

    For each customer cart:
    1. Update cart_recovery_items with bundle_offer_id, merchant_id, price (line_total)
    2. Set total_price from backend-validated allocation (NOT from LLM)
    3. Trigger Shopify draft order + Razorpay payment link
    """
    from app.services.allocation import send_finalized_offer_email

    if not allocation_plan:
        return {"error": "No allocation plan provided"}

    processed = 0
    failed = 0

    for cart in allocation_plan:
        cart_id = cart["cart_id"]
        assignments = cart["assignments"]
        # Use the backend-computed total (from AllocationBuilder), not LLM
        total_price = cart.get("total_price", 0)

        # 1. Find cart_recovery for this cart
        recovery = (
            sb.table("cart_recoveries")
            .select("id")
            .eq("cart_id", cart_id)
            .execute()
            .data
        )
        if not recovery:
            logger.error(f"No cart_recovery found for cart {cart_id}")
            failed += 1
            continue

        recovery_id = recovery[0]["id"]

        # 2. Extract selected bundle offers to mark them as 'selected'
        selected_offer_ids = {item.get("bundle_offer_id") for item in assignments if item.get("bundle_offer_id")}
        for offer_id in selected_offer_ids:
            sb.table("bundle_offers").update({
                "status": "selected"
            }).eq("id", offer_id).execute()

        # 3. Update each recovery item with validated assignment data
        for item in assignments:
            gid = item["product_group_id"]
            line_total = item.get("line_total", 0)
            bundle_offer_id = item.get("bundle_offer_id")

            # Find demand signal for this cart + product_group
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

            # Update cart_recovery_items with backend-computed values
            # Link to the merchant's actual bundle_offer_id chosen by the agent
            update_data = {
                "merchant_id": item["merchant_id"],
                "price": line_total,
            }
            if bundle_offer_id:
                update_data["bundle_offer_id"] = bundle_offer_id

            sb.table("cart_recovery_items").update(update_data).eq("cart_recovery_id", recovery_id).eq("demand_signal_id", sig_id).execute()

        # 4. Update cart_recovery with backend-computed total
        sb.table("cart_recoveries").update({
            "total_price": total_price,
            "status": "ready"
        }).eq("id", recovery_id).execute()

        # 5. Create Draft Order + Payment Link
        try:
            send_finalized_offer_email(recovery_id)
            processed += 1
        except Exception as e:
            logger.error(f"Failed to create recovery checkout for cart {cart_id}: {e}")
            failed += 1

    return {
        "status": "success",
        "carts_processed": processed,
        "carts_failed": failed,
        "total_carts": len(allocation_plan),
    }

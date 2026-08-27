"""
Section 9A.2 — Round-robin fairness allocation.

After validated offers exist for a demand pool, this module determines
whether merchants are tied on value_score and, if so, distributes
individual customer orders (demand signals) across tied merchants
using a deterministic round-robin rotation.

Key tunable constant:
    TIE_TOLERANCE_PCT — defines "genuinely comparable" as within ±N% of
    the top score. Set in .env or defaults to 3.0%.
"""

import logging
from app.config import settings
from app.db.client import get_supabase

logger = logging.getLogger(__name__)

# ┌─────────────────────────────────────────────────────────────────┐
# │  TUNABLE CONSTANT — adjust based on how close demo merchants'  │
# │  economics are, so you can reliably trigger the round-robin    │
# │  path during judging.                                          │
# └─────────────────────────────────────────────────────────────────┘
TIE_TOLERANCE_PCT = getattr(settings, "TIE_TOLERANCE_PCT", 3.0)


def run_allocation(pool_id: str) -> dict:
    """
    Run 9A.2 allocation for a demand pool.

    1. Fetch all validated offers for the pool
    2. Check for ties within TIE_TOLERANCE_PCT of top score
    3. If tie → round-robin; if clear winner → assign all to winner
    4. Insert order_allocations rows
    """
    sb = get_supabase()

    # ── Fetch validated offers ───────────────────────────────
    offers = (
        sb.table("offers")
        .select("id, merchant_id, value_score, price, offer_type")
        .eq("demand_pool_id", pool_id)
        .eq("status", "validated")
        .order("value_score", desc=True)
        .execute()
        .data
    )

    if not offers:
        return {"pool_id": pool_id, "status": "no_validated_offers", "allocations": []}

    # ── Fetch demand signals for this pool ───────────────────
    pool = sb.table("demand_pools").select("product_group_id, rotation_order").eq("id", pool_id).execute().data
    if not pool:
        return {"pool_id": pool_id, "status": "pool_not_found", "allocations": []}
    pool = pool[0]

    signals = (
        sb.table("demand_signals")
        .select("id, quantity, merchant_id")
        .eq("product_group_id", pool["product_group_id"])
        .in_("status", ["pooled", "abandoned"])
        .order("created_at")
        .execute()
        .data
    )

    if not signals:
        return {"pool_id": pool_id, "status": "no_signals", "allocations": []}

    # ── Determine tied merchants ─────────────────────────────
    top_score = float(offers[0].get("value_score", 0) or 0)
    tolerance = top_score * (TIE_TOLERANCE_PCT / 100.0)

    tied_offers = [
        o for o in offers
        if abs(float(o.get("value_score", 0) or 0) - top_score) <= tolerance
    ]

    allocations = []

    if len(tied_offers) <= 1:
        # ── Clear winner — assign all to top merchant ────────
        winner = offers[0]
        for signal in signals:
            alloc = {
                "demand_pool_id": pool_id,
                "demand_signal_id": signal["id"],
                "merchant_id": winner["merchant_id"],
                "rotation_position": 0,
            }
            result = sb.table("order_allocations").insert(alloc).execute().data[0]
            allocations.append(result)

        # Mark the winning offer as selected
        sb.table("offers").update({"status": "selected"}).eq("id", winner["id"]).execute()

        return {
            "pool_id": pool_id,
            "status": "clear_winner",
            "winner_merchant_id": winner["merchant_id"],
            "allocations_count": len(allocations),
            "allocations": allocations,
        }

    # ── Tie detected — round-robin rotation ──────────────────
    tied_merchant_ids = [o["merchant_id"] for o in tied_offers]

    # Build or reuse rotation order
    rotation_order = pool.get("rotation_order")
    if not rotation_order:
        # Initialize rotation: use tied merchant IDs in their current order
        rotation_order = tied_merchant_ids
        sb.table("demand_pools").update({
            "rotation_order": rotation_order,
        }).eq("id", pool_id).execute()

    # Track remaining capacity per merchant (in-memory)
    # For MVP, assume each merchant can handle all signals
    capacity = {mid: 9999 for mid in rotation_order}

    # Fetch actual stock hints if available
    for mid in rotation_order:
        merchant_rows = sb.table("merchants").select("stock_data").eq("id", mid).execute().data
        if merchant_rows and merchant_rows[0].get("stock_data"):
            stock = merchant_rows[0]["stock_data"]
            if isinstance(stock, dict) and "available_qty" in stock:
                capacity[mid] = int(stock["available_qty"])

    rotation_idx = 0

    for signal in signals:
        qty_remaining = int(signal.get("quantity", 1))

        while qty_remaining > 0:
            # Find next merchant with capacity
            attempts = 0
            while attempts < len(rotation_order):
                current_merchant = rotation_order[rotation_idx % len(rotation_order)]
                if capacity.get(current_merchant, 0) > 0:
                    break
                rotation_idx += 1
                attempts += 1

            if attempts >= len(rotation_order):
                # All merchants exhausted capacity
                logger.warning(f"All merchants exhausted for pool {pool_id}")
                break

            current_merchant = rotation_order[rotation_idx % len(rotation_order)]
            assign_qty = min(qty_remaining, capacity.get(current_merchant, 0))

            alloc = {
                "demand_pool_id": pool_id,
                "demand_signal_id": signal["id"],
                "merchant_id": current_merchant,
                "rotation_position": rotation_idx,
            }
            result = sb.table("order_allocations").insert(alloc).execute().data[0]
            allocations.append(result)

            capacity[current_merchant] -= assign_qty
            qty_remaining -= assign_qty
            rotation_idx += 1

    # Mark all tied offers as selected
    for o in tied_offers:
        sb.table("offers").update({"status": "selected"}).eq("id", o["id"]).execute()

    return {
        "pool_id": pool_id,
        "status": "round_robin",
        "tied_merchants": tied_merchant_ids,
        "rotation_order": rotation_order,
        "allocations_count": len(allocations),
        "allocations": allocations,
    }

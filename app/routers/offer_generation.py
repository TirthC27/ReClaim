"""
Offer generation + allocation router.

POST /demand-pools/{id}/generate-offers  — trigger the offer engine
GET  /demand-pools/{id}/allocations      — view 9A.2 allocation results
"""

import asyncio
from uuid import UUID
from fastapi import APIRouter, HTTPException

from app.services.offer_engine import run_offer_generation
from app.services.allocation import allocate_orders_for_pool
from app.services import demand as demand_svc

router = APIRouter(tags=["offer-generation"])


@router.post("/demand-pools/{pool_id}/generate-offers")
async def generate_offers(pool_id: UUID):
    """
    Trigger the full offer generation pipeline for a demand pool.

    Runs each selected merchant's 2-LLM-call pipeline concurrently,
    validates offers, then runs 9A.2 allocation if multiple offers exist.
    """
    pool = demand_svc.get_demand_pool(pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail="Demand pool not found")

    if not pool.get("selected_merchant_ids"):
        raise HTTPException(
            status_code=400,
            detail="No merchants selected for this pool. Run aggregation first.",
        )

    # Run the offer engine
    result = await run_offer_generation(str(pool_id))

    # If we have validated offers, run allocation
    if result.get("offers_generated", 0) > 0:
        try:
            allocation_result = allocate_orders_for_pool(
                pool_id=str(pool_id),
                product_id=pool["product_group_id"],
                total_demand_qty=pool.get("signal_count", 0)
            )
            result["buyer_agent"] = allocation_result
        except Exception as exc:
            result["allocation_error"] = str(exc)

    return result


@router.get("/demand-pools/{pool_id}/allocations")
def get_allocations(pool_id: UUID):
    """
    View the 9A.2 round-robin allocation results for a pool.

    Shows which merchant each individual customer order was assigned to,
    including rotation position for demo transparency.
    """
    pool = demand_svc.get_demand_pool(pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail="Demand pool not found")

    from app.db.client import get_supabase
    sb = get_supabase()

    allocations = (
        sb.table("order_allocations")
        .select("*, merchants(id, name, shopify_vendor_name)")
        .eq("demand_pool_id", str(pool_id))
        .order("rotation_position")
        .execute()
        .data
    )

    return {
        "pool_id": str(pool_id),
        "rotation_order": pool.get("rotation_order"),
        "total_allocations": len(allocations),
        "allocations": allocations,
    }

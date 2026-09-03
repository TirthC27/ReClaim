"""
Offer generation + allocation router.

POST /demand-pools/{id}/generate-offers  — trigger the offer engine
GET  /demand-pools/{id}/allocations      — view 9A.2 allocation results
"""

import asyncio
import logging
from uuid import UUID
from fastapi import APIRouter, HTTPException

from app.services.offer_engine import run_offer_generation
from app.services.allocation import allocate_orders_for_pool
from app.services.aggregation import is_pool_eligible_for_agents, pool_eligibility_message
from app.services import demand as demand_svc
from app.db.client import get_supabase

router = APIRouter(tags=["offer-generation"])
logger = logging.getLogger(__name__)


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
    if not is_pool_eligible_for_agents(pool):
        raise HTTPException(status_code=409, detail=pool_eligibility_message(pool))

    sb = get_supabase()

    # STEP 0 — Supersede every prior round's offers for this pool before generating new ones
    sb.table("offers").update({"status": "expired"}).eq(
        "demand_pool_id", str(pool_id)
    ).in_("status", ["validated", "candidate", "selected", "rejected"]).execute()

    # STEP 0b — Clear stale allocations tied to the now-expired offers
    sb.table("order_allocations").delete().eq("demand_pool_id", str(pool_id)).execute()

    # Run the offer engine
    result = await run_offer_generation(str(pool_id))

    # If we have validated offers, run allocation
    if result.get("offers_generated", 0) > 0:
        try:
            representative_signal = sb.table("demand_signals").select(
                "product_id"
            ).eq("product_group_id", pool["product_group_id"]).limit(1).execute().data
            if not representative_signal:
                raise HTTPException(status_code=500, detail=f"No demand_signals found for product_group_id {pool['product_group_id']}")
                
            allocation_result = allocate_orders_for_pool(
                pool_id=str(pool_id),
                product_id=representative_signal[0]["product_id"],
                total_demand_qty=pool.get("signal_count", 0)
            )
            result["buyer_agent"] = allocation_result
            if not allocation_result.get("allocation_plan"):
                logger.error(
                    "[generate-offers] Allocation produced no assignments for pool %s; "
                    "buyer-agent result=%s",
                    pool_id,
                    allocation_result,
                )
        except Exception as exc:
            logger.error(
                "[generate-offers] Allocation failed for pool %s: %s",
                pool_id,
                exc,
                exc_info=True,
            )
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


@router.post("/demand-pools/{pool_id}/negotiate")
async def negotiate(pool_id: UUID):
    """
    Run multi-round negotiation, validate final offers, and allocate.
    """
    from app.services.negotiation_engine import run_negotiation
    pool = demand_svc.get_demand_pool(pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail="Demand pool not found")
    if not is_pool_eligible_for_agents(pool):
        raise HTTPException(status_code=409, detail=pool_eligibility_message(pool))
    
    result = await run_negotiation(str(pool_id))
    
    # If we have validated offers, run allocation
    if result.get("status") in ("converged", "max_rounds_reached") and len(result.get("offers", [])) > 0:
        try:
            pool = demand_svc.get_demand_pool(pool_id)
            sb = get_supabase()
            representative_signal = sb.table("demand_signals").select(
                "product_id"
            ).eq("product_group_id", pool["product_group_id"]).limit(1).execute().data
            if not representative_signal:
                raise HTTPException(status_code=500, detail=f"No demand_signals found for product_group_id {pool['product_group_id']}")
                
            allocation_result = allocate_orders_for_pool(
                pool_id=str(pool_id),
                product_id=representative_signal[0]["product_id"],
                total_demand_qty=pool.get("signal_count", 0)
            )
            result["buyer_agent"] = allocation_result
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"[negotiate] Allocation failed for pool {pool_id}: {exc}", exc_info=True)
            result["allocation_error"] = str(exc)

    return result


@router.get("/demand-pools/{pool_id}/negotiation-rounds")
def get_negotiation_rounds(pool_id: UUID):
    """
    Fetch the live feed of negotiation rounds for a pool.
    """
    from app.db.client import get_supabase
    sb = get_supabase()
    
    rounds = sb.table("offer_negotiation_rounds").select("*, merchants(name)").eq(
        "demand_pool_id", str(pool_id)
    ).order("round_number").order("created_at").execute().data
    
    return {"pool_id": str(pool_id), "rounds": rounds}

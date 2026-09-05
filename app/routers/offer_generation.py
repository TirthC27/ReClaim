"""
Offer generation + allocation router.

POST /demand-pools/{id}/generate-offers  — trigger the offer engine
GET  /demand-pools/{id}/allocations      — view 9A.2 allocation results
"""

import asyncio
import logging
from uuid import UUID
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse

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


@router.post("/multi-product-pools/{pool_id}/generate-offers")
async def generate_multi_product_offers(pool_id: UUID):
    """
    Trigger the bundle offer generation pipeline for a multi-product pool.
    Runs the 3-step bundle engine for selected merchants, then calls the
    buyer agent to create the optimal split/single allocation.
    """
    from app.services.bundle_offer_engine import run_bundle_offer_generation
    from app.services.bundle_buyer_agent import run_bundle_buyer_agent
    from app.services.bundle_allocation import allocate_bundle_orders
    
    # 1. Run generation
    generation_result = await run_bundle_offer_generation(str(pool_id))
    
    if generation_result.get("error"):
        raise HTTPException(status_code=400, detail=generation_result["error"])
        
    if generation_result.get("validated_offers", 0) > 0:
        try:
            # 2. Run Buyer Agent (LLM decides → backend computes → validator gates)
            buyer_result = run_bundle_buyer_agent(str(pool_id))
            generation_result["buyer_agent"] = buyer_result
            
            # 3. Execute Allocation ONLY if validator passed
            allocation_plan = buyer_result.get("allocation_plan", [])
            validation_passed = buyer_result.get("validation_passed", False)
            
            if allocation_plan and validation_passed:
                alloc_result = allocate_bundle_orders(str(pool_id), allocation_plan)
                generation_result["allocation"] = alloc_result
            elif allocation_plan and not validation_passed:
                logger.error(
                    f"[generate-multi-offers] Buyer agent plan REJECTED by validator "
                    f"for pool {pool_id}. Errors: {buyer_result.get('validation_errors', [])}"
                )
                generation_result["allocation_error"] = (
                    f"Validator rejected the allocation plan: "
                    f"{buyer_result.get('validation_errors', [])}"
                )
            else:
                logger.warning(f"No allocation plan generated for multi-product pool {pool_id}")
                
        except Exception as exc:
            logger.error(f"Bundle allocation failed for pool {pool_id}: {exc}", exc_info=True)
            generation_result["allocation_error"] = str(exc)
            
@router.post("/multi-product-pools/{pool_id}/negotiate")
async def negotiate_multi_product_pool(pool_id: UUID, background_tasks: BackgroundTasks):
    """
    Triggers the real-time 2-round negotiation.
    Runs asynchronously in the background. The dashboard will connect to /stream.
    """
    from app.services.bundle_negotiation_engine import run_bundle_negotiation
    
    # Run negotiation in background so the request returns immediately and frontend can connect to stream
    background_tasks.add_task(run_bundle_negotiation, str(pool_id))
    
    return {"status": "started", "message": "Negotiation started in background"}


@router.get("/multi-product-pools/{pool_id}/negotiation/stream")
async def stream_negotiation(pool_id: UUID, request: Request):
    """
    SSE endpoint for live negotiation dashboard.
    """
    from app.services.bundle_negotiation_engine import sse_generator
    return StreamingResponse(sse_generator(request, str(pool_id)), media_type="text/event-stream")


@router.get("/multi-product-pools/{pool_id}/negotiation-rounds")
def get_multi_product_negotiation_rounds(pool_id: UUID):
    """
    Fetch the live feed of negotiation rounds for a pool (polling fallback/initial load).
    """
    from app.db.client import get_supabase
    sb = get_supabase()
    
    rounds = sb.table("bundle_negotiation_rounds").select("*").eq(
        "multi_product_pool_id", str(pool_id)
    ).order("round_number").order("created_at").execute().data
    
    pool = sb.table("multi_product_pools").select("negotiation_status, total_rounds").eq("id", str(pool_id)).single().execute().data
    
    return {
        "pool_id": str(pool_id), 
        "status": pool.get("negotiation_status") if pool else "unknown",
        "rounds": rounds
    }


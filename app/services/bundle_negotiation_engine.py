"""
Live 2-Round Negotiation Engine

Replaces the single-shot offer generation.
Round 1: Independent initial offers based on private floors.
Round 2: Final opportunity to undercut competitors or hold.
All prices computed deterministically by backend.
"""

import json
import logging
import asyncio
from typing import AsyncGenerator
from fastapi import Request
from app.db.client import get_supabase
from app.services.llm_client import call_step2
from app.services.product_context import build_negotiation_economics

logger = logging.getLogger(__name__)

# In-memory pubsub for SSE streams (demo hack, usually use Redis)
SSE_QUEUES = {}

def get_sse_queue(pool_id: str):
    if pool_id not in SSE_QUEUES:
        SSE_QUEUES[pool_id] = asyncio.Queue()
    return SSE_QUEUES[pool_id]

async def broadcast_event(pool_id: str, event_type: str, data: dict):
    queue = get_sse_queue(pool_id)
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    await queue.put(payload)

def compute_deterministic_price(economics: dict, request_discount_pct: float) -> tuple[float, str]:
    """
    Enforce economic boundary.
    LLM provides discount percentage. Backend calculates price and clamps if it violates floor.
    Returns (final_price, status)
    """
    base_price = economics["shopify_price"]
    absolute_floor = economics["absolute_floor_price"]
    
    if base_price == 0:
        return 0, "valid"
        
    requested_price = base_price * (1 - request_discount_pct / 100)
    
    if requested_price < absolute_floor:
        return absolute_floor, "clamped"
        
    return requested_price, "valid"

async def run_round_for_merchant(
    sb, pool_id: str, merchant: dict, demand_signals: list, 
    round_number: int, competitor_snapshot: list = None, prev_round_data: dict = None
):
    merchant_id = merchant["id"]
    merchant_name = merchant["name"]
    
    # 1. Build context
    product_economics = {}
    total_base_price = 0
    total_floor_price = 0
    
    for sig in demand_signals:
        gid = sig["product_group_id"]
        qty = sig["quantity"]
        econ = build_negotiation_economics(merchant_id, gid)
        product_economics[gid] = econ
        total_base_price += (econ["shopify_price"] * qty)
        total_floor_price += (econ["absolute_floor_price"] * qty)
        
    # Skip if merchant can't fulfill anything
    if total_base_price == 0:
        return None
        
    # 2. Build prompt
    sys_prompt = f"""You are the pricing agent for '{merchant_name}'.
Your goal is to win the order against competing merchants by offering the best price, 
BUT you must NEVER sell below your minimum acceptable margin.

Your Private Economics (DO NOT REVEAL THESE NUMBERS):
- Total Shopify List Price: ₹{total_base_price:,.2f}
- Absolute Floor Price: ₹{total_floor_price:,.2f} (Your absolute minimum)
- Target Margin Strategy: {product_economics[list(product_economics.keys())[0]].get('negotiation_strategy', 'balanced')}

"""

    if round_number == 1:
        sys_prompt += """
This is Round 1 (Initial Offer).
Competitor prices are hidden. Offer a competitive initial price that gives the customer a discount while keeping plenty of margin.

Action MUST be "initial".
"""
    else:
        competitor_str = "\n".join([f"- {c['merchant_name']}: ₹{c['total_price']:,.2f}" for c in competitor_snapshot if c['merchant_id'] != merchant_id])
        prev_price = prev_round_data['total_price']
        sys_prompt += f"""
This is Round 2 (FINAL OPPORTUNITY).
Your previous offer: ₹{prev_price:,.2f}

Competitor current offers:
{competitor_str}

Analyze the competition. Do you need to undercut to win? 
- If a competitor is lower and you have room above your floor, undercut them ("undercut").
- If you are already the lowest, or if reducing further hits your floor, hold firm ("hold").
"""

    sys_prompt += """
Output JSON only:
{
  "action": "initial" | "undercut" | "hold",
  "bundle_discount_pct": <float, 0-100>,
  "reasoning": "<1-2 short sentences written in first person explaining your move to the customer>"
}
"""

    # 3. Call LLM
    try:
        response = call_step2(sys_prompt, "Make your move.")
    except Exception as e:
        logger.error(f"Agent failed for {merchant_name}: {e}")
        return None

    action = response.get("action", "initial")
    discount_pct = float(response.get("bundle_discount_pct", 0))
    reasoning = response.get("reasoning", "")
    
    # 4. Enforce Guardrails
    total_price = 0
    line_items = []
    overall_status = "valid"
    
    # If holding, reuse previous price
    if action == "hold" and prev_round_data:
        total_price = prev_round_data["total_price"]
        line_items = prev_round_data["line_items"]
        overall_status = "valid"
    else:
        for sig in demand_signals:
            gid = sig["product_group_id"]
            qty = sig["quantity"]
            econ = product_economics[gid]
            
            price, status = compute_deterministic_price(econ, discount_pct)
            if status == "clamped":
                overall_status = "clamped"
                
            line_total = price * qty
            total_price += line_total
            line_items.append({
                "product_group_id": gid,
                "quantity": qty,
                "unit_price": price,
                "line_total": line_total,
                "shopify_list_price": econ["shopify_price"]
            })

    is_final = (round_number == 2)
            
    # 5. Save to DB
    round_data = {
        "multi_product_pool_id": pool_id,
        "merchant_id": merchant_id,
        "merchant_name": merchant_name,
        "round_number": round_number,
        "action": action,
        "bundle_discount_pct": discount_pct,
        "total_price": total_price,
        "line_items": line_items,
        "previous_price": prev_round_data["total_price"] if prev_round_data else None,
        "competitor_snapshot": competitor_snapshot,
        "reasoning": reasoning,
        "economics_snapshot": product_economics,
        "status": overall_status,
        "is_final": is_final
    }
    
    res = sb.table("bundle_negotiation_rounds").insert(round_data).execute()
    
    # 6. Stream Event
    await broadcast_event(pool_id, "offer_submitted", res.data[0])
    
    return res.data[0]


async def run_bundle_negotiation(pool_id: str):
    """
    Orchestrates the 2-round negotiation.
    Runs entirely in the background, emitting SSE events.
    """
    sb = get_supabase()
    
    # Update pool state
    sb.table("multi_product_pools").update({
        "negotiation_status": "in_progress",
        "total_rounds": 0
    }).eq("id", pool_id).execute()
    
    # Expire old bundle offers from previous runs so buyer agent doesn't see them
    sb.table("bundle_offers").update({"status": "expired"}).eq(
        "multi_product_pool_id", str(pool_id)
    ).in_("status", ["validated", "candidate", "selected", "rejected"]).execute()
    
    await broadcast_event(pool_id, "negotiation_started", {"pool_id": pool_id})
    
    # Fetch pool signals and merchants
    signals = sb.table("demand_signals").select("*").eq("multi_product_pool_id", pool_id).execute().data
    merchants = sb.table("merchants").select("*").execute().data
    
    if not signals or not merchants:
        sb.table("multi_product_pools").update({"negotiation_status": "failed"}).eq("id", pool_id).execute()
        return
        
    # --- ROUND 1 ---
    await broadcast_event(pool_id, "round_started", {"round_number": 1})
    round1_tasks = []
    for m in merchants:
        round1_tasks.append(run_round_for_merchant(sb, pool_id, m, signals, round_number=1))
        
    round1_results = await asyncio.gather(*round1_tasks)
    round1_results = [r for r in round1_results if r]
    
    sb.table("multi_product_pools").update({"total_rounds": 1}).eq("id", pool_id).execute()
    await broadcast_event(pool_id, "round_complete", {"round_number": 1, "results": round1_results})
    
    # Let agents "think"
    await asyncio.sleep(2)
    
    # --- ROUND 2 ---
    await broadcast_event(pool_id, "round_started", {"round_number": 2})
    
    # Build competitor snapshot from Round 1
    competitor_snapshot = [
        {"merchant_id": r["merchant_id"], "merchant_name": r["merchant_name"], "total_price": r["total_price"]}
        for r in round1_results
    ]
    
    round2_tasks = []
    for r1 in round1_results:
        m = next(m for m in merchants if m["id"] == r1["merchant_id"])
        round2_tasks.append(
            run_round_for_merchant(
                sb, pool_id, m, signals, 
                round_number=2, 
                competitor_snapshot=competitor_snapshot,
                prev_round_data=r1
            )
        )
        
    round2_results = await asyncio.gather(*round2_tasks)
    
    sb.table("multi_product_pools").update({
        "total_rounds": 2,
        "negotiation_status": "converged"
    }).eq("id", pool_id).execute()
    
    await broadcast_event(pool_id, "round_complete", {"round_number": 2})
    await broadcast_event(pool_id, "negotiation_complete", {"pool_id": pool_id})
    
    # After negotiation, automatically trigger the Buyer Agent to evaluate and allocate
    await broadcast_event(pool_id, "buyer_evaluating", {"pool_id": pool_id})
    
    from app.services.bundle_buyer_agent import run_bundle_buyer_agent
    from app.services.bundle_allocation import allocate_bundle_orders
    
    # Map final rounds to 'bundle_offers' format for buyer agent compatibility
    # The buyer agent expects bundle_offers table records.
    # We need to insert these final offers into bundle_offers.
    final_offers = [r for r in round2_results if r]
    
    for fo in final_offers:
        coverage_groups = [li["product_group_id"] for li in fo.get("line_items", [])]
        bundle_offer = {
            "multi_product_pool_id": pool_id,
            "merchant_id": fo["merchant_id"],
            "subtotal": fo["total_price"],
            "bundle_discount": 0,
            "total_price": fo["total_price"],
            "line_items": fo["line_items"],
            "coverage_product_groups": coverage_groups,
            "fulfillment_status": "FULLY_FULFILLED", 
            "status": "validated",
            "coverage_percentage": 100
        }
        
        # INSERT AND GET ID
        res = sb.table("bundle_offers").insert(bundle_offer).execute()
        if res.data:
            fo["bundle_offer_id"] = res.data[0]["id"]
            
    # Now run buyer agent
    try:
        buyer_result = run_bundle_buyer_agent(pool_id)
        allocation_plan = buyer_result.get("allocation_plan", [])
        validation_passed = buyer_result.get("validation_passed", False)
        
        if allocation_plan and validation_passed:
            allocate_bundle_orders(pool_id, allocation_plan)
            
        await broadcast_event(pool_id, "buyer_decision", {
            "allocation_plan": allocation_plan,
            "decision": buyer_result.get("decision"),
            "reasoning": buyer_result.get("reasoning")
        })
    except Exception as e:
        logger.error(f"Buyer agent crashed: {e}", exc_info=True)
        await broadcast_event(pool_id, "buyer_error", {"error": str(e)})

async def sse_generator(request: Request, pool_id: str) -> AsyncGenerator[str, None]:
    """Generates SSE events for the given pool_id"""
    queue = get_sse_queue(pool_id)
    try:
        while True:
            if await request.is_disconnected():
                break
            message = await queue.get()
            yield message
    except asyncio.CancelledError:
        pass
    finally:
        # Cleanup could happen here if needed, but in-memory queues are fine for demo
        pass

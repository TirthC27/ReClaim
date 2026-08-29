"""
Buyer Agent — Step 4 of the offer pipeline.

Takes all validated offers for a demand pool and produces a ranked
allocation plan across merchants, splitting pooled demand by capacity
when no single merchant can fulfil the full pool alone.
"""

import json
import logging
from uuid import UUID

from app.db.client import get_supabase
from app.services.llm_client import call_with_fallback

logger = logging.getLogger(__name__)

BUYER_AGENT_MODELS = ["deepseek/deepseek-chat"]

BUYER_AGENT_SYSTEM_PROMPT = """You represent a pool of buyers who all want the same product. \
You will be given a list of validated offers from competing merchants for this product, \
the total quantity of demand to fulfil, and each offering merchant's available stock for \
this product. Rank the offers by genuine value to the buyer: consider price, bundled items, \
warranty, and service together — not price alone. A lower price with no extras is not \
automatically better than a slightly higher price with a valuable bundle. Then produce an \
allocation plan that fills the total demand quantity starting from your top-ranked offer, \
moving to the next-ranked offer only when a merchant's available stock is exhausted. Never \
assign more units to a merchant than their stated available stock. Respond in valid JSON only, \
matching this exact schema:
{
  "ranking": [
    {"offer_id": "<uuid>", "rank": <int starting at 1>, "reasoning": "<one sentence>"}
  ],
  "allocation_plan": [
    {"offer_id": "<uuid>", "merchant_id": "<uuid>", "units": <int>}
  ]
}
"""


def _fetch_validated_offers(pool_id: str) -> list[dict]:
    supabase = get_supabase()
    resp = (
        supabase.table("offers")
        .select("id,merchant_id,offer_type,price,bundled_items,description,value_score")
        .eq("demand_pool_id", pool_id)
        .eq("status", "validated")
        .execute()
    )
    return resp.data or []


def _fetch_merchant_stock(merchant_id: str, product_id: str) -> int:
    supabase = get_supabase()
    resp = (
        supabase.table("merchants")
        .select("stock_data")
        .eq("id", merchant_id)
        .single()
        .execute()
    )
    stock_data = (resp.data or {}).get("stock_data") or {}
    # stock_data may be keyed by product_id or be a flat {"available_qty": N} — handle both
    if product_id in stock_data:
        return int(stock_data[product_id].get("qty", 0)) if isinstance(stock_data[product_id], dict) else int(stock_data[product_id])
    return int(stock_data.get("available_qty", 0))


def _build_user_content(offers: list[dict], total_demand_qty: int, merchant_stock: dict[str, int]) -> str:
    sanitized_offers = [
        {
            "offer_id": o["id"],
            "merchant_id": o["merchant_id"],
            "offer_type": o["offer_type"],
            "price": float(o["price"]) if o["price"] is not None else None,
            "bundled_items": o.get("bundled_items") or [],
            "description": o.get("description") or "",
            "merchant_available_stock": merchant_stock.get(o["merchant_id"], 0),
        }
        for o in offers
    ]
    return json.dumps({
        "total_demand_qty": total_demand_qty,
        "offers": sanitized_offers,
    })


def _clip_allocation_plan(plan: list[dict], merchant_stock: dict[str, int]) -> list[dict]:
    """Deterministic guardrail: never let the LLM's plan exceed real stock."""
    clipped = []
    remaining_stock = dict(merchant_stock)
    for entry in plan:
        merchant_id = entry["merchant_id"]
        requested = int(entry["units"])
        available = remaining_stock.get(merchant_id, 0)
        actual = min(requested, available)
        if actual > 0:
            clipped.append({**entry, "units": actual})
            remaining_stock[merchant_id] = available - actual
        if actual < requested:
            logger.warning(
                f"[buyer_agent] Clipped merchant {merchant_id} allocation from "
                f"{requested} to {actual} units (stock limit)"
            )
    return clipped


def run_buyer_agent(pool_id: str, product_id: str, total_demand_qty: int) -> dict:
    """
    Runs the Buyer Agent for a resolved demand pool. Returns the ranking +
    clipped allocation plan, and persists buyer_agent_reasoning + offer.buyer_rank.
    """
    supabase = get_supabase()
    offers = _fetch_validated_offers(pool_id)
    if not offers:
        logger.warning(f"[buyer_agent] No validated offers for pool {pool_id}, skipping")
        return {"ranking": [], "allocation_plan": []}

    merchant_stock = {
        o["merchant_id"]: _fetch_merchant_stock(o["merchant_id"], product_id)
        for o in offers
    }

    user_content = _build_user_content(offers, total_demand_qty, merchant_stock)

    result = call_with_fallback(
        BUYER_AGENT_MODELS,
        BUYER_AGENT_SYSTEM_PROMPT,
        user_content,
        step_name="step4-buyer-agent",
    )

    ranking = result.get("ranking", [])
    raw_plan = result.get("allocation_plan", [])
    clipped_plan = _clip_allocation_plan(raw_plan, merchant_stock)

    # Persist ranking on demand_pools
    supabase.table("demand_pools").update({
        "buyer_agent_reasoning": {"ranking": ranking, "raw_allocation_plan": raw_plan, "clipped_allocation_plan": clipped_plan}
    }).eq("id", pool_id).execute()

    # Persist buyer_rank on each offer
    for r in ranking:
        supabase.table("offers").update({"buyer_rank": r["rank"]}).eq("id", r["offer_id"]).execute()

    return {"ranking": ranking, "allocation_plan": clipped_plan}

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
from app.services.shopify_inventory import get_stock_with_fallback

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

IMPORTANT: A warranty, service, or bundle offer with NO price discount is only worth
more than a plain discount offer if its added value can be reasonably quantified from
the data provided. If a merchant's own reasoning states their cost, stock, or warranty
data is missing, treat their non-price claim as unverified and worth zero extra — do
not rank it above a competitor's real, guaranteed price discount. When in doubt, prefer
the offer with the largest verified discount.
"""

def _compute_effective_value(offer: dict) -> float:
    """
    Effective value = guaranteed savings vs list price, ignoring vague
    non-price claims (warranty/service) when the merchant's own
    strategy_reasoning shows missing cost/stock/warranty data —
    an unquantified benefit is worth 0 extra, not a tiebreaker win.
    """
    list_price = offer.get("list_price") or offer["price"]  # fetch actual list price for comparison
    guaranteed_discount = max(0, list_price - offer["price"])

    reasoning = offer.get("strategy_reasoning") or {}
    data_gaps = (
        reasoning.get("data_completeness") or reasoning.get("data_availability") or {}
    )
    has_real_data = not any(v == "missing" for v in data_gaps.values()) if data_gaps else True

    if offer["offer_type"] in ("warranty", "service") and offer["price"] >= list_price and not has_real_data:
        # No real discount AND no verified cost basis for the "free" warranty/service claim
        # → treat its added value as zero, not a premium offer
        return guaranteed_discount  # effectively just the discount amount (0 here)

    return guaranteed_discount  # extend later to add verified bundle/warranty value once real cost data exists



def _fetch_validated_offers(pool_id: str) -> list[dict]:
    supabase = get_supabase()
    resp = (
        supabase.table("offers")
        .select("id,merchant_id,offer_type,price,bundled_items,description,value_score,strategy_reasoning")
        .eq("demand_pool_id", pool_id)
        .eq("status", "validated")
        .execute()
    )
    return resp.data or []


def _fetch_merchant_stock(merchant_id: str, sku: str) -> int:
    qty, source = get_stock_with_fallback(merchant_id, sku)
    logger.info(
        "[buyer_agent] Stock resolved merchant=%s sku=%s qty=%s source=%s",
        merchant_id, sku, qty, source,
    )
    return qty


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

    # Attach list price for effective value calculation
    product_resp = supabase.table("products").select("price,sku").eq("id", product_id).execute()
    if not product_resp.data:
        raise ValueError(f"No product found for product_id={product_id} — check caller is passing a real product ID, not a product_group_id")
    list_price = float(product_resp.data[0]["price"]) if product_resp.data[0].get("price") else 0.0
    product_sku = product_resp.data[0].get("sku") or ""
    for o in offers:
        o["list_price"] = list_price

    # Pre-rank by effective value descending
    offers.sort(key=_compute_effective_value, reverse=True)

    merchant_stock = {
        o["merchant_id"]: _fetch_merchant_stock(o["merchant_id"], product_sku)
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

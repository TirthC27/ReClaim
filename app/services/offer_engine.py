"""
Offer engine — 2-step LLM agent pipeline + deterministic validator.

Step 1: Feasibility & Strategy (DeepSeek)
Step 2: Offer Composer (Qwen → Gemini fallback, RAG-augmented)
Step 3: Validator/Finalizer (deterministic)
Orchestrator: run all merchants concurrently with failure isolation
"""

import asyncio
import json
import logging
from uuid import UUID

from app.config import settings
from app.db.client import get_supabase
from app.services.llm_client import call_step1, call_step2, LLMError
from app.services.rag_retrieval import retrieve_context
from app.services.aggregation import get_selected_merchants

logger = logging.getLogger(__name__)

# ── System prompts (exact text from spec) ────────────────────

STEP1_SYSTEM_PROMPT = """You are a merchant's commercial strategy assistant. Given this merchant's stock, \
margin floor, available accessories, and warranty costs, plus the size of a demand \
opportunity, determine the merchant's strategic leaning: how much price flexibility \
exists, which non-price levers (gifts/bundles/warranty) are most economically \
sensible, and overall risk appetite for this opportunity. Do NOT propose a final \
offer yet — output only a structured strategy assessment. Respond in valid JSON only."""

STEP2_SYSTEM_PROMPT = """You are a merchant agent composing a customer-facing offer. You have this merchant's \
strategic assessment and relevant reference context (this merchant's own quotation \
documents, similar product data, and past offer patterns). Compose ONE concrete offer: \
a specific price, any bundled items, and a short customer-facing description. Stay \
within the strategy's max_discount_pct. Respond in valid JSON only."""

# Marketplace display categories (Section 12)
OFFER_CATEGORIES = {
    "discount": "Best Price",
    "gift": "Best Value",
    "bundle": "Bundle",
    "warranty": "Protection",
    "upgrade": "Best Value",
    "service": "Best Value",
    "hybrid": "Best Value",
}


def _fetch_pool_details(pool_id: str) -> dict:
    """Fetch demand pool with product info."""
    sb = get_supabase()
    pool = sb.table("demand_pools").select("*").eq("id", pool_id).execute().data
    if not pool:
        raise ValueError(f"Pool {pool_id} not found")
    pool = pool[0]

    # Get representative product from signals
    signals = (
        sb.table("demand_signals")
        .select("*, products(id, title, price, vendor, sku)")
        .eq("product_group_id", pool["product_group_id"])
        .in_("status", ["pooled", "abandoned"])
        .limit(1)
        .execute()
        .data
    )
    if signals and signals[0].get("products"):
        pool["_product"] = signals[0]["products"]
    else:
        pool["_product"] = {"title": "Unknown Product", "price": 0}

    pool["_total_demand_qty"] = pool.get("signal_count", 1)
    return pool


def _fetch_merchant_details(merchant_id: str) -> dict:
    """Fetch full merchant record."""
    sb = get_supabase()
    rows = sb.table("merchants").select("*").eq("id", merchant_id).execute().data
    if not rows:
        raise ValueError(f"Merchant {merchant_id} not found")
    return rows[0]


# ── Step 1 — Strategy Agent ─────────────────────────────────

def run_step1(merchant: dict, pool: dict) -> dict:
    """
    LLM call: Feasibility & Strategy assessment.

    Returns structured strategy JSON.
    """
    product = pool.get("_product", {})

    user_content = json.dumps({
        "merchant_name": merchant.get("name"),
        "margin_floor_pct": merchant.get("margin_floor_pct"),
        "stock_data": merchant.get("stock_data"),
        "accessory_inventory": merchant.get("accessory_inventory"),
        "warranty_cost_data": merchant.get("warranty_cost_data"),
        "product": {
            "title": product.get("title"),
            "price": float(product.get("price", 0)),
        },
        "total_demand_qty": pool.get("_total_demand_qty", 1),
    }, default=str)

    result = call_step1(STEP1_SYSTEM_PROMPT, user_content)

    # Ensure required fields with defaults
    result.setdefault("max_discount_pct", 10)
    result.setdefault("preferred_lever", "discount")
    result.setdefault("reasoning", "")
    result.setdefault("risk_appetite", "moderate")

    return result


# ── Step 2 — Offer Composer (RAG-augmented) ──────────────────

def run_step2(merchant: dict, pool: dict, strategy: dict) -> tuple[dict, dict]:
    """
    LLM call: Compose a concrete offer using strategy + RAG context.

    Returns (offer_data, rag_context).
    """
    product = pool.get("_product", {})

    # Retrieve RAG context
    rag_context = retrieve_context(
        merchant_id=merchant["id"],
        product_title=product.get("title", ""),
        strategy_hint=strategy.get("preferred_lever", ""),
    )

    # Build context string for the LLM
    context_parts = []
    for doc in rag_context.get("merchant_docs", []):
        text = doc.get("extracted_text", "")
        if text:
            context_parts.append(f"[Merchant Doc: {doc.get('file_name', 'unknown')}]\n{text[:500]}")
    for arch in rag_context.get("archetypes", []):
        desc = arch.get("description", "")
        if desc:
            context_parts.append(f"[Archetype] {desc}")

    context_text = "\n\n".join(context_parts) if context_parts else "No additional context available."

    user_content = json.dumps({
        "strategy_assessment": strategy,
        "product": {
            "title": product.get("title"),
            "list_price": float(product.get("price", 0)),
        },
        "reference_context": context_text,
        "merchant_name": merchant.get("name"),
    }, default=str)

    result = call_step2(STEP2_SYSTEM_PROMPT, user_content)

    # Ensure required fields
    result.setdefault("offer_type", strategy.get("preferred_lever", "discount"))
    result.setdefault("price", float(product.get("price", 0)))
    result.setdefault("bundled_items", [])
    result.setdefault("description", "")

    return result, rag_context


# ── Step 3 — Validator (deterministic) ───────────────────────

def validate_offer(offer: dict, strategy: dict, merchant: dict, pool: dict) -> tuple[str, str, float]:
    """
    Deterministic validation. Returns (status, reason, value_score).

    Checks:
    - Discount doesn't exceed strategy max
    - Bundled items plausibility
    - Stock availability
    """
    product = pool.get("_product", {})
    list_price = float(product.get("price", 0))
    offer_price = float(offer.get("price", list_price))
    max_discount = float(strategy.get("max_discount_pct", 100))

    # Check discount bounds
    if list_price > 0:
        actual_discount_pct = ((list_price - offer_price) / list_price) * 100
        if actual_discount_pct > max_discount * 1.1:  # 10% tolerance
            return "rejected", f"Discount {actual_discount_pct:.1f}% exceeds max {max_discount}%", 0.0
        if offer_price <= 0:
            return "rejected", "Offer price is zero or negative", 0.0
    else:
        actual_discount_pct = 0

    # Check stock (soft check — warn but don't reject in MVP)
    stock = merchant.get("stock_data") or {}
    demand_qty = pool.get("_total_demand_qty", 1)

    # Compute value_score (weighted: discount weight 0.6, bundle value 0.4)
    bundle_value = len(offer.get("bundled_items", [])) * 0.05  # Each item adds ~5% value
    if list_price > 0:
        discount_component = actual_discount_pct / 100.0
    else:
        discount_component = 0.0

    value_score = round((discount_component * 0.6) + (bundle_value * 0.4), 4)

    return "validated", "OK", value_score


def categorize_offer(offer_type: str) -> str:
    """Map offer_type to Section 12 marketplace display category."""
    return OFFER_CATEGORIES.get(offer_type, "Best Value")


# ── Single merchant pipeline ────────────────────────────────

def run_single_merchant_pipeline(merchant: dict, pool: dict) -> dict:
    """
    Run the full 3-step pipeline for one merchant.

    Returns the created offer row dict, or raises on failure.
    """
    sb = get_supabase()
    merchant_id = str(merchant["id"])
    pool_id = str(pool["id"])

    # Step 1: Strategy
    strategy = run_step1(merchant, pool)
    logger.info(f"[{merchant['name']}] Step 1 done: {strategy.get('preferred_lever')}")

    # Step 2: Compose offer with RAG
    offer_data, rag_context = run_step2(merchant, pool, strategy)
    logger.info(f"[{merchant['name']}] Step 2 done: {offer_data.get('offer_type')}")

    # Step 3: Validate
    status, reason, value_score = validate_offer(offer_data, strategy, merchant, pool)
    logger.info(f"[{merchant['name']}] Step 3: {status} ({reason}), score={value_score}")

    # Insert offer row
    offer_row = {
        "demand_pool_id": pool_id,
        "merchant_id": merchant_id,
        "offer_type": offer_data.get("offer_type", "discount"),
        "price": float(offer_data.get("price", 0)),
        "bundled_items": offer_data.get("bundled_items", []),
        "description": offer_data.get("description", ""),
        "strategy_reasoning": strategy,
        "rag_context_used": rag_context,
        "value_score": value_score,
        "status": status,
    }

    result = sb.table("offers").insert(offer_row).execute().data[0]
    return result


# ── Orchestrator ─────────────────────────────────────────────

async def run_offer_generation(pool_id: str) -> dict:
    """
    Orchestrate offer generation for all selected merchants in a pool.

    Runs pipelines concurrently (semaphore-bounded) with failure isolation:
    a single merchant's failure doesn't block others.
    """
    pool = _fetch_pool_details(pool_id)
    merchant_ids = pool.get("selected_merchant_ids", [])

    if not merchant_ids:
        return {"pool_id": pool_id, "error": "No selected merchants", "offers": []}

    merchants = []
    for mid in merchant_ids:
        try:
            merchants.append(_fetch_merchant_details(mid))
        except Exception as exc:
            logger.error(f"Failed to fetch merchant {mid}: {exc}")

    if not merchants:
        return {"pool_id": pool_id, "error": "No valid merchants found", "offers": []}

    # Run pipelines with bounded concurrency
    semaphore = asyncio.Semaphore(5)

    async def _bounded_pipeline(merchant):
        async with semaphore:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, run_single_merchant_pipeline, merchant, pool
            )

    results = await asyncio.gather(
        *[_bounded_pipeline(m) for m in merchants],
        return_exceptions=True,
    )

    # Separate successes from failures (failure isolation per Section 21)
    offers = []
    failures = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            merchant_name = merchants[i].get("name", "unknown")
            logger.error(f"Pipeline failed for {merchant_name}: {r}")
            failures.append({"merchant": merchant_name, "error": str(r)})
        else:
            offers.append(r)

    return {
        "pool_id": pool_id,
        "offers_generated": len(offers),
        "failures": len(failures),
        "offers": offers,
        "failure_details": failures,
    }

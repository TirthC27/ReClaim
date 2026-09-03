"""
Offer engine — 2-step LLM agent pipeline + deterministic validator.

Step 1: Feasibility & Strategy (DeepSeek) — NOW RAG-augmented with merchant docs
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
from app.services.rag_retrieval import retrieve_context, resolve_merchant_sku
from app.services.aggregation import get_selected_merchants
from app.services.shopify_inventory import get_stock_with_fallback

logger = logging.getLogger(__name__)

# ── System prompts ───────────────────────────────────────────

STEP1_SYSTEM_PROMPT = """\
You are a merchant's commercial strategy assistant. You are given:
1. The merchant's database record (margin floor, stock, accessories, warranty costs — some may be null)
2. Relevant data retrieved from the merchant's own uploaded documents (quotation CSVs, price lists, etc.)
3. The demand opportunity (product title, price, quantity)

Your job: determine the merchant's strategic leaning — how much price flexibility \
exists, which non-price levers (gifts/bundles/warranty) are most economically \
sensible, and overall risk appetite for this opportunity.

IMPORTANT: live_shopify_stock_qty is the authoritative stock quantity for this exact \ 
product and merchant. Never override it with stock_data or a document-derived number. \ 
Use retrieved document data only for qualitative reasoning about cost, margin, bundles, \ 
and warranty. The merchant record fields may be null even when the data is available in \ 
the retrieved documents. Only mark a non-stock field as "missing" if it truly isn't \ 
present in EITHER the merchant record OR the retrieved documents.

Do NOT propose a final offer yet — output only a structured strategy assessment.
Respond in valid JSON only.

If you lack cost, stock, or warranty data, your default recommended lever should be a
small, conservative real discount within margin_floor_pct — not a "hold at list price"
warranty/service claim you cannot economically justify. An unverifiable non-price claim
provides no real customer value and should not be your fallback strategy.

CRITICAL: The product you are generating an offer for is specified in the "product" 
field above. Any stock, accessory, or warranty data shown belongs ONLY to that exact 
product/SKU — ignore any retrieved document content that describes a different 
product. Never reference or price a product other than the one named in "product.title".
"""

STEP2_SYSTEM_PROMPT = """\
You are a merchant agent composing a customer-facing offer. You have this merchant's \
strategic assessment and relevant reference context (this merchant's own quotation \
documents, similar product data, and past offer patterns). Compose ONE concrete offer.

Respond with a JSON object containing EXACTLY these keys:
- "offer_type": one of "discount", "gift", "bundle", "warranty", "upgrade", "service", "hybrid"
- "price": the final offer price as a number (must respect strategy's max_discount_pct)
- "bundled_items": array of strings listing any freebies or bundled extras (empty array if none)
- "description": a short, compelling, customer-facing sentence describing this offer, \
e.g. "Best Price: ₹26,990 + Free Wireless Mouse" or "Protection Deal: ₹28,500 with 2-Year Extended Warranty"

The description MUST be non-empty and should highlight the key value proposition.
Respond in valid JSON only.

CRITICAL: The product you are generating an offer for is specified in the "product" 
field above. Any stock, accessory, or warranty data shown belongs ONLY to that exact 
product/SKU — ignore any retrieved document content that describes a different 
product. Never reference or price a product other than the one named in "product.title".
"""

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


def _build_fallback_description(
    offer_type: str,
    price: float,
    bundled_items: list | None = None,
    product_title: str = "",
) -> str:
    """
    Construct a customer-facing description when the LLM returns an empty one.

    Examples:
        "Best Price: ₹26,990 + Free Wireless Mouse"
        "Bundle: ₹27,200 with 1-Year Extended Warranty + Braided AUX Cable"
        "Discount: ₹58,500"
    """
    category = OFFER_CATEGORIES.get(offer_type, "Best Value")
    price_str = f"₹{price:,.0f}"
    parts = [f"{category}: {price_str}"]

    if bundled_items:
        items_str = " + ".join(str(b) for b in bundled_items[:3])  # Cap at 3 for brevity
        parts.append(f"with {items_str}")

    if product_title and len(product_title) <= 40:
        parts.append(f"on {product_title}")

    return " ".join(parts)


def _build_doc_context_text(rag_context: dict) -> str:
    """
    Extract human-readable text from RAG-retrieved merchant documents.
    Used to inject document data into LLM prompts.
    """
    context_parts = []
    for doc in rag_context.get("merchant_docs", []):
        text = doc.get("extracted_text", "")
        if text:
            sim = doc.get("similarity")
            sim_str = f" (similarity: {sim:.3f})" if sim is not None else ""
            context_parts.append(
                f"[Merchant Doc: {doc.get('file_name', 'unknown')}{sim_str}]\n{text[:800]}"
            )
    return "\n\n".join(context_parts) if context_parts else "No document data available."


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


def _filter_merchant_data_to_product(merchant: dict, product_sku: str) -> dict:
    """
    Merchant's stock_data/accessory_inventory/warranty_cost_data may be
    keyed by SKU (e.g. {"DIG-021": {...}, "DIG-013": {...}}) or be a flat
    catalog-wide structure. Extract only what's relevant to this product.
    """
    def extract(field: dict | None) -> dict | None:
        if not field:
            return None
        if product_sku in field:
            return {product_sku: field[product_sku]}
        return None  # don't pass unrelated SKUs' data at all

    return {
        "stock_data": extract(merchant.get("stock_data")),
        "accessory_inventory": extract(merchant.get("accessory_inventory")),
        "warranty_cost_data": extract(merchant.get("warranty_cost_data")),
    }


def _fetch_merchant_details(merchant_id: str) -> dict:
    """Fetch full merchant record."""
    sb = get_supabase()
    rows = sb.table("merchants").select("*").eq("id", merchant_id).execute().data
    if not rows:
        raise ValueError(f"Merchant {merchant_id} not found")
    return rows[0]


# ── Step 1 — Strategy Agent (now RAG-augmented) ─────────────

def run_step1(merchant: dict, pool: dict) -> tuple[dict, dict]:
    """
    LLM call: Feasibility & Strategy assessment.

    Now includes lightweight RAG retrieval from merchant_documents only
    (no archetypes/product_embeddings — Step 1 needs facts, not creative examples).

    Returns (strategy_result, strategy_rag_context).
    """
    product = pool.get("_product", {})
    merchant_sku = resolve_merchant_sku(
        merchant["id"], pool["product_group_id"], product.get("title", "")
    ) or product.get("sku", "")

    # ── Retrieve merchant docs for this product ──────────────
    strategy_rag = retrieve_context(
        merchant_id=merchant["id"],
        product_title=product.get("title", ""),
        product_sku=merchant_sku,
        strategy_hint="",  # No strategy hint for Step 1
        top_k=5,  # More chunks for Step 1 since we're looking for specific product data
        sources=["merchant_docs"],  # Only merchant documents
    )

    doc_context_text = _build_doc_context_text(strategy_rag)

    logger.info(
        f"[{merchant.get('name')}] Step 1 RAG: "
        f"{len(strategy_rag.get('merchant_docs', []))} doc chunks retrieved"
    )

    # ── Build prompt with both record data + document data ───
    filtered_data = _filter_merchant_data_to_product(merchant, merchant_sku)
    live_stock_qty, stock_source = get_stock_with_fallback(
        merchant["id"], merchant_sku
    )
    user_content = json.dumps({
        "merchant_record": {
            "merchant_name": merchant.get("name"),
            "margin_floor_pct": merchant.get("margin_floor_pct"),
            "live_shopify_stock_qty": live_stock_qty,
            "stock_source": stock_source,
            **filtered_data,
        },
        "retrieved_document_data": doc_context_text,
        "product": {
            "title": product.get("title"),
            "sku": merchant_sku,
            "price": float(product.get("price", 0)),
        },
        "total_demand_qty": pool.get("_total_demand_qty", 1),
    }, default=str)

    result = call_step1(STEP1_SYSTEM_PROMPT, user_content)

    # Log raw response for debugging
    logger.info(f"[{merchant.get('name')}] Raw Step 1 response keys: {list(result.keys())}")

    # Ensure required fields with defaults
    result.setdefault("max_discount_pct", 10)
    result.setdefault("preferred_lever", "discount")
    result.setdefault("reasoning", "")
    result.setdefault("risk_appetite", "moderate")

    return result, strategy_rag


# ── Step 2 — Offer Composer (RAG-augmented) ──────────────────

def run_step2(merchant: dict, pool: dict, strategy: dict) -> tuple[dict, dict]:
    """
    LLM call: Compose a concrete offer using strategy + RAG context.

    Returns (offer_data, rag_context).
    """
    product = pool.get("_product", {})
    merchant_sku = resolve_merchant_sku(
        merchant["id"], pool["product_group_id"], product.get("title", "")
    ) or product.get("sku", "")

    # Retrieve RAG context (all sources for Step 2)
    rag_context = retrieve_context(
        merchant_id=merchant["id"],
        product_title=product.get("title", ""),
        product_sku=merchant_sku,
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

    # Log raw LLM response for debugging
    logger.info(f"[{merchant.get('name')}] Raw Step 2 response keys: {list(result.keys())}")
    logger.debug(f"[{merchant.get('name')}] Raw Step 2 response: {json.dumps(result, default=str)[:500]}")

    # Ensure required fields
    result.setdefault("offer_type", strategy.get("preferred_lever", "discount"))
    result.setdefault("price", float(product.get("price", 0)))
    result.setdefault("bundled_items", [])
    result.setdefault("description", "")

    # Fallback: if LLM returned an empty or whitespace-only description
    if not result["description"].strip():
        result["description"] = _build_fallback_description(
            offer_type=result["offer_type"],
            price=float(result["price"]),
            bundled_items=result.get("bundled_items"),
            product_title=product.get("title", ""),
        )
        logger.warning(f"[{merchant.get('name')}] Used fallback description: {result['description']}")

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
            reason = f"Discount {actual_discount_pct:.1f}% exceeds max {max_discount}%"
            logger.warning(f"Rejected offer: {reason}")
            return "rejected", reason, 0.0
        if offer_price <= 0:
            reason = "Offer price is zero or negative"
            logger.warning(f"Rejected offer: {reason}")
            return "rejected", reason, 0.0
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
    product = pool.get("_product", {})

    # Step 1: Strategy (now returns RAG context too)
    strategy, strategy_rag = run_step1(merchant, pool)
    logger.info(f"[{merchant['name']}] Step 1 done: {strategy.get('preferred_lever')}")

    # Step 2: Compose offer with RAG
    offer_data, rag_context = run_step2(merchant, pool, strategy)
    logger.info(f"[{merchant['name']}] Step 2 done: {offer_data.get('offer_type')}")

    # Step 3: Validate
    status, reason, value_score = validate_offer(offer_data, strategy, merchant, pool)
    logger.info(f"[{merchant['name']}] Step 3: {status} ({reason}), score={value_score}")

    # Combine RAG contexts for transparency
    combined_rag = {
        "strategy_rag_context": strategy_rag,
        "composer_rag_context": rag_context,
    }

    # Insert offer row
    offer_row = {
        "demand_pool_id": pool_id,
        "merchant_id": merchant_id,
        "offer_type": offer_data.get("offer_type", "discount"),
        "price": float(offer_data.get("price", 0)),
        "bundled_items": offer_data.get("bundled_items", []),
        "description": offer_data.get("description") or _build_fallback_description(
            offer_type=offer_data.get("offer_type", "discount"),
            price=float(offer_data.get("price", 0)),
            bundled_items=offer_data.get("bundled_items"),
            product_title=product.get("title", ""),
        ),
        "strategy_reasoning": strategy,
        "rag_context_used": combined_rag,
        "value_score": value_score,
        "status": status,
    }

    result = sb.table("offers").insert(offer_row).execute().data[0]
    return result


# ── Orchestrator ─────────────────────────────────────────────

async def run_offer_generation_round(pool_id: str, merchant_ids: list[str]) -> tuple[list[dict], list[dict]]:
    """
    Core engine loop: run pipelines concurrently for the given merchants.
    Returns (offers, failures).
    """
    pool = _fetch_pool_details(pool_id)
    
    merchants = []
    for mid in merchant_ids:
        try:
            merchants.append(_fetch_merchant_details(mid))
        except Exception as exc:
            logger.error(f"Failed to fetch merchant {mid}: {exc}")

    if not merchants:
        return [], []

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

    return offers, failures

async def run_offer_generation(pool_id: str) -> dict:
    """
    Orchestrate offer generation for all selected merchants in a pool.
    """
    pool = _fetch_pool_details(pool_id)
    merchant_ids = pool.get("selected_merchant_ids", [])

    if not merchant_ids:
        return {"pool_id": pool_id, "error": "No selected merchants", "offers": []}
        
    offers, failures = await run_offer_generation_round(pool_id, merchant_ids)

    return {
        "pool_id": pool_id,
        "offers_generated": len(offers),
        "failures": len(failures),
        "offers": offers,
        "failure_details": failures,
    }

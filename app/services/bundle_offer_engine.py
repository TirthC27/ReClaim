"""
Bundle Offer Engine — v3 (Agents Decide, Backend Computes)

Architecture:
    Shopify base prices (source of truth)
        ↓
    Seller Agent (LLM + Merchant RAG)
        → outputs discount DECISIONS (percentages, strategy, reasoning)
        → NEVER outputs final prices
        ↓
    Backend Offer Calculator
        → deterministic: shopify_price × (1 - discount%) × quantity
        ↓
    Validator
        → discount within margin floor
        → math correct
        → stock available
        ↓
    bundle_offers record
        → agent_decision (raw LLM output)
        → backend-computed prices (line_items, subtotal, total_price)

Price computation chain (sequential, unambiguous):
    Shopify price → per-product discount → subtotal → bundle discount → final total
"""

import json
import logging
import asyncio
from app.db.client import get_supabase
from app.services.llm_client import call_with_fallback
from app.services.strategies import strategies_context_text
from app.services.shopify_inventory import get_stock_with_fallback
from app.services.rag_retrieval import retrieve_context

logger = logging.getLogger(__name__)
sb = get_supabase()

STRATEGY_MODELS = ["deepseek/deepseek-chat", "openai/gpt-4o-mini"]
COMPOSER_MODELS = ["deepseek/deepseek-chat", "openai/gpt-4o-mini"]


# ─── SELLER AGENT PROMPTS ────────────────────────────────────

BUNDLE_STRATEGY_PROMPT = f"""You are a merchant pricing AI evaluating a multi-product demand pool.
You will be given:
1. Live Shopify context (current list price, current live inventory).
2. Quotation economics context (historical wholesale cost, margins, your own uploaded business documents).
3. The total requested customer demand quantity.

Determine a pricing strategy for the ENTIRE basket you can cover.
CRITICAL RULE: "Quotation Stock Qty" is strictly historical context. Use "Shopify Inventory" as the live stock authority.
{strategies_context_text()}

You do not need to cover every product in the basket, but you must offer a strategy for the ones you do stock.
Output valid JSON:
{{
  "strategy_name": "<name>",
  "reasoning": "<why this strategy for this basket>",
  "per_product_max_discount": {{
    "<product_group_id>": <number>
  }},
  "overall_bundle_margin_floor": <number>,
  "data_availability": {{"cost_missing": true/false}}
}}
"""


BUNDLE_COMPOSER_PROMPT = """You are a merchant's pricing negotiator for a multi-product bundle.
You will be given the basket products, your strategic assessment, and the merchant's own business documents.

Your job: decide what DISCOUNT to offer on each product, and whether to add a bundle-level discount
for buying everything together.

CRITICAL RULES:
- You output DISCOUNT PERCENTAGES, never final prices. The backend calculates all prices.
- per_product_discounts: the discount % for each product you cover (e.g. 7 means 7% off)
- bundle_discount_pct: an ADDITIONAL discount applied to the subtotal for buying together (e.g. 2 means 2% extra off the subtotal)
- These are SEQUENTIAL: base price → per-product discount → subtotal → bundle discount → final
- The bundle_discount_pct is SEPARATE from per_product_discounts — it is an extra incentive, not already included
- Each per-product discount must be within that product's max_discount from the strategy
- bundle_benefits should list actual value-adds (free shipping, extended warranty, etc.)

Output valid JSON matching EXACTLY:
{
  "discount_type": "percentage",
  "per_product_discounts": {
    "<product_group_id>": <number 0-100>
  },
  "bundle_discount_pct": <number 0-100>,
  "bundle_benefits": ["<benefit_1>", "<benefit_2>"],
  "reasoning": {
    "demand": "<why this discount given demand>",
    "inventory": "<inventory-based reasoning>",
    "policy": "<reference to retrieved policy documents>",
    "strategy": "<overall strategic reasoning>"
  }
}

DO NOT output prices, totals, subtotals, or unit_prices. Those are backend territory.
"""


# ─── MERCHANT CONTEXT BUILDER ────────────────────────────────

def _fetch_merchant_basket_context(merchant_id: str, pool: dict, product_groups: list[dict]) -> dict:
    """Fetch the merchant's cost basis, stock, and RAG docs for all products in the basket."""
    from app.services.product_context import build_seller_context

    merchant_resp = sb.table("merchants").select("*").eq("id", merchant_id).single().execute()
    merchant = merchant_resp.data if merchant_resp.data else {}

    products_context = []
    coverage_product_groups = []

    for pg in product_groups:
        gid = pg["product_group_id"]
        
        # Build combined context from new resolver
        ctx = build_seller_context(merchant_id=merchant_id, product_group_id=gid)
        
        if ctx["live_shopify"] or ctx["quotation_economics"]:
            # Check if this merchant actually covers it
            # We assume if product_context returned anything with shopify_product_id or q_sku, it's covered
            if ctx["live_shopify"].get("shopify_product_id") or ctx["quotation_economics"].get("quotation_sku"):
                coverage_product_groups.append(gid)
                
                # We still fetch the product title for context formatting
                prod = None
                if ctx["live_shopify"].get("shopify_product_id"):
                    prod_resp = sb.table("products").select("title, sku").eq("shopify_product_id", ctx["live_shopify"]["shopify_product_id"]).execute().data
                    if prod_resp:
                        prod = prod_resp[0]
                elif pg.get("representative_product_id"):
                    prod_resp = sb.table("products").select("title, sku").eq("id", pg["representative_product_id"]).execute().data
                    if prod_resp:
                        prod = prod_resp[0]
                        
                products_context.append({
                    "product_group_id": gid,
                    "title": prod["title"] if prod else "Unknown",
                    "live_shopify": ctx["live_shopify"],
                    "quotation_economics": ctx["quotation_economics"],
                    "requested_qty": pg["aggregated_qty"]
                })

    # Retrieve Seller RAG context (merchant docs — pricing, margins, inventory)
    # We still fetch general docs but since product_context injects SKU-specific historical_context, 
    # we append it to the overall doc text to avoid losing exact SKU pricing.
    product_titles = " ".join(p["title"] for p in products_context)
    seller_rag = retrieve_context(
        merchant_id=merchant_id,
        product_title=product_titles,
        strategy_hint="pricing margin discount strategy inventory",
        top_k=5,
        sources=["merchant_docs"],
    )

    doc_context_text = _build_doc_context_text(seller_rag)
    
    # Inject exact SKU historical context
    exact_contexts = []
    for p in products_context:
        hist = p["quotation_economics"].get("historical_context")
        if hist:
            exact_contexts.append(f"--- SKU {p['quotation_economics']['quotation_sku']} Quotation Data ---\n{hist}")
            
    if exact_contexts:
        doc_context_text += "\n\n" + "\n\n".join(exact_contexts)

    return {
        "merchant": merchant,
        "products": products_context,
        "coverage_product_groups": coverage_product_groups,
        "coverage_ratio": len(coverage_product_groups) / len(product_groups) if product_groups else 0,
        "rag_context": seller_rag,
        "doc_context_text": doc_context_text,
    }


def _build_doc_context_text(rag_context: dict) -> str:
    """Extract human-readable text from RAG-retrieved merchant documents."""
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


# ─── BACKEND OFFER CALCULATOR ────────────────────────────────
# Deterministic: takes Seller Agent's discount decision + Shopify prices → real prices

def _compute_offer_from_decision(
    seller_decision: dict,
    products_context: list[dict],
    coverage_product_groups: list[str],
) -> dict:
    """
    Deterministic price computation from Seller Agent's discount decision.

    Chain (sequential, unambiguous):
        Shopify base price
            → per-product discount (%)
            → discounted unit price
            → subtotal (sum of discounted_unit_price for covered products)
            → bundle discount (% off subtotal)
            → final total

    Returns {line_items, subtotal, bundle_discount_amount, total_price}
    """
    per_product_discounts = seller_decision.get("per_product_discounts", {})
    bundle_discount_pct = float(seller_decision.get("bundle_discount_pct", 0))

    line_items = []
    subtotal = 0.0

    for prod in products_context:
        gid = prod["product_group_id"]
        if gid not in coverage_product_groups:
            continue

        shopify_price = prod["live_shopify"].get("current_price", 0)
        if shopify_price is None or shopify_price == 0:
            raise ValueError(
                f"Product {gid} has price=0 or None — backfill the products table price before generating offers."
            )
        shopify_price = float(shopify_price)
        discount_pct = float(per_product_discounts.get(gid, 0))

        # Clamp discount to [0, 100]
        discount_pct = max(0, min(100, discount_pct))

        unit_price = round(shopify_price * (1 - discount_pct / 100), 2)
        # Note: line_items store unit_price. Quantity is applied later by AllocationBuilder
        # per individual cart, not here at pool level.

        line_items.append({
            "product_group_id": gid,
            "product_title": prod["title"],
            "shopify_list_price": shopify_price,
            "discount_pct": discount_pct,
            "unit_price": unit_price,
        })

        subtotal += unit_price

    subtotal = round(subtotal, 2)

    # Bundle discount applied to the subtotal (sequential, not included in per-product)
    bundle_discount_amount = round(subtotal * (bundle_discount_pct / 100), 2)
    total_price = round(subtotal - bundle_discount_amount, 2)

    return {
        "line_items": line_items,
        "subtotal": subtotal,
        "bundle_discount_pct": bundle_discount_pct,
        "bundle_discount": bundle_discount_amount,
        "total_price": total_price,
    }


# ─── VALIDATOR ────────────────────────────────────────────────

def validate_bundle_offer(
    computed_offer: dict,
    seller_decision: dict,
    strategy: dict,
    context: dict,
) -> tuple:
    """
    Deterministic validation of the backend-computed offer.

    Checks:
    1. Per-product discount ≤ strategy's per_product_max_discount
    2. Per-product discount ≤ merchant's margin_floor_pct
    3. Math: subtotal - bundle_discount == total_price
    4. Stock > 0 for each covered product
    5. No negative prices

    Returns (status, reason, value_score)
    """
    per_product_max = strategy.get("per_product_max_discount", {})
    line_items = computed_offer.get("line_items", [])

    if not line_items:
        return "rejected", "No line items in bundle", 0.0

    for item in line_items:
        gid = item["product_group_id"]
        discount_pct = item["discount_pct"]
        unit_price = item["unit_price"]

        # Check discount within strategy ceiling
        max_discount = float(per_product_max.get(gid, 100))
        if discount_pct > max_discount * 1.1:  # 10% tolerance
            return "rejected", f"Product {gid}: discount {discount_pct}% exceeds strategy max {max_discount}%", 0.0

        # Check discount within margin floor
        ctx_prod = next((p for p in context["products"] if p["product_group_id"] == gid), None)
        if ctx_prod:
            margin_floor = ctx_prod.get("margin_floor_pct", 15)
            if discount_pct > margin_floor * 1.1:
                return "rejected", f"Product {gid}: discount {discount_pct}% exceeds margin floor {margin_floor}%", 0.0

            # Check stock
            if ctx_prod["live_shopify"].get("inventory", 0) <= 0:
                return "rejected", f"Merchant is out of stock for {gid}", 0.0

        # No negative prices
        if unit_price <= 0:
            return "rejected", f"Product {gid}: computed unit_price is ≤0", 0.0

    # Math check
    subtotal = computed_offer["subtotal"]
    bundle_discount = computed_offer["bundle_discount"]
    total_price = computed_offer["total_price"]

    if abs((subtotal - bundle_discount) - total_price) > 0.01:
        return "rejected", f"Math: subtotal({subtotal}) - discount({bundle_discount}) ≠ total({total_price})", 0.0

    # Value score (discount depth relative to list prices)
    list_total = sum(i["shopify_list_price"] for i in line_items)
    if list_total > 0:
        overall_discount_pct = ((list_total - total_price) / list_total) * 100
        value_score = float(min(1.0, overall_discount_pct / 100.0))
    else:
        value_score = 0.0

    return "validated", "Valid bundle offer", value_score


# ─── FULL MERCHANT PIPELINE ──────────────────────────────────

async def run_bundle_merchant_pipeline(merchant_id: str, pool: dict, product_groups: list[dict]) -> dict:
    """Full 3-step pipeline for one merchant → inserts into bundle_offers table."""
    try:
        context = _fetch_merchant_basket_context(merchant_id, pool, product_groups)

        if not context["coverage_product_groups"]:
            logger.info(f"Merchant {merchant_id} covers 0 products for pool {pool['id']}, skipping.")
            return {"error": "no_coverage"}

        # ─── Step 1: Strategy (LLM) ──────────────────────────
        strategy_input = json.dumps({
            "merchant_name": context["merchant"].get("name"),
            "margin_floor_pct": context["merchant"].get("margin_floor_pct"),
            "basket_products": context["products"],
            "retrieved_merchant_documents": context["doc_context_text"],
        })

        strategy = call_with_fallback(
            STRATEGY_MODELS, BUNDLE_STRATEGY_PROMPT, strategy_input,
            step_name="bundle_step1_strategy"
        )

        # ─── Step 2: Discount Decision (LLM) ────────────────
        composer_input = json.dumps({
            "basket_products": context["products"],
            "strategy": strategy,
            "retrieved_merchant_documents": context["doc_context_text"],
        })

        seller_decision = call_with_fallback(
            COMPOSER_MODELS, BUNDLE_COMPOSER_PROMPT, composer_input,
            step_name="bundle_step2_discount_decision"
        )

        logger.info(
            f"[{context['merchant'].get('name')}] Seller decision: "
            f"discounts={seller_decision.get('per_product_discounts')}, "
            f"bundle={seller_decision.get('bundle_discount_pct')}%"
        )

        # ─── Step 3: Backend Compute (deterministic) ─────────
        computed_offer = _compute_offer_from_decision(
            seller_decision, context["products"], context["coverage_product_groups"]
        )

        logger.info(
            f"[{context['merchant'].get('name')}] Backend computed: "
            f"subtotal={computed_offer['subtotal']}, "
            f"bundle_discount={computed_offer['bundle_discount']}, "
            f"total={computed_offer['total_price']}"
        )

        # ─── Step 4: Validate (deterministic) ────────────────
        status, reason, value_score = validate_bundle_offer(
            computed_offer, seller_decision, strategy, context
        )

        if status == "rejected":
            logger.info(f"Bundle offer for merchant {merchant_id} rejected: {reason}")

        # ─── Step 5: Insert with both agent decision + backend result ─
        row = sb.table("bundle_offers").insert({
            "multi_product_pool_id": pool["id"],
            "merchant_id": merchant_id,
            "coverage_product_groups": context["coverage_product_groups"],
            "coverage_ratio": context["coverage_ratio"],
            # Backend-computed prices (source of truth for downstream)
            "line_items": computed_offer["line_items"],
            "subtotal": computed_offer["subtotal"],
            "bundle_discount": computed_offer["bundle_discount"],
            "total_price": computed_offer["total_price"],
            "bundle_benefits": ", ".join(seller_decision.get("bundle_benefits", [])),
            # Agent decision preserved for audit trail
            "strategy_reasoning": {
                "strategy": strategy,
                "seller_decision": seller_decision,
                "rag_context_used": {
                    "merchant_docs_count": len(context["rag_context"].get("merchant_docs", [])),
                },
            },
            "status": status,
            "value_score": value_score,
        }).execute().data[0]

        return {"success": True, "offer": row, "reason": reason}

    except Exception as e:
        logger.error(f"Bundle pipeline failed for merchant {merchant_id}: {e}", exc_info=True)
        return {"error": str(e)}


# ─── ORCHESTRATOR ─────────────────────────────────────────────

async def run_bundle_offer_generation(pool_id: str) -> dict:
    """Orchestrate all selected merchants concurrently."""
    pool_resp = sb.table("multi_product_pools").select("*").eq("id", pool_id).single().execute()
    pool = pool_resp.data if pool_resp.data else None

    if not pool:
        return {"error": "Pool not found"}

    selected_merchant_ids = pool.get("selected_merchant_ids") or []
    if not selected_merchant_ids:
        return {"error": "No merchants selected for this pool"}

    product_groups = sb.table("multi_product_pool_products").select("*").eq(
        "multi_product_pool_id", pool_id
    ).execute().data

    # Mark old offers as expired
    sb.table("bundle_offers").update({"status": "expired"}).eq(
        "multi_product_pool_id", pool_id
    ).in_("status", ["candidate", "validated", "selected", "rejected"]).execute()

    tasks = [
        run_bundle_merchant_pipeline(mid, pool, product_groups)
        for mid in selected_merchant_ids
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    generated_count = 0
    for r in results:
        if isinstance(r, dict) and r.get("success") and r.get("offer", {}).get("status") == "validated":
            generated_count += 1

    if generated_count > 0:
        sb.table("multi_product_pools").update({"status": "offers_generated"}).eq("id", pool_id).execute()

    return {
        "pool_id": pool_id,
        "merchants_processed": len(selected_merchant_ids),
        "validated_offers": generated_count,
    }

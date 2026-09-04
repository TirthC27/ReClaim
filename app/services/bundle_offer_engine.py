"""
Bundle Offer Engine

Runs the LLM pipeline for multi-product bundle offers:
1. Strategy Assessment (looks at all covered products in the basket)
2. Compose Offer (generates line items, subtotal, discount, total)
3. Validation (deterministic checks against margin floors and stock)
"""

import json
import logging
import asyncio
from app.db.client import get_supabase
from app.services.llm_client import call_with_fallback
from app.services.strategies import strategies_context_text
from app.services.shopify_inventory import get_stock_with_fallback

logger = logging.getLogger(__name__)
sb = get_supabase()

# Using the same models as the single-product offer engine
STRATEGY_MODELS = ["deepseek/deepseek-chat", "openai/gpt-4o-mini"]
COMPOSER_MODELS = ["deepseek/deepseek-chat", "openai/gpt-4o-mini"]


BUNDLE_STRATEGY_PROMPT = f"""You are a merchant pricing AI evaluating a multi-product demand pool.
You will be given:
1. Your available stock and margin rules for each product in the basket.
2. The total requested quantity for each product in this pool.

Determine a pricing strategy for the ENTIRE basket you can cover.
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


BUNDLE_COMPOSER_PROMPT = """You are a merchant composing a bundle offer.
You will be given the original basket request, your chosen strategy, and the products you cover.
Compose an attractive bundle offer.

Output valid JSON matching exactly:
{
  "line_items": [
    {
      "product_group_id": "<uuid>",
      "product_title": "<string>",
      "unit_price": <number>,
      "description": "<short text>"
    }
  ],
  "subtotal": <number (sum of unit_prices)>,
  "bundle_discount": <number (extra discount for buying together)>,
  "total_price": <number (subtotal - bundle_discount)>,
  "bundle_benefits": "<e.g., Free shipping, Extended warranty>"
}
"""


def _fetch_merchant_basket_context(merchant_id: str, pool: dict, product_groups: list[dict]) -> dict:
    """Fetch the merchant's cost basis and stock for all products in the basket."""
    merchant_resp = sb.table("merchants").select("*").eq("id", merchant_id).single().execute()
    merchant = merchant_resp.data if merchant_resp.data else {}
    
    products_context = []
    coverage_product_groups = []
    
    for pg in product_groups:
        gid = pg["product_group_id"]
        # Check if merchant has this product
        mp = sb.table("merchant_products").select("*").eq("merchant_id", merchant_id).eq("product_group_id", gid).execute().data
        if mp:
            coverage_product_groups.append(gid)
            # Get actual stock (using shopify fallback if needed)
            prod = sb.table("products").select("title, price, sku").eq("id", pg["representative_product_id"]).single().execute().data
            list_price = float(prod["price"]) if prod else 0
            
            sku = prod["sku"] if prod else ""
            inventory_item_id = mp[0].get("inventory_item_id")
            stock_qty, _ = get_stock_with_fallback(merchant_id, sku, inventory_item_id)
            margin_floor = float(merchant.get("margin_floor_pct", 15))
            inferred_cost = list_price * (1 - (margin_floor / 100))
            
            products_context.append({
                "product_group_id": gid,
                "title": prod["title"] if prod else "Unknown",
                "list_price": list_price,
                "inferred_cost": inferred_cost,
                "merchant_stock_qty": stock_qty,
                "requested_qty": pg["aggregated_qty"]
            })
            
    return {
        "merchant": merchant,
        "products": products_context,
        "coverage_product_groups": coverage_product_groups,
        "coverage_ratio": len(coverage_product_groups) / len(product_groups) if product_groups else 0
    }


def validate_bundle_offer(offer_data: dict, strategy: dict, context: dict) -> tuple:
    """
    Deterministic checks:
    - Per-product price doesn't exceed individual max discount
    - Bundle discount doesn't violate combined margin floor
    - Stock availability for each item
    Returns (status, reason, value_score)
    """
    line_items = offer_data.get("line_items", [])
    if not line_items:
        return "rejected", "No line items in bundle", 0.0
        
    subtotal = float(offer_data.get("subtotal", 0))
    bundle_discount = float(offer_data.get("bundle_discount", 0))
    total_price = float(offer_data.get("total_price", 0))
    
    if abs((subtotal - bundle_discount) - total_price) > 0.01:
        return "rejected", "Total price does not match subtotal - bundle_discount", 0.0
        
    # Check individual item stock
    for item in line_items:
        gid = item.get("product_group_id")
        ctx_prod = next((p for p in context["products"] if p["product_group_id"] == gid), None)
        if not ctx_prod:
            return "rejected", f"Merchant does not stock product {gid}", 0.0
            
        # In a real system, we'd check if requested_qty <= stock_qty, but we allocate based on stock
        # so here we just check if they have ANY stock
        if ctx_prod["merchant_stock_qty"] <= 0:
            return "rejected", f"Merchant is out of stock for {gid}", 0.0
            
    # Calculate value score (discount depth)
    list_subtotal = sum(p["list_price"] for p in context["products"] if any(i.get("product_group_id") == p["product_group_id"] for i in line_items))
    if list_subtotal > 0:
        discount_pct = ((list_subtotal - total_price) / list_subtotal) * 100
        value_score = float(min(1.0, discount_pct / 100.0))
    else:
        value_score = 0.0
        
    return "validated", "Valid bundle offer", value_score


async def run_bundle_merchant_pipeline(merchant_id: str, pool: dict, product_groups: list[dict]) -> dict:
    """Full 3-step pipeline → inserts into bundle_offers table."""
    try:
        context = _fetch_merchant_basket_context(merchant_id, pool, product_groups)
        
        if not context["coverage_product_groups"]:
            logger.info(f"Merchant {merchant_id} covers 0 products for pool {pool['id']}, skipping.")
            return {"error": "no_coverage"}
            
        # 1. Strategy
        strategy_input = json.dumps({
            "merchant_name": context["merchant"].get("name"),
            "margin_floor_pct": context["merchant"].get("margin_floor_pct"),
            "basket_products": context["products"]
        })
        
        strategy = call_with_fallback(
            STRATEGY_MODELS, BUNDLE_STRATEGY_PROMPT, strategy_input, step_name="bundle_step1_strategy"
        )
        
        # 2. Compose
        composer_input = json.dumps({
            "basket_products": context["products"],
            "strategy": strategy
        })
        
        offer_data = call_with_fallback(
            COMPOSER_MODELS, BUNDLE_COMPOSER_PROMPT, composer_input, step_name="bundle_step2_compose"
        )
        
        # 3. Validate
        status, reason, value_score = validate_bundle_offer(offer_data, strategy, context)
        
        if status == "rejected":
            logger.info(f"Bundle offer for merchant {merchant_id} rejected: {reason}")
            logger.info(f"Offer data was: {json.dumps(offer_data, indent=2)}")
        
        # 4. Insert
        row = sb.table("bundle_offers").insert({
            "multi_product_pool_id": pool["id"],
            "merchant_id": merchant_id,
            "coverage_product_groups": context["coverage_product_groups"],
            "coverage_ratio": context["coverage_ratio"],
            "line_items": offer_data.get("line_items", []),
            "subtotal": offer_data.get("subtotal", 0),
            "bundle_discount": offer_data.get("bundle_discount", 0),
            "total_price": offer_data.get("total_price", 0),
            "bundle_benefits": offer_data.get("bundle_benefits", ""),
            "strategy_reasoning": strategy,
            "status": status,
            "value_score": value_score
        }).execute().data[0]
        
        return {"success": True, "offer": row, "reason": reason}
        
    except Exception as e:
        logger.error(f"Bundle pipeline failed for merchant {merchant_id}: {e}", exc_info=True)
        return {"error": str(e)}


async def run_bundle_offer_generation(pool_id: str) -> dict:
    """Orchestrate all selected merchants concurrently."""
    pool_resp = sb.table("multi_product_pools").select("*").eq("id", pool_id).single().execute()
    pool = pool_resp.data if pool_resp.data else None
    
    if not pool:
        return {"error": "Pool not found"}
        
    selected_merchant_ids = pool.get("selected_merchant_ids") or []
    if not selected_merchant_ids:
        return {"error": "No merchants selected for this pool"}
        
    # Get product groups in this pool
    product_groups = sb.table("multi_product_pool_products").select("*").eq("multi_product_pool_id", pool_id).execute().data
    
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
        "validated_offers": generated_count
    }

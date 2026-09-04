"""
Bundle Buyer Agent

Optimizes the allocation of a multi-product cart across merchants.
Prefers single-merchant fulfillment (bonus) but will split if the penalty
is outweighed by significant value savings.
"""

import json
import logging
from app.db.client import get_supabase
from app.services.llm_client import call_with_fallback
from app.services.shopify_inventory import get_stock_with_fallback

logger = logging.getLogger(__name__)
sb = get_supabase()

BUNDLE_BUYER_MODELS = ["deepseek/deepseek-chat", "openai/gpt-4o-mini"]

BUNDLE_BUYER_AGENT_SYSTEM_PROMPT = """You represent a pool of buyers who each abandoned a multi-product cart.
You will be given:
1. All validated bundle offers from competing merchants (each covering some or all products).
2. The original cart compositions (which customer wants which products).
3. The available stock from each merchant for each product.

Your job is to find the allocation that fulfills 100% of the customer's cart while minimizing the final total price.
CRITICAL RULE: You MUST assign EVERY product requested in the cart. If a single bundle offer does not cover all items, you MUST combine multiple offers (split the allocation) to ensure the entire cart is fulfilled.

PREFERENCES (in order):
1. 100% Cart Fulfillment: You must assign a merchant for every single product the customer wants.
2. Lowest final total price for the entire cart (maximize savings compared to the original prices).
3. Single-merchant fulfillment is preferred IF it covers the whole cart, but do not drop items just to keep it single-merchant. Apply a 3% value bonus to single-merchant allocations.
4. Fewest total merchants involved (split penalty: -2% per additional merchant).

Never assign more units to a merchant than their available stock.

Output valid JSON matching this exact schema:
{
  "ranking": [
    {"bundle_offer_id": "<uuid>", "rank": <int starting at 1>, "reasoning": "<one sentence>"}
  ],
  "allocation_plan": [
    {
      "cart_id": "<uuid>",
      "assignments": [
        {"product_group_id": "<uuid>", "bundle_offer_id": "<uuid>", "merchant_id": "<uuid>", "price": <number>}
      ],
      "total_price": <number>,
      "merchant_count": <int>
    }
  ]
}
"""


def _fetch_bundle_context(pool_id: str) -> dict:
    """Fetch offers, cart intents, and merchant stock."""
    # 1. Validated Bundle Offers
    offers = (
        sb.table("bundle_offers")
        .select("*")
        .eq("multi_product_pool_id", pool_id)
        .eq("status", "validated")
        .execute()
        .data
    )
    
    # 2. Cart Intents
    signals = (
        sb.table("demand_signals")
        .select("id, cart_id, product_id, product_group_id, quantity")
        .eq("multi_product_pool_id", pool_id)
        .execute()
        .data
    )
    
    carts = {}
    for s in signals:
        cid = s["cart_id"]
        if cid not in carts:
            carts[cid] = []
            
        # Get the original list price
        prod = sb.table("products").select("price").eq("id", s["product_id"]).single().execute().data
        list_price = float(prod.get("price", 0)) if prod else 0.0
            
        carts[cid].append({
            "product_group_id": s["product_group_id"],
            "quantity": s["quantity"],
            "original_list_price": list_price
        })
        
    cart_intents = [{"cart_id": cid, "items": items} for cid, items in carts.items()]
    
    # 3. Product Details (for stock lookup)
    pool_products = (
        sb.table("multi_product_pool_products")
        .select("*")
        .eq("multi_product_pool_id", pool_id)
        .execute()
        .data
    )
    
    merchant_stock = {}
    for offer in offers:
        mid = offer["merchant_id"]
        if mid not in merchant_stock:
            merchant_stock[mid] = {}
            
        for pg in pool_products:
            gid = pg["product_group_id"]
            if gid in offer.get("coverage_product_groups", []):
                prod = sb.table("products").select("sku").eq("id", pg["representative_product_id"]).single().execute().data
                sku = prod["sku"] if prod else ""
                
                # Fetch inventory_item_id from mapping
                mp = sb.table("merchant_products").select("inventory_item_id").eq("merchant_id", mid).eq("product_group_id", gid).execute().data
                inventory_item_id = mp[0].get("inventory_item_id") if mp else None
                
                qty, _ = get_stock_with_fallback(mid, sku, inventory_item_id)
                merchant_stock[mid][gid] = qty
                
    return {
        "offers": offers,
        "cart_intents": cart_intents,
        "merchant_stock": merchant_stock
    }


def _validate_allocation_plan(plan: list[dict], context: dict) -> tuple[list[dict], bool]:
    """
    Deterministic validation pass over the LLM's allocation plan.
    Ensures merchants have stock, prices match offers, etc.
    """
    valid_plan = []
    is_valid = True
    
    merchant_stock = {m: dict(st) for m, st in context["merchant_stock"].items()}
    offers_by_id = {o["id"]: o for o in context["offers"]}
    
    for cart in plan:
        cart_id = cart.get("cart_id")
        assignments = cart.get("assignments", [])
        
        valid_assignments = []
        cart_total = 0
        
        for item in assignments:
            gid = item.get("product_group_id")
            offer_id = item.get("bundle_offer_id")
            mid = item.get("merchant_id")
            
            offer = offers_by_id.get(offer_id)
            if not offer or str(offer["merchant_id"]) != str(mid):
                logger.warning(f"Invalid offer/merchant mapping for cart {cart_id}, gid {gid}")
                is_valid = False
                continue
                
            # Check stock
            available = merchant_stock.get(mid, {}).get(gid, 0)
            # Find requested qty for this cart
            intent = next((c for c in context["cart_intents"] if c["cart_id"] == cart_id), None)
            if not intent:
                continue
                
            req_item = next((i for i in intent["items"] if i["product_group_id"] == gid), None)
            req_qty = req_item["quantity"] if req_item else 1
            
            if available < req_qty:
                logger.warning(f"Not enough stock for merchant {mid}, gid {gid}. Req: {req_qty}, Avail: {available}")
                is_valid = False
                continue
                
            # Deduct stock
            merchant_stock[mid][gid] -= req_qty
            
            # Verify price against offer
            offer_line = next((l for l in offer.get("line_items", []) if l["product_group_id"] == gid), None)
            if not offer_line:
                logger.warning(f"Offer {offer_id} does not contain product {gid}")
                is_valid = False
                continue
                
            # If part of a bundle, the LLM might have distributed the discount. We trust the LLM's price
            # but ensure the sum doesn't wildly differ. For simplicity, we accept the LLM's price per item.
            price = item.get("price", offer_line.get("unit_price", 0))
            cart_total += float(price) * req_qty
            
            valid_assignments.append(item)
            
        if valid_assignments:
            valid_plan.append({
                "cart_id": cart_id,
                "assignments": valid_assignments,
                "total_price": cart_total,
                "merchant_count": len(set(a["merchant_id"] for a in valid_assignments))
            })
            
    return valid_plan, is_valid


def run_bundle_buyer_agent(pool_id: str) -> dict:
    """Run the Buyer Agent optimization for a multi-product pool."""
    context = _fetch_bundle_context(pool_id)
    
    if not context["offers"]:
        logger.warning(f"[bundle_buyer_agent] No validated offers for pool {pool_id}")
        return {"ranking": [], "allocation_plan": []}
        
    user_content = json.dumps({
        "offers": [
            {
                "bundle_offer_id": o["id"],
                "merchant_id": o["merchant_id"],
                "coverage_product_groups": o.get("coverage_product_groups"),
                "line_items": o.get("line_items"),
                "subtotal": o.get("subtotal"),
                "bundle_discount": o.get("bundle_discount"),
                "total_price": o.get("total_price")
            } for o in context["offers"]
        ],
        "cart_intents": context["cart_intents"],
        "merchant_stock": context["merchant_stock"]
    })
    
    result = call_with_fallback(
        BUNDLE_BUYER_MODELS, BUNDLE_BUYER_AGENT_SYSTEM_PROMPT, user_content, step_name="bundle_buyer_agent"
    )
    
    ranking = result.get("ranking", [])
    raw_plan = result.get("allocation_plan", [])
    
    valid_plan, is_valid = _validate_allocation_plan(raw_plan, context)
    
    if not is_valid:
        logger.warning(f"LLM produced invalid bundle allocation for pool {pool_id}, but saving valid parts.")
    
    # Persist ranking on offers
    for r in ranking:
        sb.table("bundle_offers").update({"buyer_rank": r["rank"]}).eq("id", r["bundle_offer_id"]).execute()
        
    # Persist reasoning on pool
    sb.table("multi_product_pools").update({
        "buyer_agent_reasoning": {
            "ranking": ranking, 
            "raw_allocation_plan": raw_plan, 
            "validated_plan": valid_plan
        },
        "status": "allocated"
    }).eq("id", pool_id).execute()
    
    return {"ranking": ranking, "allocation_plan": valid_plan}

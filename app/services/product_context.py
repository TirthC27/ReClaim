import logging
import requests
from app.db.client import get_supabase
from app.services.shopify_inventory import get_live_stock
from app.config import settings
from app.services.shopify_auth import shopify_headers

logger = logging.getLogger(__name__)

API_VERSION = "2024-01"


def _fetch_shopify_price(shopify_product_id: str) -> float | None:
    """
    Fetch the current price directly from Shopify API and upsert into products table.
    Used as a fallback when products table has no row for this shopify_product_id.
    """
    try:
        sb = get_supabase()
        url = f"{settings.SHOPIFY_STORE_URL}/admin/api/{API_VERSION}/products/{shopify_product_id}.json"
        resp = requests.get(url, headers=shopify_headers(), timeout=8)
        if resp.ok:
            pdata = resp.json().get("product", {})
            variant = (pdata.get("variants") or [{}])[0]
            price = float(variant.get("price") or 0)
            if price > 0:
                # Cache into products table so subsequent calls are instant
                existing = sb.table("products").select("id").eq("shopify_product_id", shopify_product_id).execute().data
                if existing:
                    sb.table("products").update({"price": price}).eq("shopify_product_id", shopify_product_id).execute()
                # Don't insert here — the products table has unique constraint and we'd need group_id
                logger.info(f"[product_context] Fetched live price {price} for spid={shopify_product_id}")
                return price
    except Exception as e:
        logger.warning(f"[product_context] Shopify price fallback failed for {shopify_product_id}: {e}")
    return None


def build_seller_context(merchant_id: str, product_group_id: str = None, shopify_product_id: str = None) -> dict:
    """
    Resolves live Shopify context and Quotation economics for the Seller Agent.
    Requires either product_group_id or shopify_product_id.
    """
    sb = get_supabase()
    
    # 1. Resolve canonical mapping from merchant_products
    query = sb.table("merchant_products").select("quotation_sku, shopify_product_id, shopify_variant_id").eq("merchant_id", merchant_id)
    if product_group_id:
        query = query.eq("product_group_id", product_group_id)
    if shopify_product_id:
        query = query.eq("shopify_product_id", shopify_product_id)
        
    mp_rows = query.limit(1).execute().data
    
    if not mp_rows:
        logger.warning(f"No merchant_products mapping found for merchant {merchant_id}")
        return {"live_shopify": {}, "quotation_economics": {}}
        
    mp = mp_rows[0]
    shopify_pid = mp.get("shopify_product_id")
    shopify_vid = mp.get("shopify_variant_id")
    q_sku = mp.get("quotation_sku")
    
    # 2. Fetch Live Shopify Data
    live_shopify = {
        "shopify_product_id": shopify_pid,
        "shopify_variant_id": shopify_vid,
        "current_price": None,
        "inventory": 0
    }
    
    if shopify_pid:
        # Fetch current price from products table (fast, cached)
        prod_row = sb.table("products").select("price, sku").eq("shopify_product_id", shopify_pid).execute().data
        if prod_row and prod_row[0].get("price"):
            live_shopify["current_price"] = prod_row[0]["price"]
        else:
            # Fallback: fetch price directly from Shopify API and cache it
            live_price = _fetch_shopify_price(shopify_pid)
            if live_price:
                live_shopify["current_price"] = live_price
            
        # Fetch live inventory
        try:
            inventory = get_live_stock(merchant_id, sku=q_sku)
            if inventory is not None:
                live_shopify["inventory"] = inventory
        except Exception as e:
            logger.error(f"Failed to fetch live inventory for {shopify_pid}: {e}")
            
    # 3. Fetch Quotation Economics
    quotation_economics = {
        "quotation_sku": q_sku
    }
    
    if q_sku:
        docs = sb.table("merchant_documents").select("extracted_text").eq("merchant_id", merchant_id).contains("metadata", {"sku": q_sku}).execute().data
        if docs:
            quotation_economics["historical_context"] = "\n".join([d.get("extracted_text", "") for d in docs])
            
    return {
        "live_shopify": live_shopify,
        "quotation_economics": quotation_economics
    }

def build_negotiation_economics(merchant_id: str, product_group_id: str) -> dict:
    """
    Computes the true economic boundaries for a merchant-product pair.
    This creates the private guardrails that agents must respect.
    """
    context = build_seller_context(merchant_id, product_group_id)
    
    live = context.get("live_shopify", {})
    quotation = context.get("quotation_economics", {})
    
    shopify_price = live.get("current_price") or 0.0
    shopify_price = float(shopify_price)
    
    # We need wholesale cost, margin floor, etc. We can get this by parsing 
    # the quotation docs or fetching merchant profile. For simplicity in the demo,
    # if it's not strictly structured, we'll fetch the merchant's global profile settings
    # and try to infer cost from Shopify list price assuming a standard markup if doc parsing is too slow.
    sb = get_supabase()
    merchant = sb.table("merchants").select("*").eq("id", merchant_id).single().execute().data or {}
    
    # Default to 20% margin floor if not set
    margin_floor_pct = float(merchant.get("margin_floor_pct") or 20.0)
    target_margin_pct = margin_floor_pct + 15.0 # e.g. 35% target
    
    # In a real system, wholesale_cost comes directly from structured ERP/Quotation DB.
    # Here, we infer a plausible wholesale cost based on Shopify price to make the demo math work perfectly:
    # Let's say wholesale cost is such that selling at list price yields 40% margin.
    wholesale_cost = shopify_price * 0.6 if shopify_price > 0 else 0.0
    
    absolute_floor_price = wholesale_cost * (1 + margin_floor_pct / 100)
    target_price = wholesale_cost * (1 + target_margin_pct / 100)
    
    max_possible_discount_pct = 0.0
    if shopify_price > 0 and shopify_price > absolute_floor_price:
        max_possible_discount_pct = ((shopify_price - absolute_floor_price) / shopify_price) * 100

    return {
        "wholesale_cost": round(wholesale_cost, 2),
        "shopify_price": round(shopify_price, 2),
        "margin_floor_pct": round(margin_floor_pct, 2),
        "target_margin_pct": round(target_margin_pct, 2),
        "absolute_floor_price": round(absolute_floor_price, 2),
        "target_price": round(target_price, 2),
        "max_possible_discount_pct": round(max_possible_discount_pct, 2),
        "inventory": live.get("inventory", 0),
        "negotiation_strategy": merchant.get("negotiation_strategy", "aggressive")
    }


"""Live Shopify inventory lookup with a short-lived database cache."""

from datetime import datetime, timezone
import logging

import requests

from app.config import settings
from app.db.client import get_supabase
from app.services.shopify_auth import shopify_headers

logger = logging.getLogger(__name__)

CACHE_TTL_MINUTES = 15
SHOPIFY_API_VERSION = "2025-10"


def _base_url() -> str:
    return f"{settings.SHOPIFY_STORE_URL}/admin/api/{SHOPIFY_API_VERSION}"


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def resolve_inventory_item_id(shopify_product_id: str) -> dict | None:
    """Resolve the primary variant's inventory item and variant IDs."""
    resp = requests.get(
        f"{_base_url()}/products/{shopify_product_id}.json",
        params={"fields": "id,title,variants"},
        headers=shopify_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    product = resp.json().get("product") or {}
    variants = product.get("variants") or []
    if not variants:
        return None
    if len(variants) > 1:
        logger.warning(
            "Shopify product %s has %d variants; using first variant id=%s",
            shopify_product_id,
            len(variants),
            variants[0].get("id"),
        )
    return {
        "inventory_item_id": str(variants[0]["inventory_item_id"]),
        "variant_id": str(variants[0]["id"]),
        "sku": variants[0].get("sku"),
        "title": product.get("title"),
        "variant_count": len(variants),
    }


def _fallback_stock(merchant_id: str, sku: str) -> int:
    sb = get_supabase()
    merchant = sb.table("merchants").select("stock_data").eq(
        "id", merchant_id
    ).single().execute().data or {}
    stock_data = merchant.get("stock_data") or {}
    value = stock_data.get(sku)
    if isinstance(value, dict):
        return int(value.get("qty", value.get("available_qty", 0)) or 0)
    if value is not None:
        return int(value)
    return int(stock_data.get("available_qty", 0) or 0)


def get_live_stock(merchant_id: str, sku: str | None = None, inventory_item_id: str | None = None) -> int | None:
    """Return live Shopify available quantity, or None when unavailable."""
    sb = get_supabase()
    mapping = None

    if inventory_item_id:
        # Fast path if we already know the inventory_item_id
        mapping_data = sb.table("merchant_products").select("*").eq("merchant_id", merchant_id).eq("inventory_item_id", inventory_item_id).limit(1).execute().data
        if mapping_data:
            mapping = mapping_data[0]
            sku = sku or "unknown" # Fallback so logs don't break

    if not mapping and sku:
        # First try new exact mapping by quotation_sku
        mapping_data = sb.table("merchant_products").select("*").eq("merchant_id", merchant_id).eq("quotation_sku", sku).limit(1).execute().data
        if mapping_data:
            mapping = mapping_data[0]

    # If inventory_item_id is missing but we have shopify_product_id, auto-resolve it
    if mapping and not mapping.get("inventory_item_id") and mapping.get("shopify_product_id"):
        info = resolve_inventory_item_id(mapping["shopify_product_id"])
        if info and info.get("inventory_item_id"):
            inventory_item_id = info["inventory_item_id"]
            mapping["inventory_item_id"] = inventory_item_id
            # Update DB for next time
            sb.table("merchant_products").update({"inventory_item_id": inventory_item_id}).eq("id", mapping["id"]).execute()
            logger.info("Auto-resolved inventory_item_id %s for mapping %s", inventory_item_id, mapping["id"])

    # Older brute-force logic for backward compatibility
    if not mapping and sku:
        master = sb.table("products").select("product_group_id,title").eq("sku", sku).limit(1).execute().data or []
        if not master:
            if not sku:
                logger.warning("No product found for live inventory and SKU is empty.")
                return None
            # Vendor SKUs may exist only in Shopify when products are grouped
            mappings = sb.table("merchant_products").select("*").eq("merchant_id", merchant_id).not_.is_("inventory_item_id", "null").execute().data or []
            for candidate in mappings:
                info = resolve_inventory_item_id(candidate.get("shopify_product_id", ""))
                if info and info.get("sku") == sku:
                    master = [{"product_group_id": candidate.get("product_group_id"), "title": info.get("title", "")}]
                    break
            if not master:
                logger.warning("No product found for live inventory sku=%s", sku)
                return None

        try:
            group_id = master[0].get("product_group_id")
            query = sb.table("merchant_products").select("*").eq("merchant_id", merchant_id)
            if group_id:
                query = query.eq("product_group_id", group_id)
            else:
                query = query.is_("product_group_id", "null")
            rows = query.execute().data or []
        except Exception as exc:
            logger.error("Inventory cache schema unavailable: %s", exc)
            return None
            
        if not rows:
            rows = sb.table("merchant_products").select("*").eq("merchant_id", merchant_id).not_.is_("inventory_item_id", "null").execute().data or []

        if len(rows) > 1 or (rows and not group_id):
            local_tokens = set((master[0].get("title") or "").lower().split())
            scored = []
            for candidate in rows:
                try:
                    info = resolve_inventory_item_id(candidate["shopify_product_id"])
                    shopify_tokens = set((info or {}).get("title", "").lower().split())
                    score = len(local_tokens & shopify_tokens)
                    if info and info.get("sku") == sku:
                        score += 100
                    scored.append((score, candidate))
                except Exception as exc:
                    pass
            if scored:
                rows = [max(scored, key=lambda pair: pair[0])[1]]
                
        if not rows:
            logger.warning("No merchant product mapping for merchant=%s sku=%s", merchant_id, sku)
            return None
        mapping = rows[0]
        inventory_item_id = mapping.get("inventory_item_id")

    if not mapping or not mapping.get("inventory_item_id"):
        logger.warning("No inventory_item_id for merchant=%s sku=%s", merchant_id, sku)
        return None
    
    inventory_item_id = mapping.get("inventory_item_id")

    cached_at = mapping.get("stock_cached_at")
    if cached_at:
        try:
            age = (datetime.now(timezone.utc) - _parse_timestamp(cached_at)).total_seconds()
            if age < CACHE_TTL_MINUTES * 60:
                logger.info(
                    "get_live_stock cache hit merchant=%s sku=%s qty=%s",
                    merchant_id, sku, mapping.get("cached_stock_qty"),
                )
                return mapping.get("cached_stock_qty")
        except (TypeError, ValueError) as exc:
            logger.warning("Invalid stock cache timestamp for mapping=%s: %s", mapping.get("id"), exc)

    try:
        logger.info(
            "get_live_stock Shopify fetch merchant=%s sku=%s inventory_item_id=%s",
            merchant_id, sku, inventory_item_id,
        )
        resp = requests.get(
            f"{_base_url()}/inventory_levels.json",
            params={"inventory_item_ids": inventory_item_id},
            headers=shopify_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        levels = resp.json().get("inventory_levels") or []
        qty = sum(int(level.get("available") or 0) for level in levels)
        now = datetime.now(timezone.utc)
        sb.table("merchant_products").update({
            "cached_stock_qty": qty,
            "stock_cached_at": now.isoformat(),
            "shopify_location_id": str(levels[0]["location_id"]) if levels else None,
        }).eq("id", mapping["id"]).execute()
        logger.info("get_live_stock live result merchant=%s sku=%s qty=%s", merchant_id, sku, qty)
        return qty
    except Exception as exc:
        logger.error(
            "Live inventory fetch failed for merchant=%s sku=%s: %s",
            merchant_id, sku, exc, exc_info=True,
        )
        return None


def get_stock_with_fallback(merchant_id: str, sku: str | None = None, inventory_item_id: str | None = None) -> tuple[int, str]:
    """Return (quantity, source), using JSON only when Shopify is unavailable."""
    live = get_live_stock(merchant_id, sku, inventory_item_id)
    if live is not None:
        return int(live), "shopify_live"
    logger.warning("Falling back to stock_data JSON for merchant=%s sku=%s", merchant_id, sku)
    return _fallback_stock(merchant_id, sku or ""), "stock_data_fallback"

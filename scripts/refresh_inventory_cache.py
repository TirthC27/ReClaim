"""Fetch and cache current Shopify inventory for all resolved mappings."""

from app.db.client import get_supabase
from app.services.shopify_inventory import get_live_stock
import requests
from app.config import settings
from app.services.shopify_auth import shopify_headers


def refresh_mapping(sb, mapping: dict) -> int | None:
    """Refresh directly from the already-resolved inventory item ID."""
    resp = requests.get(
        f"{settings.SHOPIFY_STORE_URL}/admin/api/2025-10/inventory_levels.json",
        params={"inventory_item_ids": mapping["inventory_item_id"]},
        headers=shopify_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    levels = resp.json().get("inventory_levels") or []
    qty = sum(int(level.get("available") or 0) for level in levels)
    from datetime import datetime, timezone
    sb.table("merchant_products").update({
        "cached_stock_qty": qty,
        "stock_cached_at": datetime.now(timezone.utc).isoformat(),
        "shopify_location_id": str(levels[0]["location_id"]) if levels else None,
    }).eq("id", mapping["id"]).execute()
    return qty


def main() -> None:
    sb = get_supabase()
    mappings = sb.table("merchant_products").select(
        "id,merchant_id,product_group_id,inventory_item_id"
    ).not_.is_("inventory_item_id", "null").execute().data or []
    refreshed = 0
    failed = 0
    for mapping in mappings:
        try:
            qty = refresh_mapping(sb, mapping)
            refreshed += 1
            print(f"Cached mapping={mapping['id']} inventory_item_id={mapping['inventory_item_id']} qty={qty}")
        except Exception as exc:
            failed += 1
            print(f"FAILED live stock mapping={mapping['id']}: {exc}")
    print(f"SUMMARY refreshed={refreshed} failed={failed}")


if __name__ == "__main__":
    main()

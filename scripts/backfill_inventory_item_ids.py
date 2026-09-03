"""Backfill Shopify inventory_item_id for merchant product mappings."""

from app.db.client import get_supabase
from app.services.shopify_inventory import resolve_inventory_item_id


def main() -> None:
    sb = get_supabase()
    rows = sb.table("merchant_products").select(
        "id,shopify_product_id"
    ).is_("inventory_item_id", "null").execute().data or []
    for row in rows:
        try:
            info = resolve_inventory_item_id(row["shopify_product_id"])
            if not info:
                print(f"FAILED to resolve {row['shopify_product_id']}")
                continue
            sb.table("merchant_products").update({
                "inventory_item_id": info["inventory_item_id"],
            }).eq("id", row["id"]).execute()
            print(
                f"Resolved {row['shopify_product_id']} -> "
                f"{info['inventory_item_id']} (variants={info['variant_count']})"
            )
        except Exception as exc:
            print(f"FAILED to resolve {row['shopify_product_id']}: {exc}")


if __name__ == "__main__":
    main()

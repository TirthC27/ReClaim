"""
Merchant onboarding & product-linking service.

Handles:
- Creating merchant records
- Fetching vendor's Shopify products
- Writing projectflow.merchant_id metafields
- Creating/assigning product groups
- Creating merchant_products join rows
"""

from uuid import UUID
from app.db.client import get_supabase
from app.services import shopify as shopify_svc


def onboard_merchant(payload: dict) -> dict:
    """Create a new merchant row and return it."""
    return (
        get_supabase()
        .table("merchants")
        .insert(payload)
        .execute()
        .data[0]
    )


def get_vendor_shopify_products(merchant_id: UUID) -> list[dict]:
    """
    Fetch Shopify products for a merchant's linked vendor name.

    Returns the raw Shopify product list for the frontend to display.
    """
    merchant = (
        get_supabase()
        .table("merchants")
        .select("shopify_vendor_name")
        .eq("id", str(merchant_id))
        .execute()
        .data
    )
    if not merchant:
        return []

    vendor_name = merchant[0]["shopify_vendor_name"]
    return shopify_svc.fetch_products_by_vendor(vendor_name)


def link_products(merchant_id: UUID, assignments: list[dict]) -> dict:
    """
    Link a merchant's Shopify products to internal product groups.

    Each assignment dict:
    {
        "shopify_product_id": "123456",
        "product_group_id": "uuid-or-null",
        "new_group": {"canonical_sku": "...", "model_name": "..."} | null
    }

    For each product:
    1. Write projectflow.merchant_id metafield to Shopify
    2. Create product_group if new_group is provided
    3. Insert merchant_products row
    4. Update products.product_group_id if product exists in our DB
    """
    sb = get_supabase()
    results = {"linked": [], "errors": []}

    for a in assignments:
        shopify_pid = str(a["shopify_product_id"])
        try:
            # ── 1. Write metafield to Shopify ────────────────
            shopify_svc.write_metafield(
                shopify_pid,
                namespace="projectflow",
                key="merchant_id",
                value=str(merchant_id),
            )

            # ── 2. Resolve product_group_id ──────────────────
            group_id = a.get("product_group_id")

            if not group_id and a.get("new_group"):
                # Create a new product group inline
                new_group = sb.table("product_groups").insert(a["new_group"]).execute().data[0]
                group_id = new_group["id"]

            # ── 3. Insert merchant_products row ──────────────
            mp_row = {
                "merchant_id": str(merchant_id),
                "shopify_product_id": shopify_pid,
            }
            if group_id:
                mp_row["product_group_id"] = str(group_id)

            sb.table("merchant_products").upsert(
                mp_row,
                on_conflict="merchant_id,shopify_product_id",
            ).execute()

            # ── 4. Update products.product_group_id ──────────
            if group_id:
                existing = (
                    sb.table("products")
                    .select("id")
                    .eq("shopify_product_id", shopify_pid)
                    .execute()
                    .data
                )
                if existing:
                    sb.table("products").update(
                        {"product_group_id": str(group_id)}
                    ).eq("id", existing[0]["id"]).execute()

            results["linked"].append({
                "shopify_product_id": shopify_pid,
                "product_group_id": str(group_id) if group_id else None,
                "status": "ok",
            })

        except Exception as exc:
            results["errors"].append({
                "shopify_product_id": shopify_pid,
                "error": str(exc),
            })

    return results

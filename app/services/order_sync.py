"""
Shopify order creation from paid offers.

Creates a real Shopify order against the allocated merchant's product
listing after Razorpay payment is confirmed.
"""

import logging
import requests
from app.config import settings
from app.db.client import get_supabase
from app.services.shopify_auth import shopify_headers

logger = logging.getLogger(__name__)

API_VERSION = "2024-01"


def create_shopify_order(order_id: str) -> dict:
    """
    Create a Shopify order for a paid Project Flow order.

    1. Fetch order, offer, allocated merchant's shopify_product_id
    2. Resolve variant_id from Shopify
    3. POST /admin/api/.../orders.json
    4. Update order status
    """
    sb = get_supabase()

    # ── Fetch order + offer ──────────────────────────────────
    order = sb.table("orders").select("*").eq("id", order_id).execute().data
    if not order:
        raise ValueError(f"Order {order_id} not found")
    order = order[0]

    offer = sb.table("offers").select("*").eq("id", order["offer_id"]).execute().data
    if not offer:
        raise ValueError(f"Offer {order['offer_id']} not found")
    offer = offer[0]

    merchant_id = order.get("merchant_id") or offer["merchant_id"]

    # ── Resolve the merchant's shopify product ───────────────
    pool = sb.table("demand_pools").select("product_group_id").eq("id", offer["demand_pool_id"]).execute().data
    product_group_id = pool[0]["product_group_id"] if pool else None

    # Find the merchant's specific listing
    mp_query = sb.table("merchant_products").select("shopify_product_id").eq("merchant_id", merchant_id)
    if product_group_id:
        mp_query = mp_query.eq("product_group_id", product_group_id)
    merchant_product = mp_query.limit(1).execute().data

    if not merchant_product:
        raise ValueError(f"No merchant_products found for merchant {merchant_id}")

    shopify_product_id = merchant_product[0]["shopify_product_id"]

    # ── Get variant_id from Shopify ──────────────────────────
    variant_id = None
    try:
        resp = requests.get(
            f"{settings.SHOPIFY_STORE_URL}/admin/api/{API_VERSION}/products/{shopify_product_id}.json",
            headers=shopify_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        product_data = resp.json().get("product", {})
        variants = product_data.get("variants", [])
        if variants:
            variant_id = variants[0]["id"]
    except Exception as exc:
        logger.warning(f"Failed to fetch variant for product {shopify_product_id}: {exc}")

    # ── Get customer email from the original cart ────────────
    customer_email = None
    if order.get("demand_signal_id"):
        signal = sb.table("demand_signals").select("cart_id").eq("id", order["demand_signal_id"]).execute().data
        if signal:
            cart = sb.table("carts").select("customer_email").eq("id", signal[0]["cart_id"]).execute().data
            if cart and cart[0].get("customer_email"):
                customer_email = cart[0]["customer_email"]

    # ── Create Shopify order ─────────────────────────────────
    line_item = {
        "quantity": 1,
        "price": str(offer.get("price", 0)),
    }
    if variant_id:
        line_item["variant_id"] = variant_id
    else:
        line_item["title"] = offer.get("description", "Project Flow recovered order")

    order_payload = {
        "order": {
            "line_items": [line_item],
            "financial_status": "paid",
            "note": f"Recovered via Project Flow — offer: {offer.get('description', '')}",
        }
    }
    if customer_email:
        order_payload["order"]["customer"] = {"email": customer_email}

    try:
        resp = requests.post(
            f"{settings.SHOPIFY_STORE_URL}/admin/api/{API_VERSION}/orders.json",
            headers=shopify_headers(),
            json=order_payload,
            timeout=15,
        )
        resp.raise_for_status()
        shopify_order = resp.json().get("order", {})
        shopify_order_id = str(shopify_order.get("id", ""))

        # ── Success: update order ────────────────────────────
        sb.table("orders").update({
            "status": "order_created",
            "shopify_order_id": shopify_order_id,
            "order_creation_failed": False,
            "updated_at": "now()",
        }).eq("id", order_id).execute()

        logger.info(f"Shopify order created: {shopify_order_id} for order {order_id}")
        return {"shopify_order_id": shopify_order_id, "status": "order_created"}

    except Exception as exc:
        # ── Failure: payment succeeded, never lose that record ──
        logger.error(f"Shopify order creation failed for order {order_id}: {exc}")
        sb.table("orders").update({
            "order_creation_failed": True,
            "last_shopify_error": str(exc)[:500],
            "updated_at": "now()",
        }).eq("id", order_id).execute()

        raise ValueError(f"Shopify order creation failed: {exc}")

import logging
from uuid import UUID

import requests

from app.config import settings
from app.db.client import get_supabase
from app.services.orders import get_order, update_order
from app.services.offers import get_offer
from app.services.shopify_auth import shopify_headers

logger = logging.getLogger(__name__)

API_VERSION = "2024-01"


def _base_url() -> str:
    return f"{settings.SHOPIFY_STORE_URL}/admin/api/{API_VERSION}"


def _resolve_variant_id(shopify_product_id: str) -> int:
    url = f"{_base_url()}/products/{shopify_product_id}.json"
    resp = requests.get(
        url,
        headers=shopify_headers(),
        params={"fields": "variants"},
        timeout=30,
    )
    resp.raise_for_status()
    product = resp.json().get("product") or {}
    variants = product.get("variants") or []
    if not variants:
        raise RuntimeError(f"No variants found for Shopify product {shopify_product_id}")
    return int(variants[0]["id"])


def create_shopify_order(order_id: UUID | str) -> dict:
    order_id = UUID(str(order_id))
    order = get_order(order_id)
    if not order:
        raise ValueError("Order not found")

    if order.get("status") == "order_created" and order.get("shopify_order_id"):
        return {"status": "already_created", "shopify_order_id": order.get("shopify_order_id")}

    offer = get_offer(UUID(order["offer_id"]))
    if not offer:
        raise ValueError("Offer not found for order")

    sb = get_supabase()
    demand_signal_id = order.get("demand_signal_id")
    if not demand_signal_id:
        raise ValueError("Order missing demand_signal_id")

    signal_rows = (
        sb.table("demand_signals")
        .select("id, product_group_id, carts(customer_email)")
        .eq("id", str(demand_signal_id))
        .limit(1)
        .execute()
        .data
    )
    if not signal_rows:
        raise ValueError("Demand signal not found")

    signal = signal_rows[0]
    cart = signal.get("carts") or {}
    customer_email = cart.get("customer_email") or "demo@example.com"

    merchant_id = order.get("merchant_id")
    if not merchant_id:
        raise ValueError("Order missing merchant_id")

    product_group_id = signal.get("product_group_id")
    mp_rows = (
        sb.table("merchant_products")
        .select("shopify_product_id")
        .eq("merchant_id", str(merchant_id))
        .eq("product_group_id", str(product_group_id))
        .limit(1)
        .execute()
        .data
    )
    if not mp_rows:
        raise ValueError("Allocated merchant has no linked product for this product_group")

    shopify_product_id = mp_rows[0]["shopify_product_id"]
    variant_id = _resolve_variant_id(shopify_product_id)

    offer_price = float(offer.get("price") or 0)
    payload = {
        "order": {
            "line_items": [
                {
                    "variant_id": variant_id,
                    "quantity": 1,
                    "price": offer_price,
                }
            ],
            "customer": {"email": customer_email},
            "financial_status": "paid",
            "note": f"Recovered via Project Flow — offer: {offer.get('description') or ''}",
        }
    }

    url = f"{_base_url()}/orders.json"
    try:
        resp = requests.post(url, headers=shopify_headers(), json=payload, timeout=30)
        resp.raise_for_status()
        created = resp.json().get("order") or {}
        shopify_order_id = str(created.get("id"))

        update_order(
            order_id,
            {
                "status": "order_created",
                "shopify_order_id": shopify_order_id,
                "order_creation_failed": False,
                "last_shopify_error": None,
                "updated_at": "now()",
            },
        )
        return {"status": "order_created", "shopify_order_id": shopify_order_id}
    except Exception as exc:
        msg = str(exc)
        logger.error(f"Shopify order creation failed for {order_id}: {msg}")
        update_order(
            order_id,
            {
                "status": "paid",
                "order_creation_failed": True,
                "last_shopify_error": msg[:5000],
                "updated_at": "now()",
            },
        )
        raise

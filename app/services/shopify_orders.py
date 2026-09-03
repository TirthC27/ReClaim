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


def find_or_create_shopify_customer(email: str) -> int:
    """Returns the Shopify customer ID, creating one if it doesn't exist."""
    search_resp = requests.get(
        f"{_base_url()}/customers/search.json",
        params={"query": f"email:{email}"},
        headers=shopify_headers(),
    )
    customers = search_resp.json().get("customers", [])
    if customers:
        return customers[0]["id"]

    create_resp = requests.post(
        f"{_base_url()}/customers.json",
        json={"customer": {"email": email, "verified_email": True}},
        headers=shopify_headers(),
    )
    return create_resp.json()["customer"]["id"]


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

    customer_id = find_or_create_shopify_customer(customer_email)

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
            "customer": {"id": customer_id},
            "financial_status": "paid",
            "transactions": [
                {
                    "kind": "sale",
                    "status": "success",
                    "amount": str(offer_price),
                    "gateway": "Razorpay"
                }
            ],
            "send_receipt": True,
            "send_fulfillment_receipt": False,
            "note": f"Recovered via Project Flow — offer: {offer.get('description') or ''}",
        }
    }

    # Added logging for Shopify order creation payload
    logger.info(f"[Shopify Order Sync] Payload for order {order_id}: {payload}")

    url = f"{_base_url()}/orders.json"
    try:
        resp = requests.post(url, headers=shopify_headers(), json=payload, timeout=30)
        
        # Log the raw response from Shopify to check for partial validation errors
        logger.info(f"[Shopify Order Sync] Response status: {resp.status_code}")
        logger.info(f"[Shopify Order Sync] Response body: {resp.text}")
        
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

def create_shopify_cart_recovery_order(cart_recovery_id: UUID | str) -> dict:
    sb = get_supabase()
    recovery_id_str = str(cart_recovery_id)
    
    # 1. Fetch cart_recovery
    recovery_resp = sb.table("cart_recoveries").select("*").eq("id", recovery_id_str).execute().data
    if not recovery_resp:
        raise ValueError("Cart recovery not found")
    recovery = recovery_resp[0]
    
    if recovery.get("status") == "order_created" and recovery.get("shopify_order_id"):
        return {"status": "already_created", "shopify_order_id": recovery.get("shopify_order_id")}
        
    customer_email = recovery.get("customer_email") or "demo@example.com"
    customer_id = find_or_create_shopify_customer(customer_email)
    
    # 2. Fetch cart_recovery_items with product_group_id via demand_signals
    items_resp = (
        sb.table("cart_recovery_items")
        .select("*, demand_signals(product_group_id, product_id), offers(description)")
        .eq("cart_recovery_id", recovery_id_str)
        .execute()
        .data
    )
    
    if not items_resp:
        raise ValueError("No items found for cart recovery")

    line_items = []
    descriptions = []
    
    # 3. Resolve variant for each item
    for item in items_resp:
        merchant_id = item.get("merchant_id")
        price = float(item.get("price") or 0)
        product_group_id = item.get("demand_signals", {}).get("product_group_id")
        desc = (item.get("offers") or {}).get("description")
        if desc:
            descriptions.append(desc)
            
        if merchant_id:
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
                logger.warning(f"No linked product for merchant {merchant_id} and group {product_group_id}")
                continue
                
            shopify_product_id = mp_rows[0]["shopify_product_id"]
        else:
            # Ungrouped item fallback
            product_id = item.get("demand_signals", {}).get("product_id")
            if not product_id:
                logger.warning(f"Skipping item {item.get('id')} - missing product_id for ungrouped item")
                continue
            
            p_rows = sb.table("products").select("shopify_product_id").eq("id", str(product_id)).limit(1).execute().data
            if not p_rows:
                logger.warning(f"Skipping item {item.get('id')} - missing product mapping")
                continue
            
            shopify_product_id = p_rows[0]["shopify_product_id"]
            
        variant_id = _resolve_variant_id(shopify_product_id)
        
        line_items.append({
            "variant_id": variant_id,
            "quantity": 1,
            "price": price
        })

    if not line_items:
        raise ValueError("Could not resolve any line items for Shopify order")

    total_price = float(recovery.get("total_price") or 0)
    
    payload = {
        "order": {
            "line_items": line_items,
            "customer": {"id": customer_id},
            "financial_status": "paid",
            "transactions": [
                {
                    "kind": "sale",
                    "status": "success",
                    "amount": str(total_price),
                    "gateway": "Razorpay"
                }
            ],
            "send_receipt": True,
            "send_fulfillment_receipt": False,
            "note": f"Recovered via Project Flow — offers: {' | '.join(descriptions)[:200]}",
        }
    }

    url = f"{_base_url()}/orders.json"
    try:
        resp = requests.post(url, headers=shopify_headers(), json=payload, timeout=30)
        resp.raise_for_status()
        created = resp.json().get("order") or {}
        shopify_order_id = str(created.get("id"))

        sb.table("cart_recoveries").update({
            "status": "order_created",
            "shopify_order_id": shopify_order_id,
            "updated_at": "now()",
        }).eq("id", recovery_id_str).execute()
        
        return {"status": "order_created", "shopify_order_id": shopify_order_id}
    except Exception as exc:
        logger.error(f"Shopify cart recovery order creation failed for {recovery_id_str}: {exc}")
        sb.table("cart_recoveries").update({
            "status": "paid", # Keep paid, but order failed
            "updated_at": "now()",
        }).eq("id", recovery_id_str).execute()
        raise

"""
Shopify webhook receiver router.

POST /webhooks/shopify/checkout-create  — Shopify checkouts/create topic
POST /webhooks/shopify/order-create     — Shopify orders/create topic
"""

import logging
from fastapi import APIRouter, Request, HTTPException

from app.services.webhooks import (
    verify_hmac,
    process_checkout_create,
    process_order_create,
)
import json
from app.db.client import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/shopify", tags=["webhooks"])


@router.post("/checkout-create")
async def webhook_checkout_create(request: Request):
    """
    Receive Shopify checkouts/create webhook.

    Verifies HMAC, upserts cart, creates demand signals per line item.
    Returns 200 immediately — Shopify requires fast ACKs.
    """
    body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")

    if not verify_hmac(body, hmac_header):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    payload = await request.json()
    logger.info(f"Checkout webhook received: {payload.get('id', 'unknown')}")

    result = process_checkout_create(payload)
    return {"status": "ok", **result}


@router.post("/order-create")
async def webhook_order_create(request: Request):
    """
    Receive Shopify orders/create webhook.

    Marks the originating cart as converted so the abandonment worker
    skips it.
    """
    body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")

    if not verify_hmac(body, hmac_header):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    payload = await request.json()
    logger.info(f"Order webhook received: {payload.get('id', 'unknown')}")

    result = process_order_create(payload)
    return {"status": "ok", **result}


@router.post("/cart-update")
async def webhook_cart_update(request: Request):
    """
    Receive Shopify carts/update webhook.
    Saves cart_token to the carts table so the storefront popup can match
    the browser's cart cookie to our internal cart record.
    """
    body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")

    if not verify_hmac(body, hmac_header):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    payload = json.loads(body)
    cart_token = payload.get("token")

    logger.info(f"[cart-update] cart_token={cart_token}, keys={list(payload.keys())}")

    if not cart_token:
        logger.warning("[cart-update] No token in payload, skipping")
        return {"status": "ok", "skipped": True}

    sb = get_supabase()

    # Strategy 1: Match by customer email (most reliable)
    customer_email = payload.get("customer", {}).get("email") if payload.get("customer") else None
    if not customer_email:
        customer_email = payload.get("email")

    updated = False
    if customer_email:
        result = sb.table("carts").update({"cart_token": cart_token}).eq(
            "customer_email", customer_email
        ).is_("cart_token", "null").order("created_at", desc=True).limit(1).execute().data
        if result:
            updated = True
            logger.info(f"[cart-update] Linked cart_token={cart_token} to cart via email={customer_email}")

    # Strategy 2: If checkout_token is in payload, match by shopify_checkout_id
    if not updated:
        checkout_token = payload.get("checkout_token")
        if checkout_token:
            result = sb.table("carts").update({"cart_token": cart_token}).eq(
                "shopify_checkout_id", str(checkout_token)
            ).execute().data
            if result:
                updated = True
                logger.info(f"[cart-update] Linked cart_token={cart_token} via checkout_token={checkout_token}")

    if not updated:
        logger.info(f"[cart-update] Could not match cart_token={cart_token} to any existing cart")

    return {"status": "ok", "updated": updated}


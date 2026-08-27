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

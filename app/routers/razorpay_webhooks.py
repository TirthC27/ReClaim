import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from app.services.orders import get_order, update_order
from app.services.payments import get_payment_for_order, update_payment
from app.services.razorpay_payments import verify_webhook_signature
from app.services.shopify_orders import create_shopify_order

router = APIRouter(prefix="/webhooks/razorpay", tags=["webhooks"])


@router.post("/payment-link-paid")
async def payment_link_paid(request: Request):
    raw = await request.body()
    signature = request.headers.get("X-Razorpay-Signature") or ""

    try:
        verify_webhook_signature(payload=raw, signature=signature)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = payload.get("event")
    if event != "payment_link.paid":
        return {"status": "ignored", "event": event}

    notes = (
        payload.get("payload", {})
        .get("payment_link", {})
        .get("entity", {})
        .get("notes", {})
    )
    order_id_raw = notes.get("order_id")
    if not order_id_raw:
        raise HTTPException(status_code=400, detail="Missing notes.order_id")

    order_id = UUID(str(order_id_raw))
    order = get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.get("status") in ["paid", "order_created"]:
        return {"status": "ok", "idempotent": True}

    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {}) or {}
    razorpay_payment_id = payment_entity.get("id")

    payment = get_payment_for_order(order_id)
    if payment:
        update_payment(
            UUID(str(payment["id"])),
            {
                "status": "paid",
                "razorpay_payment_id": razorpay_payment_id,
                "raw_webhook_payload": payload,
            },
        )

    update_order(order_id, {"status": "paid", "updated_at": "now()"})

    try:
        result = create_shopify_order(order_id)
        return {"status": "ok", "shopify": result}
    except Exception:
        return {"status": "ok", "shopify": {"status": "queued_for_retry"}}

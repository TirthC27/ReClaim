import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from app.services.orders import get_order, update_order
from app.services.payments import get_payment_for_order, update_payment
from app.services.razorpay_payments import verify_webhook_signature
from app.services.shopify_orders import create_shopify_order, create_shopify_cart_recovery_order
from app.db.client import get_supabase

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
    cart_recovery_id_raw = notes.get("cart_recovery_id")
    order_id_raw = notes.get("order_id")
    
    if not cart_recovery_id_raw and not order_id_raw:
        raise HTTPException(status_code=400, detail="Missing notes.order_id and notes.cart_recovery_id")
        
    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {}) or {}
    razorpay_payment_id = payment_entity.get("id")

    if cart_recovery_id_raw:
        # ── Cart Recovery Flow (Multi-item) ──
        sb = get_supabase()
        cart_recovery_id = UUID(str(cart_recovery_id_raw))
        recovery_resp = sb.table("cart_recoveries").select("*").eq("id", str(cart_recovery_id)).execute().data
        if not recovery_resp:
            raise HTTPException(status_code=404, detail="Cart recovery not found")
        recovery = recovery_resp[0]
        
        if recovery.get("status") in ["paid", "order_created"]:
            return {"status": "ok", "idempotent": True}
            
        sb.table("cart_recoveries").update({
            "status": "paid",
            "updated_at": "now()"
        }).eq("id", str(cart_recovery_id)).execute()
        
        try:
            result = create_shopify_cart_recovery_order(cart_recovery_id)
            return {"status": "ok", "shopify": result}
        except Exception as e:
            import logging
            logging.error(f"Shopify order creation failed: {e}")
            return {"status": "ok", "shopify": {"status": "queued_for_retry"}}
    else:
        # ── Single Order Flow (Backward Compatibility) ──
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

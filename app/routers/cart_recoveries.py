from uuid import UUID
import time
import razorpay
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.db.client import get_supabase

router = APIRouter(prefix="/cart-recoveries", tags=["cart-recoveries"])

# We only initialize this if RAZORPAY_KEY_ID is available
razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)) if settings.RAZORPAY_KEY_ID else None

import logging
logger = logging.getLogger(__name__)


@router.get("/by-cart-token/{cart_token}")
def get_recovery_by_cart_token(cart_token: str):
    """
    Lookup a cart recovery by the Shopify cart cookie token.
    Used by the storefront popup to check if a special offer is ready.
    """
    sb = get_supabase()

    # Find the cart matching this token
    cart = sb.table("carts").select("id").eq("cart_token", cart_token).order(
        "created_at", desc=True
    ).limit(1).execute().data
    if not cart:
        raise HTTPException(status_code=404, detail="No cart found for this token")

    cart_id = cart[0]["id"]

    # Find the most recent recovery for this cart
    recovery = sb.table("cart_recoveries").select("*").eq(
        "cart_id", str(cart_id)
    ).order("created_at", desc=True).limit(1).execute().data
    if not recovery:
        raise HTTPException(status_code=404, detail="No recovery found for this cart")

    rec = recovery[0]

    # Fetch items with their offers
    items = sb.table("cart_recovery_items").select(
        "*, offers(price, description, offer_type), demand_signals(product_title, quantity)"
    ).eq("cart_recovery_id", str(rec["id"])).execute().data

    return {
        "recovery": rec,
        "items": items or [],
    }



@router.get("/{recovery_id}/summary")
def get_cart_recovery_summary(recovery_id: UUID):
    sb = get_supabase()
    
    # Fetch recovery record
    rec_resp = sb.table("cart_recoveries").select("*").eq("id", str(recovery_id)).execute().data
    if not rec_resp:
        raise HTTPException(status_code=404, detail="Cart recovery not found")
    recovery = rec_resp[0]
    
    # Fetch items with their offers
    items_resp = sb.table("cart_recovery_items").select("*, offers(price, description, offer_type), demand_signals(product_title, quantity)").eq("cart_recovery_id", str(recovery_id)).execute().data
    
    return {
        "recovery": recovery,
        "items": items_resp
    }


@router.post("/{recovery_id}/checkout")
def checkout_cart_recovery(recovery_id: UUID):
    sb = get_supabase()
    rec_resp = sb.table("cart_recoveries").select("*").eq("id", str(recovery_id)).execute().data
    if not rec_resp:
        raise HTTPException(status_code=404, detail="Cart recovery not found")
        
    recovery = rec_resp[0]
    if recovery["status"] != "ready":
        raise HTTPException(status_code=400, detail="Not all items in this cart have a resolved offer yet")

    from app.services.razorpay_payments import create_payment_link

    amount_paise = int(float(recovery.get("total_price") or 0) * 100)
    
    payment_link = create_payment_link(
        amount_paise=amount_paise,
        description="Project Flow Special Offer",
        notes={"cart_recovery_id": str(recovery_id)},
        callback_url=f"{settings.FRONTEND_BASE_URL}/payment-success?cart_recovery_id={recovery_id}",
        customer_email=recovery.get("customer_email")
    )
    
    sb.table("cart_recoveries").update({
        "status": "pending_payment",
        "razorpay_payment_link_id": payment_link["id"],
    }).eq("id", str(recovery_id)).execute()
    
    payment_link_url = payment_link.get("short_url") or payment_link.get("url")
    return {"payment_link_url": payment_link_url}


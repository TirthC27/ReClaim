"""Offers router — CRUD with pool_id filter."""

from uuid import UUID
from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.models.schemas import OfferRead, OfferSelectRequest, OfferSelectResponse
from app.services import allocation as allocation_svc
from app.services import offers as svc
from app.services import orders as orders_svc
from app.services import payments as payments_svc
from app.services.razorpay_payments import create_payment_link

router = APIRouter(prefix="/offers", tags=["offers"])


@router.get("", response_model=list[OfferRead])
def list_offers(
    pool_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    status_ne: str | None = Query(default=None, description="Exclude offers with this status"),
    limit: int = 100,
    offset: int = 0,
):
    return svc.list_offers(pool_id=pool_id, status=status, status_ne=status_ne, limit=limit, offset=offset)


@router.get("/{offer_id}", response_model=OfferRead)
def get_offer(offer_id: UUID):
    row = svc.get_offer(offer_id)
    if not row:
        raise HTTPException(status_code=404, detail="Offer not found")
    return row


@router.post("/{offer_id}/select", response_model=OfferSelectResponse)
def select_offer(offer_id: UUID, body: OfferSelectRequest):
    offer = svc.get_offer(offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    if offer.get("status") not in ["validated", "selected"]:
        raise HTTPException(status_code=400, detail="Offer is not selectable")

    allocation = allocation_svc.get_allocation_for_signal(str(body.demand_signal_id))
    if not allocation:
        raise HTTPException(status_code=400, detail="No allocation exists for this demand_signal_id")

    allocated_merchant_id = allocation.get("merchant_id")
    if str(offer.get("merchant_id")) != str(allocated_merchant_id):
        raise HTTPException(status_code=403, detail="This offer is not allocated to this customer")

    created_order = orders_svc.create_order(
        {
            "offer_id": str(offer_id),
            "demand_signal_id": str(body.demand_signal_id),
            "merchant_id": str(allocated_merchant_id),
            "status": "pending_payment",
        }
    )

    order_id = created_order["id"]
    callback_url = f"{settings.FRONTEND_BASE_URL}/payment/success?order_id={order_id}"

    # Fetch customer email for Razorpay notification
    from app.db.client import get_supabase
    sb = get_supabase()
    signal_resp = sb.table("demand_signals").select("carts(customer_email)").eq("id", str(body.demand_signal_id)).execute()
    customer_email = None
    if signal_resp.data and signal_resp.data[0].get("carts"):
        customer_email = signal_resp.data[0]["carts"].get("customer_email")

    price = float(offer.get("price") or 0)
    if price <= 0:
        raise HTTPException(status_code=400, detail="Offer price is invalid")

    pl = create_payment_link(
        amount_paise=int(price * 100),
        description=str(offer.get("description") or ""),
        notes={"order_id": str(order_id), "offer_id": str(offer_id)},
        callback_url=callback_url,
        customer_email=customer_email,
    )

    payments_svc.create_payment(
        {
            "order_id": str(order_id),
            "razorpay_payment_link_id": pl.get("id"),
            "amount": price,
            "status": "created",
        }
    )

    payment_link_url = pl.get("short_url") or pl.get("short_url".upper()) or pl.get("url")
    if not payment_link_url:
        raise HTTPException(status_code=500, detail="Razorpay payment link URL missing")

    return {"order_id": order_id, "payment_link_url": payment_link_url}

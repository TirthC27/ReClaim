"""
Offer selection + Razorpay payment link creation.

POST /offers/{offer_id}/select → validates allocation, creates order,
generates Razorpay payment link, returns URL.
"""

import logging
import requests
from requests.auth import HTTPBasicAuth

from app.config import settings
from app.db.client import get_supabase

logger = logging.getLogger(__name__)


def select_offer(offer_id: str, demand_signal_id: str) -> dict:
    """
    Select an offer for a specific customer (demand signal).

    1. Verify allocation — customer can only select their allocated merchant's offer
    2. Create order row
    3. Create Razorpay payment link
    4. Create payment row
    5. Return payment link URL
    """
    sb = get_supabase()

    # ── 1. Fetch offer ───────────────────────────────────────
    offers = sb.table("offers").select("*").eq("id", offer_id).execute().data
    if not offers:
        raise ValueError("Offer not found")
    offer = offers[0]

    if offer["status"] not in ("validated", "selected"):
        raise ValueError(f"Offer status is '{offer['status']}', must be validated or selected")

    # ── 2. Verify allocation ─────────────────────────────────
    allocations = (
        sb.table("order_allocations")
        .select("*")
        .eq("demand_signal_id", demand_signal_id)
        .execute()
        .data
    )

    if allocations:
        allocated_merchant = allocations[0]["merchant_id"]
        if allocated_merchant != offer["merchant_id"]:
            raise ValueError(
                f"Allocation mismatch: customer is allocated to merchant "
                f"{allocated_merchant}, but selected offer from {offer['merchant_id']}"
            )

    # ── 3. Check for existing order (idempotency) ────────────
    existing = (
        sb.table("orders")
        .select("id, status")
        .eq("offer_id", offer_id)
        .eq("demand_signal_id", demand_signal_id)
        .limit(1)
        .execute()
        .data
    )
    if existing:
        if existing[0]["status"] == "expired":
            raise ValueError("This offer has expired.")

        # Check if payment link already exists
        payment = (
            sb.table("payments")
            .select("*")
            .eq("order_id", existing[0]["id"])
            .limit(1)
            .execute()
            .data
        )
        if payment and payment[0].get("razorpay_payment_link_id"):
            return {
                "order_id": existing[0]["id"],
                "payment_link_url": f"https://rzp.io/i/{payment[0]['razorpay_payment_link_id']}",
                "payment_link_id": payment[0]["razorpay_payment_link_id"],
            }

    # ── 4. Create order ──────────────────────────────────────
    order = sb.table("orders").insert({
        "offer_id": offer_id,
        "demand_signal_id": demand_signal_id,
        "merchant_id": offer["merchant_id"],
        "status": "pending_payment",
    }).execute().data[0]

    # ── 5. Create Razorpay payment link ──────────────────────
    amount_paise = int(float(offer.get("price", 0)) * 100)
    description = offer.get("description", "Project Flow offer")[:250]

    try:
        resp = requests.post(
            "https://api.razorpay.com/v1/payment_links",
            auth=HTTPBasicAuth(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
            json={
                "amount": amount_paise,
                "currency": "INR",
                "description": description,
                "notes": {
                    "order_id": str(order["id"]),
                    "offer_id": offer_id,
                },
                "callback_url": f"http://localhost:5173/payment-success?order_id={order['id']}",
                "callback_method": "get",
            },
            timeout=15,
        )
        resp.raise_for_status()
        rz_data = resp.json()
    except Exception as exc:
        logger.error(f"Razorpay payment link creation failed: {exc}")
        sb.table("orders").update({"status": "failed"}).eq("id", order["id"]).execute()
        raise ValueError(f"Payment link creation failed: {exc}")

    payment_link_id = rz_data.get("id", "")
    payment_link_url = rz_data.get("short_url", "")

    # ── 6. Create payment row ────────────────────────────────
    sb.table("payments").insert({
        "order_id": str(order["id"]),
        "razorpay_payment_link_id": payment_link_id,
        "amount": float(offer.get("price", 0)),
        "status": "created",
    }).execute()

    return {
        "order_id": str(order["id"]),
        "payment_link_url": payment_link_url,
        "payment_link_id": payment_link_id,
    }

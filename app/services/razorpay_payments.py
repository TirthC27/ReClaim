import json
from base64 import b64encode

import razorpay
import requests

from app.config import settings


import time

def create_payment_link(*, amount_paise: int, description: str, notes: dict, callback_url: str, customer_email: str | None = None) -> dict:
    auth_raw = f"{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}".encode("utf-8")
    auth = b64encode(auth_raw).decode("ascii")

    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "description": description,
        "notes": notes,
        "callback_url": callback_url,
        "callback_method": "get",
        "expire_by": int(time.time()) + (settings.PAYMENT_EXPIRY_HOURS * 3600),
    }

    if customer_email:
        payload["customer"] = {"email": customer_email}
        payload["notify"] = {"sms": False, "email": True}

    resp = requests.post(
        "https://api.razorpay.com/v1/payment_links",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def verify_webhook_signature(*, payload: bytes, signature: str) -> None:
    razorpay.Utility.verify_webhook_signature(payload, signature, settings.RAZORPAY_WEBHOOK_SECRET)


import json
from base64 import b64encode

import razorpay
import requests
import logging

from app.config import settings

logger = logging.getLogger(__name__)



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

    url = "https://api.razorpay.com/v1/payment_links"
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(
                url,
                json=payload,
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            
            if response.status_code == 429 and attempt < max_retries - 1:
                logger.warning(f"Razorpay rate limit hit. Retrying in {2 ** attempt} seconds...")
                time.sleep(2 ** attempt)
                continue
                
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to generate Razorpay link: {e}")
                if hasattr(e, "response") and e.response is not None:
                    logger.error(f"Response: {e.response.text}")
                raise
            time.sleep(2 ** attempt)
            
    return {}


def verify_webhook_signature(*, payload: bytes, signature: str) -> None:
    razorpay.Utility.verify_webhook_signature(payload, signature, settings.RAZORPAY_WEBHOOK_SECRET)

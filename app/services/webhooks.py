"""
Shopify webhook handling service.

- HMAC signature verification
- Checkout/create → cart + demand_signals creation
- Orders/create  → cart conversion detection
- Metafield caching for merchant_id resolution
"""

import hashlib
import hmac
import base64
import logging
from uuid import UUID

import requests
from app.config import settings
from app.db.client import get_supabase
from app.services.shopify_auth import shopify_headers

logger = logging.getLogger(__name__)

# In-memory cache: shopify_product_id → merchant_id (uuid string)
_metafield_cache: dict[str, str | None] = {}

API_VERSION = "2024-01"


# ── HMAC verification ───────────────────────────────────────

def verify_hmac(body: bytes, hmac_header: str) -> bool:
    """Verify the X-Shopify-Hmac-Sha256 header against the webhook secret."""
    if not settings.SHOPIFY_WEBHOOK_SECRET:
        logger.warning("SHOPIFY_WEBHOOK_SECRET not set — skipping HMAC verification")
        return True  # Allow during dev if secret not configured

    digest = hmac.new(
        settings.SHOPIFY_WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    computed = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(computed, hmac_header)


# ── Metafield resolution ────────────────────────────────────

def _resolve_merchant_id(shopify_product_id: str) -> str | None:
    """
    Resolve the projectflow.merchant_id metafield for a Shopify product.

    Uses an in-memory cache to avoid repeat API calls per product.
    Falls back to merchant_products table if metafield API fails.
    """
    pid = str(shopify_product_id)

    # Check cache first
    if pid in _metafield_cache:
        return _metafield_cache[pid]

    # Try Shopify metafield API
    try:
        url = (
            f"{settings.SHOPIFY_STORE_URL}/admin/api/{API_VERSION}"
            f"/products/{pid}/metafields.json"
        )
        resp = requests.get(
            url,
            headers=shopify_headers(),
            params={"namespace": "projectflow", "key": "merchant_id"},
            timeout=10,
        )
        resp.raise_for_status()
        metafields = resp.json().get("metafields", [])
        for mf in metafields:
            if mf.get("key") == "merchant_id":
                merchant_id = mf["value"]
                _metafield_cache[pid] = merchant_id
                return merchant_id
    except Exception as exc:
        logger.warning(f"Metafield API failed for product {pid}: {exc}")

    # Fallback: look up merchant_products table
    try:
        rows = (
            get_supabase()
            .table("merchant_products")
            .select("merchant_id")
            .eq("shopify_product_id", pid)
            .limit(1)
            .execute()
            .data
        )
        if rows:
            merchant_id = rows[0]["merchant_id"]
            _metafield_cache[pid] = merchant_id
            return merchant_id
    except Exception as exc:
        logger.warning(f"merchant_products lookup failed for product {pid}: {exc}")

    _metafield_cache[pid] = None
    return None


def _resolve_product_group_id(shopify_product_id: str) -> str | None:
    """
    Resolve product_group_id for a Shopify product.

    Checks products table first, then merchant_products.
    """
    sb = get_supabase()
    pid = str(shopify_product_id)

    # Check products table
    rows = (
        sb.table("products")
        .select("product_group_id")
        .eq("shopify_product_id", pid)
        .limit(1)
        .execute()
        .data
    )
    if rows and rows[0].get("product_group_id"):
        return rows[0]["product_group_id"]

    # Fallback: merchant_products
    rows = (
        sb.table("merchant_products")
        .select("product_group_id")
        .eq("shopify_product_id", pid)
        .limit(1)
        .execute()
        .data
    )
    if rows and rows[0].get("product_group_id"):
        return rows[0]["product_group_id"]

    return None


# ── Checkout/create handler ─────────────────────────────────

def process_checkout_create(payload: dict) -> dict:
    """
    Process a checkouts/create webhook payload.

    1. Upsert cart row
    2. For each line_item, resolve product/group/merchant and create demand_signal
    """
    sb = get_supabase()

    checkout_id = str(payload.get("id", "") or payload.get("token", ""))
    cart_token = str(payload.get("cart_token", "") or payload.get("token", ""))
    customer_email = None
    if payload.get("email"):
        customer_email = payload["email"]
    elif payload.get("customer", {}).get("email"):
        customer_email = payload["customer"]["email"]

    # ── 1. Upsert cart ───────────────────────────────────────
    cart_row = {
        "shopify_checkout_id": checkout_id,
        "customer_email": customer_email,
        "status": "active",
    }
    if cart_token:
        cart_row["cart_token"] = cart_token
    cart_result = (
        sb.table("carts")
        .upsert(cart_row, on_conflict="shopify_checkout_id")
        .execute()
        .data
    )
    cart_id = cart_result[0]["id"] if cart_result else None
    if not cart_id:
        logger.error(f"Failed to upsert cart for checkout {checkout_id}")
        return {"error": "cart upsert failed"}

    # ── 2. Process line items ────────────────────────────────
    line_items = payload.get("line_items", [])
    signals_created = 0

    for item in line_items:
        shopify_pid = str(item.get("product_id", ""))
        if not shopify_pid:
            continue

        # Ensure product exists in our DB (create minimal row if missing)
        existing = (
            sb.table("products")
            .select("id, product_group_id")
            .eq("shopify_product_id", shopify_pid)
            .limit(1)
            .execute()
            .data
        )
        if existing:
            internal_product_id = existing[0]["id"]
        else:
            # Create minimal product row, marked for backfill
            new_product = {
                "shopify_product_id": shopify_pid,
                "title": item.get("title", "Unknown"),
                "price": float(item.get("price", 0)),
                "vendor": item.get("vendor"),
                "sku": item.get("sku"),
                "raw_shopify_data": {"needs_backfill": True, "source": "webhook"},
            }
            result = sb.table("products").insert(new_product).execute().data
            internal_product_id = result[0]["id"] if result else None

        if not internal_product_id:
            continue

        # Resolve product_group_id and merchant_id
        product_group_id = _resolve_product_group_id(shopify_pid)
        merchant_id = _resolve_merchant_id(shopify_pid)

        # Upsert demand signal — deduplicate by cart_id + product_id
        existing_signal = (
            sb.table("demand_signals")
            .select("id")
            .eq("cart_id", str(cart_id))
            .eq("product_id", str(internal_product_id))
            .eq("status", "pending")
            .limit(1)
            .execute()
            .data
        )

        if existing_signal:
            # Update quantity on existing signal instead of creating duplicate
            try:
                sb.table("demand_signals").update({
                    "quantity": int(item.get("quantity", 1)),
                    "product_title": item.get("title", "Unknown"),
                }).eq("id", existing_signal[0]["id"]).execute()
                signals_created += 1
            except Exception as exc:
                logger.error(f"Failed to update demand signal: {exc}")
        else:
            # Create new signal
            signal = {
                "cart_id": str(cart_id),
                "product_id": str(internal_product_id),
                "product_title": item.get("title", "Unknown"),
                "quantity": int(item.get("quantity", 1)),
                "status": "pending",
            }
            if product_group_id:
                signal["product_group_id"] = str(product_group_id)
            if merchant_id:
                signal["merchant_id"] = str(merchant_id)

            try:
                sb.table("demand_signals").insert(signal).execute()
                signals_created += 1
            except Exception as exc:
                logger.error(f"Failed to create demand signal: {exc}")

    return {
        "cart_id": str(cart_id),
        "checkout_id": checkout_id,
        "signals_created": signals_created,
    }


# ── Orders/create handler (conversion detection) ────────────

def process_order_create(payload: dict) -> dict:
    """
    Process an orders/create webhook payload.

    Marks the originating cart as 'converted' so the abandonment worker
    skips it.
    """
    sb = get_supabase()

    checkout_id = str(payload.get("checkout_id", ""))
    if not checkout_id:
        # Try to find via checkout_token
        checkout_id = str(payload.get("checkout_token", ""))

    if not checkout_id:
        return {"status": "no_checkout_id"}

    # Find and update the cart
    carts = (
        sb.table("carts")
        .select("id")
        .eq("shopify_checkout_id", checkout_id)
        .limit(1)
        .execute()
        .data
    )

    if not carts:
        return {"status": "cart_not_found", "checkout_id": checkout_id}

    cart_id = carts[0]["id"]

    # Mark cart as converted
    sb.table("carts").update({
        "status": "converted",
        "converted_at": "now()",
    }).eq("id", str(cart_id)).execute()

    # Cancel any pending demand signals for this cart
    sb.table("demand_signals").update({
        "status": "expired",
    }).eq("cart_id", str(cart_id)).eq("status", "pending").execute()

    return {
        "status": "converted",
        "cart_id": str(cart_id),
        "checkout_id": checkout_id,
    }

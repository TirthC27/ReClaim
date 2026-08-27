"""
Shopify OAuth — Client Credentials Grant token management.

Fetches an Admin API access token via POST to
{SHOPIFY_STORE_URL}/admin/oauth/access_token with client_credentials grant,
caches the token in memory, and auto-refreshes 5 minutes before expiry.
"""

import time
import threading
import requests

from app.config import settings


class _TokenStore:
    """Thread-safe in-memory token cache with pre-emptive refresh."""

    def __init__(self):
        self._access_token: str | None = None
        self._expires_at: float = 0.0  # epoch seconds
        self._lock = threading.Lock()

    def _fetch_token(self) -> tuple[str, float]:
        """POST client_credentials grant to Shopify and return (token, expires_at)."""
        url = f"{settings.SHOPIFY_STORE_URL}/admin/oauth/access_token"
        payload = {
            "client_id": settings.SHOPIFY_CLIENT_ID,
            "client_secret": settings.SHOPIFY_CLIENT_SECRET,
            "grant_type": "client_credentials",
        }
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        # Refresh 5 minutes (300 s) before actual expiry
        expires_at = time.time() + expires_in - 300

        return token, expires_at

    def get_token(self) -> str:
        """Return a valid access token, refreshing only when needed."""
        # Fast path — token is still valid
        if self._access_token and time.time() < self._expires_at:
            return self._access_token

        with self._lock:
            # Double-check after acquiring lock (another thread may have refreshed)
            if self._access_token and time.time() < self._expires_at:
                return self._access_token

            token, expires_at = self._fetch_token()
            self._access_token = token
            self._expires_at = expires_at
            return token


_store = _TokenStore()


def get_shopify_access_token() -> str:
    """
    Return a valid Shopify Admin API access token.

    Falls back to the static SHOPIFY_ADMIN_TOKEN env var if
    SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET are not configured.
    """
    if settings.SHOPIFY_CLIENT_ID and settings.SHOPIFY_CLIENT_SECRET:
        return _store.get_token()

    # Fallback: static token from .env
    if settings.SHOPIFY_ADMIN_TOKEN:
        return settings.SHOPIFY_ADMIN_TOKEN

    raise RuntimeError(
        "No Shopify credentials configured. Set SHOPIFY_CLIENT_ID + "
        "SHOPIFY_CLIENT_SECRET for OAuth, or SHOPIFY_ADMIN_TOKEN for static auth."
    )


def shopify_headers() -> dict[str, str]:
    """Return headers dict with current access token for Shopify Admin API calls."""
    return {"X-Shopify-Access-Token": get_shopify_access_token()}

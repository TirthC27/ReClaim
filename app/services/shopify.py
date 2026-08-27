"""
Service for proxying Shopify Admin API calls.

Uses the OAuth token module for authentication (client_credentials grant
with auto-refresh), falling back to static SHOPIFY_ADMIN_TOKEN.
"""

import requests
from app.config import settings
from app.services.shopify_auth import shopify_headers

API_VERSION = "2024-01"


def _base_url() -> str:
    return f"{settings.SHOPIFY_STORE_URL}/admin/api/{API_VERSION}"


def _paginate(url: str, params: dict | None = None) -> list[dict]:
    """Generic Shopify REST paginator using Link headers."""
    results: list[dict] = []
    params = params or {}

    while url:
        resp = requests.get(url, headers=shopify_headers(), params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        key = list(data.keys())[0]  # "products", "metafields", etc.
        results.extend(data.get(key, []))

        # Follow pagination via Link header
        link = resp.headers.get("Link", "")
        url = None  # type: ignore[assignment]
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split("<")[1].split(">")[0]
                    params = {}  # URL already contains params
                    break

    return results


def fetch_shopify_vendors() -> list[str]:
    """
    GET /products.json and return distinct vendor values.

    Paginates through all products to collect every vendor string.
    """
    url = f"{_base_url()}/products.json"
    products = _paginate(url, {"limit": 250, "fields": "vendor"})
    vendors = {p["vendor"] for p in products if p.get("vendor")}
    return sorted(vendors)


def fetch_products_by_vendor(vendor_name: str) -> list[dict]:
    """Return all Shopify products whose vendor field matches exactly."""
    url = f"{_base_url()}/products.json"
    return _paginate(url, {"limit": 250, "vendor": vendor_name})


def write_metafield(product_id: str | int, namespace: str, key: str, value: str) -> dict:
    """
    Create / update a metafield on a Shopify product.

    POST /products/{product_id}/metafields.json
    """
    url = f"{_base_url()}/products/{product_id}/metafields.json"
    payload = {
        "metafield": {
            "namespace": namespace,
            "key": key,
            "value": value,
            "type": "single_line_text_field",
        }
    }
    resp = requests.post(url, headers=shopify_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json().get("metafield", {})

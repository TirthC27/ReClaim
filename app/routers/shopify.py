"""Shopify Admin API proxy router."""

from fastapi import APIRouter, HTTPException

from app.services import shopify as svc

router = APIRouter(prefix="/shopify", tags=["shopify"])


@router.get("/vendors")
def get_vendors():
    """
    Proxy to Shopify Admin API — returns distinct vendor strings.

    Used by the merchant-onboarding UI to populate a dropdown.
    """
    try:
        vendors = svc.fetch_shopify_vendors()
        return {"vendors": vendors}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Shopify API error: {exc}")

"""
Merchant onboarding router.

POST /merchants/onboard          — create a merchant
GET  /merchants/{id}/shopify-products — fetch vendor's Shopify listings
POST /merchants/{id}/link-products    — link products + write metafields
"""

from uuid import UUID
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import merchant_onboarding as svc

router = APIRouter(prefix="/merchants", tags=["merchant-onboarding"])


# ── Request / response schemas ───────────────────────────────

class OnboardRequest(BaseModel):
    name: str
    shopify_vendor_name: str
    margin_floor_pct: float | None = None


class NewGroup(BaseModel):
    canonical_sku: str | None = None
    model_name: str


class ProductAssignment(BaseModel):
    shopify_product_id: str
    product_group_id: str | None = None
    new_group: NewGroup | None = None


class LinkProductsRequest(BaseModel):
    assignments: list[ProductAssignment]


# ── Endpoints ────────────────────────────────────────────────

@router.post("/onboard", status_code=201)
def onboard_merchant(body: OnboardRequest):
    """Sign up a new merchant and return the created record."""
    try:
        merchant = svc.onboard_merchant(body.model_dump(exclude_none=True))
        return merchant
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{merchant_id}/shopify-products")
def get_shopify_products(merchant_id: UUID):
    """
    Fetch all Shopify products belonging to this merchant's vendor.

    Used by the product-linking UI to display products for group assignment.
    """
    products = svc.get_vendor_shopify_products(merchant_id)
    if not products and products is not None:
        return {"products": [], "message": "No products found for this vendor"}
    return {"products": products}


@router.post("/{merchant_id}/link-products")
def link_products(merchant_id: UUID, body: LinkProductsRequest):
    """
    Link Shopify products to internal product groups.

    For each assignment:
    1. Writes a projectflow.merchant_id metafield to Shopify
    2. Creates a new product_group if new_group is provided
    3. Inserts a merchant_products join row
    4. Updates the products table's product_group_id
    """
    assignments = [a.model_dump() for a in body.assignments]
    result = svc.link_products(merchant_id, assignments)
    return result

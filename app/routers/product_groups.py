"""Product-groups router — CRUD + merchant resolution."""

from uuid import UUID
from fastapi import APIRouter, HTTPException

from app.models.schemas import ProductGroupCreate, ProductGroupRead
from app.services import product_groups as svc

router = APIRouter(prefix="/product-groups", tags=["product-groups"])


@router.get("", response_model=list[ProductGroupRead])
def list_product_groups(limit: int = 100, offset: int = 0):
    return svc.list_product_groups(limit=limit, offset=offset)


@router.post("", response_model=ProductGroupRead, status_code=201)
def create_product_group(body: ProductGroupCreate):
    return svc.create_product_group(body.model_dump(exclude_none=True))


@router.get("/{group_id}/merchants")
def get_merchants_for_group(group_id: UUID):
    """Return all merchants competing under this product group."""
    group = svc.get_product_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Product group not found")
    return svc.get_merchants_for_group(group_id)

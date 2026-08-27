"""Products router — CRUD only."""

from uuid import UUID
from fastapi import APIRouter, HTTPException

from app.models.schemas import ProductCreate, ProductRead
from app.services import products as svc

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductRead])
def list_products(limit: int = 100, offset: int = 0):
    return svc.list_products(limit=limit, offset=offset)


@router.get("/{product_id}", response_model=ProductRead)
def get_product(product_id: UUID):
    row = svc.get_product(product_id)
    if not row:
        raise HTTPException(status_code=404, detail="Product not found")
    return row


@router.post("", response_model=ProductRead, status_code=201)
def create_product(body: ProductCreate):
    payload = body.model_dump(exclude_none=True)
    # Serialize UUIDs for Supabase
    for k, v in payload.items():
        if isinstance(v, UUID):
            payload[k] = str(v)
    return svc.create_product(payload)

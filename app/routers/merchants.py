"""Merchants router — CRUD + PATCH."""

from uuid import UUID
from fastapi import APIRouter, HTTPException

from app.models.schemas import MerchantCreate, MerchantUpdate, MerchantRead
from app.services import merchants as svc

router = APIRouter(prefix="/merchants", tags=["merchants"])


@router.get("", response_model=list[MerchantRead])
def list_merchants(limit: int = 100, offset: int = 0):
    return svc.list_merchants(limit=limit, offset=offset)


@router.post("", response_model=MerchantRead, status_code=201)
def create_merchant(body: MerchantCreate):
    return svc.create_merchant(body.model_dump(exclude_none=True))


@router.patch("/{merchant_id}", response_model=MerchantRead)
def update_merchant(merchant_id: UUID, body: MerchantUpdate):
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")
    row = svc.update_merchant(merchant_id, payload)
    if not row:
        raise HTTPException(status_code=404, detail="Merchant not found")
    return row

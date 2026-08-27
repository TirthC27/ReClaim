"""Offers router — CRUD with pool_id filter."""

from uuid import UUID
from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import OfferRead
from app.services import offers as svc

router = APIRouter(prefix="/offers", tags=["offers"])


@router.get("", response_model=list[OfferRead])
def list_offers(
    pool_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = 100,
    offset: int = 0,
):
    return svc.list_offers(pool_id=pool_id, status=status, limit=limit, offset=offset)


@router.get("/{offer_id}", response_model=OfferRead)
def get_offer(offer_id: UUID):
    row = svc.get_offer(offer_id)
    if not row:
        raise HTTPException(status_code=404, detail="Offer not found")
    return row

"""Orders router — read only for now."""

from uuid import UUID
from fastapi import APIRouter, HTTPException

from app.models.schemas import OrderRead
from app.services import orders as svc

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("/{order_id}", response_model=OrderRead)
def get_order(order_id: UUID):
    row = svc.get_order(order_id)
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    return row

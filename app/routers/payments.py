"""Payments router — read only for now."""

from uuid import UUID
from fastapi import APIRouter, HTTPException

from app.models.schemas import PaymentRead
from app.services import payments as svc

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("/{payment_id}", response_model=PaymentRead)
def get_payment(payment_id: UUID):
    row = svc.get_payment(payment_id)
    if not row:
        raise HTTPException(status_code=404, detail="Payment not found")
    return row

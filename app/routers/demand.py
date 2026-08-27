"""Demand router — pools + signals."""

from uuid import UUID
from fastapi import APIRouter, HTTPException

from app.models.schemas import DemandPoolRead
from app.services import demand as svc

router = APIRouter(prefix="/demand-pools", tags=["demand"])


@router.get("", response_model=list[DemandPoolRead])
def list_demand_pools(limit: int = 100, offset: int = 0):
    return svc.list_demand_pools(limit=limit, offset=offset)


@router.get("/{pool_id}", response_model=DemandPoolRead)
def get_demand_pool(pool_id: UUID):
    row = svc.get_demand_pool(pool_id)
    if not row:
        raise HTTPException(status_code=404, detail="Demand pool not found")
    return row


@router.get("/{pool_id}/eligible-merchants")
def eligible_merchants(pool_id: UUID):
    """Resolve which merchants can bid on this demand pool."""
    pool = svc.get_demand_pool(pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail="Demand pool not found")
    return svc.get_eligible_merchants(pool_id)

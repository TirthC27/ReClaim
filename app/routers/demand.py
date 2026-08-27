"""Demand router — pools + signals + merchant resolution."""

from uuid import UUID
from fastapi import APIRouter, HTTPException

from app.models.schemas import DemandPoolRead
from app.services import demand as svc
from app.services.aggregation import get_selected_merchants

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


@router.get("/{pool_id}/selected-merchants")
def selected_merchants(pool_id: UUID):
    """
    Return the Section 9A-selected merchants for this demand pool.

    These are the merchants chosen by the selection algorithm to
    generate offers, based on pool size and merchant positioning.
    """
    pool = svc.get_demand_pool(pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail="Demand pool not found")

    merchants = get_selected_merchants(pool_id)
    return {
        "pool_id": str(pool_id),
        "signal_count": pool.get("signal_count", 0),
        "selected_merchants": merchants,
    }

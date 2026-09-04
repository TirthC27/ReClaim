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


@router.get("/multi-product")
def list_multi_product_pools(limit: int = 100, offset: int = 0):
    """List all multi-product pools."""
    from app.db.client import get_supabase
    sb = get_supabase()
    rows = (
        sb.table("multi_product_pools")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
    )
    return rows


@router.get("/{pool_id}")
def get_demand_pool(pool_id: UUID):
    row = svc.get_demand_pool(pool_id)
    if not row:
        raise HTTPException(status_code=404, detail="Demand pool not found")
    return row


@router.get("/{pool_id}/signals")
def get_pool_signals(pool_id: str):
    """
    Returns every demand_signal belonging to this pool's product_group,
    joined with the customer's email and (if it exists) their allocation
    and offer details — so it's clear exactly which signal maps to which customer and which offer.
    """
    from app.db.client import get_supabase
    supabase = get_supabase()

    pool = (
        supabase.table("demand_pools")
        .select("id, product_group_id")
        .eq("id", pool_id)
        .limit(1)
        .execute()
    )
    if not pool.data:
        raise HTTPException(status_code=404, detail="Demand pool not found")

    signals_resp = (
        supabase.table("demand_signals")
        .select("id, cart_id, quantity, status, created_at, carts(customer_email)")
        .eq("product_group_id", pool.data[0]["product_group_id"])
        .in_("status", ["abandoned", "pooled"])
        .execute()
    )
    signals = signals_resp.data or []

    allocations_resp = (
        supabase.table("order_allocations")
        .select("demand_signal_id, merchant_id, rotation_position")
        .eq("demand_pool_id", pool_id)
        .execute()
    )
    allocations_by_signal = {a["demand_signal_id"]: a for a in (allocations_resp.data or [])}

    # Fetch selected/validated offers for this pool to match with merchants
    offers_resp = (
        supabase.table("offers")
        .select("id, merchant_id, offer_type, price, description")
        .eq("demand_pool_id", pool_id)
        .in_("status", ["selected", "validated"])
        .execute()
    )
    # Prefer selected over validated if both exist
    offers_by_merchant = {}
    for o in (offers_resp.data or []):
        mid = o["merchant_id"]
        if mid not in offers_by_merchant or o.get("status") == "selected":
            offers_by_merchant[mid] = o

    result = []
    for s in signals:
        alloc = allocations_by_signal.get(s["id"])
        offer = offers_by_merchant.get(alloc["merchant_id"]) if alloc else None

        result.append({
            "demand_signal_id": s["id"],
            "customer_email": (s.get("carts") or {}).get("customer_email"),
            "quantity": s["quantity"],
            "status": s["status"],
            "created_at": s["created_at"],
            "allocated": alloc is not None,
            "allocation": {
                "merchant_id": alloc["merchant_id"],
                "offer": offer,
            } if alloc else None,
        })
    
    return {"pool_id": pool_id, "signals": result}


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

"""CRUD helpers for **demand_signals** and **demand_pools**."""

from uuid import UUID
from app.db.client import get_supabase


SIGNALS = "demand_signals"
POOLS = "demand_pools"
JOIN_TABLE = "merchant_products"


# ── demand_pools ─────────────────────────────────────────────

def list_demand_pools(limit: int = 100, offset: int = 0) -> list[dict]:
    return (
        get_supabase()
        .table(POOLS)
        .select("*")
        .range(offset, offset + limit - 1)
        .execute()
        .data
    )


def get_demand_pool(pool_id: UUID) -> dict | None:
    rows = (
        get_supabase()
        .table(POOLS)
        .select("*")
        .eq("id", str(pool_id))
        .execute()
        .data
    )
    return rows[0] if rows else None


def get_eligible_merchants(pool_id: UUID) -> list[dict]:
    """
    Resolve merchants eligible to bid on a demand pool.

    1. Look up the pool's product_group_id.
    2. Find all merchant_products rows for that group.
    3. Return merchant details via join.
    """
    pool = get_demand_pool(pool_id)
    if not pool:
        return []
    group_id = pool["product_group_id"]
    return (
        get_supabase()
        .table(JOIN_TABLE)
        .select("*, merchants(*)")
        .eq("product_group_id", str(group_id))
        .execute()
        .data
    )


# ── demand_signals ───────────────────────────────────────────

def list_demand_signals(limit: int = 100, offset: int = 0) -> list[dict]:
    return (
        get_supabase()
        .table(SIGNALS)
        .select("*")
        .range(offset, offset + limit - 1)
        .execute()
        .data
    )


def create_demand_signal(payload: dict) -> dict:
    return (
        get_supabase()
        .table(SIGNALS)
        .insert(payload)
        .execute()
        .data[0]
    )

"""CRUD helpers for **demand_signals** and **demand_pools**."""

from uuid import UUID
from app.services.aggregation import now_iso
from app.db.client import get_supabase


SIGNALS = "demand_signals"
POOLS = "demand_pools"
JOIN_TABLE = "merchant_products"


# ── demand_pools ─────────────────────────────────────────────

def list_demand_pools(limit: int = 100, offset: int = 0) -> list[dict]:
    sb = get_supabase()
    pools = (
        sb.table(POOLS)
        .select("*, product_groups(model_name)")
        .gt("expires_at", now_iso())
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
        .data
    )
    if not pools:
        return []

    # Fetch signals for all pools to determine demo status on frontend
    group_ids = [p["product_group_id"] for p in pools if p.get("product_group_id")]
    if group_ids:
        signals_data = (
            sb.table(SIGNALS)
            .select("product_group_id, carts(customer_email)")
            .in_("product_group_id", group_ids)
            .execute()
            .data
        )
        
        # Group signals by product_group_id
        signals_by_group = {}
        for s in signals_data:
            gid = s["product_group_id"]
            if gid not in signals_by_group:
                signals_by_group[gid] = []
            
            customer_email = None
            if s.get("carts") and s["carts"].get("customer_email"):
                customer_email = s["carts"]["customer_email"]
                
            signals_by_group[gid].append({"customer_email": customer_email})
            
        for p in pools:
            p["signals"] = signals_by_group.get(p["product_group_id"], [])

    return pools


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

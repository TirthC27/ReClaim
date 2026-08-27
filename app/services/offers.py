"""CRUD helpers for the **offers** table."""

from uuid import UUID
from app.db.client import get_supabase


TABLE = "offers"


def list_offers(pool_id: UUID | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
    q = get_supabase().table(TABLE).select("*")
    if pool_id:
        q = q.eq("demand_pool_id", str(pool_id))
    return q.range(offset, offset + limit - 1).execute().data


def get_offer(offer_id: UUID) -> dict | None:
    rows = (
        get_supabase()
        .table(TABLE)
        .select("*")
        .eq("id", str(offer_id))
        .execute()
        .data
    )
    return rows[0] if rows else None


def create_offer(payload: dict) -> dict:
    return (
        get_supabase()
        .table(TABLE)
        .insert(payload)
        .execute()
        .data[0]
    )

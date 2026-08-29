"""CRUD helpers for the **orders** table."""

from uuid import UUID
from app.db.client import get_supabase


TABLE = "orders"


def get_order(order_id: UUID) -> dict | None:
    rows = (
        get_supabase()
        .table(TABLE)
        .select("*")
        .eq("id", str(order_id))
        .execute()
        .data
    )
    return rows[0] if rows else None


def create_order(payload: dict) -> dict:
    return (
        get_supabase()
        .table(TABLE)
        .insert(payload)
        .execute()
        .data[0]
    )


def find_order(offer_id: UUID, demand_signal_id: UUID) -> dict | None:
    rows = (
        get_supabase()
        .table(TABLE)
        .select("*")
        .eq("offer_id", str(offer_id))
        .eq("demand_signal_id", str(demand_signal_id))
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def update_order(order_id: UUID, payload: dict) -> dict:
    return (
        get_supabase()
        .table(TABLE)
        .update(payload)
        .eq("id", str(order_id))
        .execute()
        .data[0]
    )

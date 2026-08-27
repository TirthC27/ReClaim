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

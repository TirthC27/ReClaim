"""CRUD helpers for the **payments** table."""

from uuid import UUID
from app.db.client import get_supabase


TABLE = "payments"


def get_payment(payment_id: UUID) -> dict | None:
    rows = (
        get_supabase()
        .table(TABLE)
        .select("*")
        .eq("id", str(payment_id))
        .execute()
        .data
    )
    return rows[0] if rows else None


def create_payment(payload: dict) -> dict:
    return (
        get_supabase()
        .table(TABLE)
        .insert(payload)
        .execute()
        .data[0]
    )

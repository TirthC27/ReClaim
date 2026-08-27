"""CRUD helpers for the **merchants** table."""

from uuid import UUID
from app.db.client import get_supabase


TABLE = "merchants"


def list_merchants(limit: int = 100, offset: int = 0) -> list[dict]:
    return (
        get_supabase()
        .table(TABLE)
        .select("*")
        .range(offset, offset + limit - 1)
        .execute()
        .data
    )


def get_merchant(merchant_id: UUID) -> dict | None:
    rows = (
        get_supabase()
        .table(TABLE)
        .select("*")
        .eq("id", str(merchant_id))
        .execute()
        .data
    )
    return rows[0] if rows else None


def create_merchant(payload: dict) -> dict:
    return (
        get_supabase()
        .table(TABLE)
        .insert(payload)
        .execute()
        .data[0]
    )


def update_merchant(merchant_id: UUID, payload: dict) -> dict | None:
    rows = (
        get_supabase()
        .table(TABLE)
        .update(payload)
        .eq("id", str(merchant_id))
        .execute()
        .data
    )
    return rows[0] if rows else None

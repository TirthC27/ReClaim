"""CRUD helpers for the **products** table."""

from uuid import UUID
from app.db.client import get_supabase


TABLE = "products"


def list_products(limit: int = 100, offset: int = 0) -> list[dict]:
    return (
        get_supabase()
        .table(TABLE)
        .select("*")
        .range(offset, offset + limit - 1)
        .execute()
        .data
    )


def get_product(product_id: UUID) -> dict | None:
    rows = (
        get_supabase()
        .table(TABLE)
        .select("*")
        .eq("id", str(product_id))
        .execute()
        .data
    )
    return rows[0] if rows else None


def create_product(payload: dict) -> dict:
    return (
        get_supabase()
        .table(TABLE)
        .insert(payload)
        .execute()
        .data[0]
    )

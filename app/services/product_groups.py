"""CRUD helpers for the **product_groups** table + merchant resolution."""

from uuid import UUID
from app.db.client import get_supabase


TABLE = "product_groups"
JOIN_TABLE = "merchant_products"


def list_product_groups(limit: int = 100, offset: int = 0) -> list[dict]:
    return (
        get_supabase()
        .table(TABLE)
        .select("*")
        .range(offset, offset + limit - 1)
        .execute()
        .data
    )


def get_product_group(group_id: UUID) -> dict | None:
    rows = (
        get_supabase()
        .table(TABLE)
        .select("*")
        .eq("id", str(group_id))
        .execute()
        .data
    )
    return rows[0] if rows else None


def create_product_group(payload: dict) -> dict:
    return (
        get_supabase()
        .table(TABLE)
        .insert(payload)
        .execute()
        .data[0]
    )


def get_merchants_for_group(group_id: UUID) -> list[dict]:
    """Return merchant_products rows (with merchant details) for a product group."""
    return (
        get_supabase()
        .table(JOIN_TABLE)
        .select("*, merchants(*)")
        .eq("product_group_id", str(group_id))
        .execute()
        .data
    )

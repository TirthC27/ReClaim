"""
Multi-Product Cart Aggregation

Classifies carts, creates basket signatures, manages multi-product pools,
and tracks product co-occurrences.
"""

import logging
from uuid import UUID
from datetime import datetime, timezone
from app.db.client import get_supabase

logger = logging.getLogger(__name__)
sb = get_supabase()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_cart(cart_id: str) -> str:
    """
    Returns "single" or "multi" based on how many distinct
    product_group_ids exist among the cart's abandoned demand signals.
    Signals without a product_group_id are ignored.
    """
    signals = (
        sb.table("demand_signals")
        .select("product_group_id")
        .eq("cart_id", cart_id)
        .in_("status", ["abandoned", "pooled"])
        .execute()
        .data
    )
    if not signals:
        return "single"
        
    distinct_groups = {s["product_group_id"] for s in signals if s.get("product_group_id")}
    return "multi" if len(distinct_groups) > 1 else "single"


def compute_basket_signature(product_group_ids: list[str]) -> str:
    """
    Sorted pipe-delimited string of product_group UUIDs.
    e.g. "61af4866-...|a2b3c4d5-..."
    """
    return "|".join(sorted(product_group_ids))


def _update_co_occurrences(product_group_ids: list[str]):
    """
    For every pair (A, B) in the basket, upsert basket_co_occurrences.
    """
    n = len(product_group_ids)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = sorted([product_group_ids[i], product_group_ids[j]])
            
            # Upsert using RPC or fetch-and-update (since we lack RPC for upsert)
            existing = (
                sb.table("basket_co_occurrences")
                .select("*")
                .eq("product_group_id_a", a)
                .eq("product_group_id_b", b)
                .execute()
                .data
            )
            
            if existing:
                sb.table("basket_co_occurrences").update({
                    "co_occurrence_count": existing[0]["co_occurrence_count"] + 1,
                    "last_seen_at": now_iso()
                }).eq("id", existing[0]["id"]).execute()
            else:
                sb.table("basket_co_occurrences").insert({
                    "product_group_id_a": a,
                    "product_group_id_b": b,
                    "co_occurrence_count": 1
                }).execute()


def _select_merchants_by_coverage(pool_id: str, product_group_ids: list[str]) -> list[str]:
    """
    Find merchants who stock these products and rank them by coverage.
    Coverage 3/3 > 2/3 > 1/3.
    Updates the multi_product_pool with selected_merchant_ids.
    """
    # Find all merchants who stock ANY of these products
    merchant_products = (
        sb.table("merchant_products")
        .select("merchant_id, product_group_id")
        .in_("product_group_id", product_group_ids)
        .execute()
        .data
    )
    
    if not merchant_products:
        return []
        
    merchant_coverage = {}
    for mp in merchant_products:
        mid = mp["merchant_id"]
        if mid not in merchant_coverage:
            merchant_coverage[mid] = set()
        merchant_coverage[mid].add(mp["product_group_id"])
        
    # Sort by coverage descending (most products covered first)
    sorted_merchants = sorted(
        merchant_coverage.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )
    
    selected_ids = [m[0] for m in sorted_merchants]
    
    sb.table("multi_product_pools").update({
        "selected_merchant_ids": selected_ids
    }).eq("id", pool_id).execute()
    
    return selected_ids


def aggregate_multi_product_demand(cart_id: str):
    """
    1. Collect grouped product_group_ids from cart signals
    2. Compute basket_signature
    3. Find or create multi_product_pool
    4. Upsert multi_product_pool_products
    5. Update signals and cart_recoveries
    6. Select merchants by coverage
    7. Update co-occurrences
    """
    # 1. Fetch signals
    signals = (
        sb.table("demand_signals")
        .select("id, product_id, product_group_id, quantity, status, multi_product_pool_id")
        .eq("cart_id", cart_id)
        .in_("status", ["abandoned", "pooled"])
        .execute()
        .data
    )
    
    if not signals:
        return
        
    # Check for idempotency: if already processed, return
    if any(s.get("multi_product_pool_id") for s in signals):
        logger.info(f"Cart {cart_id} already processed for multi-product pooling.")
        return
        
    grouped_signals = [s for s in signals if s.get("product_group_id")]
    if len(grouped_signals) < 2:
        return
        
    # Aggregate quantities per product group
    group_qtys = {}
    representative_products = {}
    for s in grouped_signals:
        gid = s["product_group_id"]
        group_qtys[gid] = group_qtys.get(gid, 0) + s["quantity"]
        representative_products[gid] = s["product_id"]
        
    product_group_ids = list(group_qtys.keys())
    if len(product_group_ids) < 2:
        return
        
    # 2. Compute signature
    signature = compute_basket_signature(product_group_ids)
    
    # 3. Find active pool
    active_pools = (
        sb.table("multi_product_pools")
        .select("*")
        .eq("basket_signature", signature)
        .in_("status", ["open", "offers_generated"])
        .execute()
        .data
    )
    
    total_items = sum(s["quantity"] for s in signals)
    
    if active_pools:
        pool = active_pools[0]
        pool_id = pool["id"]
        
        # Update existing pool
        sb.table("multi_product_pools").update({
            "signal_count": pool["signal_count"] + len(signals),
            "cart_count": pool["cart_count"] + 1,
            "total_items": pool["total_items"] + total_items,
            "updated_at": now_iso()
        }).eq("id", pool_id).execute()
    else:
        # Create new pool
        from app.config import settings
        from datetime import timedelta
        
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=settings.POOL_WINDOW_HOURS)).isoformat()
        
        pool = sb.table("multi_product_pools").insert({
            "basket_signature": signature,
            "product_group_ids": product_group_ids,
            "signal_count": len(signals),
            "cart_count": 1,
            "total_items": total_items,
            "status": "open",
            "expires_at": expires_at,
            "min_carts_required": 1
        }).execute().data[0]
        pool_id = pool["id"]
        
    # 4. Upsert multi_product_pool_products
    for gid in product_group_ids:
        existing = (
            sb.table("multi_product_pool_products")
            .select("*")
            .eq("multi_product_pool_id", pool_id)
            .eq("product_group_id", gid)
            .execute()
            .data
        )
        if existing:
            sb.table("multi_product_pool_products").update({
                "aggregated_qty": existing[0]["aggregated_qty"] + group_qtys[gid]
            }).eq("id", existing[0]["id"]).execute()
        else:
            sb.table("multi_product_pool_products").insert({
                "multi_product_pool_id": pool_id,
                "product_group_id": gid,
                "aggregated_qty": group_qtys[gid],
                "representative_product_id": representative_products[gid]
            }).execute()
            
    # 5. Mark signals and cart recovery
    signal_ids = [s["id"] for s in signals]
    # Update signals in chunks if needed, but usually < 10
    for sid in signal_ids:
        sb.table("demand_signals").update({
            "multi_product_pool_id": pool_id
        }).eq("id", sid).execute()
        
    sb.table("cart_recoveries").update({
        "pool_type": "multi",
        "multi_product_pool_id": pool_id
    }).eq("cart_id", cart_id).execute()
    
    # 6. Merchant coverage
    _select_merchants_by_coverage(pool_id, product_group_ids)
    
    # 7. Update co-occurrences
    _update_co_occurrences(product_group_ids)
    
    logger.info(f"Aggregated cart {cart_id} into multi_product_pool {pool_id}")
    return pool

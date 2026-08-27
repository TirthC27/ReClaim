"""
Demand aggregation + Section 9A merchant selection service.

Called by the abandonment worker when a cart is marked abandoned.
Aggregates demand signals per product_group into demand_pools and
selects which merchants should generate offers.
"""

import math
import logging
from uuid import UUID

from app.config import settings
from app.db.client import get_supabase

logger = logging.getLogger(__name__)


def aggregate_demand_for_group(product_group_id: str) -> dict | None:
    """
    Aggregate abandoned demand signals for a product group into a demand pool.

    1. Count abandoned signals for this group
    2. Upsert the demand_pool row with updated signal_count
    3. If threshold met, run Section 9A merchant selection
    4. Return the updated pool
    """
    sb = get_supabase()
    group_id = str(product_group_id)

    # ── 1. Count abandoned signals ───────────────────────────
    signals = (
        sb.table("demand_signals")
        .select("id, merchant_id")
        .eq("product_group_id", group_id)
        .eq("status", "abandoned")
        .execute()
        .data
    )
    signal_count = len(signals)

    if signal_count == 0:
        return None

    # ── 2. Upsert demand_pool ────────────────────────────────
    existing_pools = (
        sb.table("demand_pools")
        .select("*")
        .eq("product_group_id", group_id)
        .in_("status", ["open", "offers_generated"])
        .limit(1)
        .execute()
        .data
    )

    if existing_pools:
        pool = existing_pools[0]
        pool_id = pool["id"]
        sb.table("demand_pools").update({
            "signal_count": signal_count,
            "updated_at": "now()",
        }).eq("id", str(pool_id)).execute()
    else:
        result = sb.table("demand_pools").insert({
            "product_group_id": group_id,
            "signal_count": signal_count,
            "status": "open",
            "threshold": 1,
        }).execute().data
        pool_id = result[0]["id"]

    # ── 3. Check threshold ───────────────────────────────────
    # Refresh pool after update
    pool = (
        sb.table("demand_pools")
        .select("*")
        .eq("id", str(pool_id))
        .execute()
        .data[0]
    )

    threshold = pool.get("threshold", 1)

    if signal_count >= threshold:
        # ── 4. Section 9A merchant selection ──────────────────
        selected = _select_merchants_9a(group_id, signal_count)

        sb.table("demand_pools").update({
            "status": "offers_generated",
            "selected_merchant_ids": selected,
            "updated_at": "now()",
        }).eq("id", str(pool_id)).execute()

        # Mark signals as pooled
        sb.table("demand_signals").update({
            "status": "pooled",
        }).eq("product_group_id", group_id).eq("status", "abandoned").execute()

        logger.info(
            f"Pool {pool_id} for group {group_id}: "
            f"{signal_count} signals, {len(selected)} merchants selected"
        )

    return pool


def _select_merchants_9a(product_group_id: str, signal_count: int) -> list[str]:
    """
    Section 9A merchant selection algorithm.

    ┌─────────────────────────────────────────────────────────────────┐
    │  PLACEHOLDER THRESHOLDS — update when final Section 9A         │
    │  numbers are supplied:                                         │
    │                                                                │
    │  SMALL_POOL_THRESHOLD  (default 5):                            │
    │    Pools with fewer signals → pick single best-positioned      │
    │    merchant to generate one strong offer.                      │
    │                                                                │
    │  DEMAND_PER_MERCHANT  (default 5):                             │
    │    For larger pools → select ceil(signal_count / this_value)   │
    │    merchants, capped at total eligible.                        │
    └─────────────────────────────────────────────────────────────────┘
    """
    sb = get_supabase()

    # Get all eligible merchants for this product group
    eligible = (
        sb.table("merchant_products")
        .select("merchant_id, merchants(id, name, margin_floor_pct, is_active)")
        .eq("product_group_id", product_group_id)
        .execute()
        .data
    )

    # Filter to active merchants, deduplicate
    seen: set[str] = set()
    active_merchants: list[dict] = []
    for row in eligible:
        merchant = row.get("merchants")
        if not merchant:
            continue
        mid = str(merchant["id"])
        if mid in seen:
            continue
        if not merchant.get("is_active", True):
            continue
        seen.add(mid)
        active_merchants.append(merchant)

    if not active_merchants:
        return []

    # If only 1-2 merchants exist, select all of them regardless
    if len(active_merchants) <= 2:
        return [str(m["id"]) for m in active_merchants]

    # ── Section 9A selection logic ───────────────────────────
    # PLACEHOLDER: these constants come from config, pending final values
    small_threshold = settings.SMALL_POOL_THRESHOLD
    demand_per_merchant = settings.DEMAND_PER_MERCHANT

    if signal_count < small_threshold:
        # Small pool: pick the single best-positioned merchant
        # "Best-positioned" = highest margin_floor_pct headroom
        # (merchant willing to cut deepest while maintaining floor)
        best = _pick_best_merchant(active_merchants)
        return [str(best["id"])]
    else:
        # Larger pool: proportional selection
        num_to_select = min(
            len(active_merchants),
            math.ceil(signal_count / demand_per_merchant),
        )
        # Sort by margin headroom (lowest floor = most room to offer)
        sorted_merchants = sorted(
            active_merchants,
            key=lambda m: m.get("margin_floor_pct") or 0,
        )
        selected = sorted_merchants[:num_to_select]
        return [str(m["id"]) for m in selected]


def _pick_best_merchant(merchants: list[dict]) -> dict:
    """
    Pick the single best-positioned merchant for a small demand pool.

    Strategy: merchant with the lowest margin floor (most room to discount).
    Tie-break: alphabetical by name.
    """
    return min(
        merchants,
        key=lambda m: (m.get("margin_floor_pct") or 0, m.get("name", "")),
    )


def get_selected_merchants(pool_id: UUID) -> list[dict]:
    """Return full merchant details for the Section 9A-selected merchants of a pool."""
    sb = get_supabase()

    pool = (
        sb.table("demand_pools")
        .select("selected_merchant_ids")
        .eq("id", str(pool_id))
        .execute()
        .data
    )
    if not pool or not pool[0].get("selected_merchant_ids"):
        return []

    merchant_ids = pool[0]["selected_merchant_ids"]

    merchants = []
    for mid in merchant_ids:
        rows = (
            sb.table("merchants")
            .select("*")
            .eq("id", str(mid))
            .limit(1)
            .execute()
            .data
        )
        if rows:
            merchants.append(rows[0])

    return merchants

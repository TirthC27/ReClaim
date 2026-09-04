"""
Abandonment timeout worker.

Uses APScheduler to periodically check for carts that have been
active beyond ABANDONMENT_TIMEOUT_MINUTES, mark them as abandoned,
and trigger demand aggregation.
"""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.db.client import get_supabase
from app.services.aggregation import aggregate_demand_for_group, archive_expired_pools

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def check_abandoned_carts():
    """
    Periodic job: find timed-out active carts and process them.

    1. Query carts with status='active' older than timeout
    2. Skip any that were converted (orders/create webhook arrived)
    3. Mark remaining as abandoned
    4. Flip their demand_signals to 'abandoned'
    5. Trigger aggregation for each affected product_group
    """
    sb = get_supabase()
    timeout = settings.ABANDONMENT_TIMEOUT_MINUTES
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout)
    cutoff_iso = cutoff.isoformat()

    logger.debug(f"Checking for abandoned carts (cutoff: {cutoff_iso})")

    try:
        # Find active carts older than the timeout
        stale_carts = (
            sb.table("carts")
            .select("id, shopify_checkout_id")
            .eq("status", "active")
            .lt("created_at", cutoff_iso)
            .execute()
            .data
        )

        if not stale_carts:
            return

        logger.info(f"Found {len(stale_carts)} stale active carts to process")

        affected_groups: set[str] = set()

        for cart in stale_carts:
            cart_id = cart["id"]
            
            # Fetch the customer email from the cart to pass to the recovery
            cart_details = sb.table("carts").select("customer_email").eq("id", str(cart_id)).execute().data
            customer_email = cart_details[0].get("customer_email") if cart_details else None

            # ── Mark cart as abandoned ────────────────────────
            sb.table("carts").update({
                "status": "abandoned",
                "abandoned_at": "now()",
            }).eq("id", str(cart_id)).execute()

            # ── Flip demand_signals to 'abandoned' ───────────
            signals = (
                sb.table("demand_signals")
                .select("id, product_group_id")
                .eq("cart_id", str(cart_id))
                .eq("status", "pending")
                .execute()
                .data
            )

            for signal in signals:
                sb.table("demand_signals").update({
                    "status": "abandoned",
                }).eq("id", signal["id"]).execute()

                if signal.get("product_group_id"):
                    affected_groups.add(signal["product_group_id"])

            # ── Create cart_recoveries record ───────────────
            if signals:
                existing_recovery = (sb.table("cart_recoveries").select("id")
                    .eq("cart_id", str(cart_id)).order("created_at", desc=True)
                    .limit(1).execute().data)
                if existing_recovery:
                    recovery_id = existing_recovery[0]["id"]
                    sb.table("cart_recoveries").update({
                        "customer_email": customer_email,
                    }).eq("id", recovery_id).execute()
                    rec_result = [{"id": recovery_id}]
                    logger.info("Reusing cart_recovery %s for cart %s", recovery_id, cart_id)
                else:
                    recovery = {
                        "cart_id": str(cart_id),
                        "customer_email": customer_email,
                        "status": "awaiting_offers",
                        "expires_at": (datetime.now(timezone.utc) + timedelta(
                            hours=settings.POOL_WINDOW_HOURS
                        )).isoformat(),
                    }
                    rec_result = sb.table("cart_recoveries").insert(recovery).execute().data
                if rec_result:
                    recovery_id = rec_result[0]["id"]
                    # Insert items
                    linked = (sb.table("cart_recovery_items").select("demand_signal_id")
                              .eq("cart_recovery_id", recovery_id).execute().data)
                    linked_ids = {row["demand_signal_id"] for row in linked}
                    recovery_items = []
                    for sig in signals:
                        if sig["id"] not in linked_ids:
                            recovery_items.append({
                                "cart_recovery_id": recovery_id,
                                "demand_signal_id": sig["id"]
                            })
                    if recovery_items:
                        sb.table("cart_recovery_items").insert(recovery_items).execute()

            logger.info(
                f"Cart {cart_id} abandoned: "
                f"{len(signals)} signals flipped"
            )

        # ── NEW: Multi-product pool classification ───────────
        from app.services.multi_product_aggregation import (
            classify_cart, aggregate_multi_product_demand
        )
        for cart in stale_carts:
            cart_id = str(cart["id"])
            cart_type = classify_cart(cart_id)
            if cart_type == "multi":
                try:
                    aggregate_multi_product_demand(cart_id)
                except Exception as exc:
                    logger.error(f"Multi-product aggregation failed for cart {cart_id}: {exc}")

        # ── Trigger aggregation for each affected group ──────
        for group_id in affected_groups:
            try:
                aggregate_demand_for_group(group_id)
            except Exception as exc:
                logger.error(
                    f"Aggregation failed for group {group_id}: {exc}"
                )

    except Exception as exc:
        logger.error(f"Abandonment check failed: {exc}")


def retry_failed_shopify_orders():
    sb = get_supabase()
    rows = (
        sb.table("orders")
        .select("id")
        .eq("status", "paid")
        .eq("order_creation_failed", True)
        .is_("shopify_order_id", "null")
        .limit(20)
        .execute()
        .data
    )
    if not rows:
        return

    from app.services.shopify_orders import create_shopify_order

    for row in rows:
        try:
            create_shopify_order(row["id"])
        except Exception as exc:
            logger.error(f"Retry Shopify order failed for {row['id']}: {exc}")


def expire_unpaid_offers():
    """
    Periodic job: Find orders in 'pending_payment' status older than PAYMENT_EXPIRY_HOURS,
    and mark them as 'expired'.
    """
    sb = get_supabase()
    timeout_hours = getattr(settings, "PAYMENT_EXPIRY_HOURS", 8)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)
    cutoff_iso = cutoff.isoformat()

    try:
        stale_orders = (
            sb.table("orders")
            .select("id")
            .eq("status", "pending_payment")
            .lt("created_at", cutoff_iso)
            .execute()
            .data
        )

        if not stale_orders:
            return

        logger.info(f"Found {len(stale_orders)} expired unpaid orders")

        for order in stale_orders:
            sb.table("orders").update({"status": "expired"}).eq("id", order["id"]).execute()
            sb.table("payments").update({"status": "failed"}).eq("order_id", order["id"]).execute()
            
    except Exception as exc:
        logger.error(f"Expire unpaid offers check failed: {exc}")


def start_scheduler():
    """Start the APScheduler background scheduler."""
    global _scheduler

    if _scheduler is not None:
        return  # Already running

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        check_abandoned_carts,
        "interval",
        minutes=1,  # Check every minute
        id="abandonment_checker",
        replace_existing=True,
    )
    _scheduler.add_job(
        retry_failed_shopify_orders,
        "interval",
        minutes=1,
        id="shopify_order_retry",
        replace_existing=True,
    )
    _scheduler.add_job(
        expire_unpaid_offers,
        "interval",
        minutes=15,
        id="expire_unpaid_offers",
        replace_existing=True,
    )
    _scheduler.add_job(
        archive_expired_pools,
        "interval",
        minutes=15,
        id="archive_expired_pools",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        f"Abandonment worker started "
        f"(checking every 1 min, timeout={settings.ABANDONMENT_TIMEOUT_MINUTES} min)"
    )


def stop_scheduler():
    """Gracefully stop the scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Abandonment worker stopped")

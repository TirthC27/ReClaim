"""Trace a cart by customer email through the full pipeline."""
import os
os.environ["PYTHONIOENCODING"] = "utf-8"

from app.db.client import get_supabase
from app.config import settings
from datetime import datetime, timezone

sb = get_supabase()
EMAIL = "fayeve9933@slotbeer.com"

# ── STEP 1: Find cart ────────────────────────────────────────
print("=" * 80)
print(f"STEP 1: carts where customer_email = {EMAIL}")
print("=" * 80)
carts = sb.table("carts").select("*").eq("customer_email", EMAIL).order("created_at", desc=True).execute().data
if not carts:
    print("  NO CARTS FOUND for this email")
    print()
    print("  Checking most recent carts in DB:")
    recent = sb.table("carts").select("id, shopify_checkout_id, customer_email, status, created_at").order("created_at", desc=True).limit(10).execute().data
    for c in recent:
        print(f"    email={c.get('customer_email')}  status={c.get('status')}  "
              f"created={c.get('created_at')}  checkout_id={c.get('shopify_checkout_id')}")
else:
    for cart in carts:
        for k, v in cart.items():
            print(f"  {k}: {v}")
        print()

    # ── STEP 2: Timing ───────────────────────────────────────
    cart = carts[0]  # most recent
    cart_id = str(cart["id"])
    print("=" * 80)
    print("STEP 2: Timing analysis")
    print("=" * 80)
    created = cart.get("created_at", "")
    print(f"  created_at: {created}")
    print(f"  status: {cart.get('status')}")
    print(f"  abandoned_at: {cart.get('abandoned_at')}")
    print(f"  converted_at: {cart.get('converted_at')}")
    print(f"  ABANDONMENT_TIMEOUT_MINUTES: {settings.ABANDONMENT_TIMEOUT_MINUTES}")
    if created:
        try:
            from dateutil import parser as dp
            ct = dp.isoparse(created)
            now = datetime.now(timezone.utc)
            elapsed = (now - ct).total_seconds() / 60
            print(f"  elapsed since creation: {elapsed:.1f} minutes")
            print(f"  past timeout threshold: {elapsed > settings.ABANDONMENT_TIMEOUT_MINUTES}")
        except Exception as e:
            print(f"  timing error: {e}")
    print()

    # ── STEP 3: demand_signals ────────────────────────────────
    print("=" * 80)
    print(f"STEP 3: demand_signals where cart_id = {cart_id}")
    print("=" * 80)
    signals = sb.table("demand_signals").select("*").eq("cart_id", cart_id).execute().data
    if signals:
        for s in signals:
            for k, v in s.items():
                print(f"  {k}: {v}")
            print()
    else:
        print("  NO demand_signals found for this cart")
    print()

    # ── STEP 4: cart_recoveries ───────────────────────────────
    print("=" * 80)
    print(f"STEP 4: cart_recoveries where cart_id = {cart_id}")
    print("=" * 80)
    try:
        recoveries = sb.table("cart_recoveries").select("*").eq("cart_id", cart_id).execute().data
        if recoveries:
            for r in recoveries:
                for k, v in r.items():
                    print(f"  {k}: {v}")
                print()
        else:
            print("  NO cart_recoveries found for this cart")
    except Exception as e:
        print(f"  Error: {e}")
    print()

    # ── STEP 5: Check if demand_pool exists for this group ────
    if signals:
        group_ids = set(s.get("product_group_id") for s in signals if s.get("product_group_id"))
        print("=" * 80)
        print(f"STEP 5: demand_pools for product groups: {group_ids}")
        print("=" * 80)
        for gid in group_ids:
            pools = sb.table("demand_pools").select("id, product_group_id, signal_count, status, selected_merchant_ids, created_at").eq("product_group_id", gid).execute().data
            for p in pools:
                selected = p.get("selected_merchant_ids") or []
                pid = p["id"][:12]
                print(f"  Pool {pid}  signals={p['signal_count']}  status={p['status']}  selected_count={len(selected)}")
            if not pools:
                print(f"  No pools for group {gid}")
        print()

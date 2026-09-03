"""Deep audit: merchant selection scaling with real vendor count."""
import os, math
os.environ["PYTHONIOENCODING"] = "utf-8"

from app.db.client import get_supabase
from app.config import settings

sb = get_supabase()

# ── Step 2+4: selected_merchant_ids per pool ──────────────────
print("=" * 80)
print("STEP 2+4: selected_merchant_ids for every pool")
print("=" * 80)

pools = sb.table("demand_pools").select(
    "id, product_group_id, signal_count, status, selected_merchant_ids, created_at, updated_at, negotiation_status"
).execute().data

for p in pools:
    selected = p.get("selected_merchant_ids") or []
    pid_short = p["id"][:8]
    gid_short = p["product_group_id"][:8]
    print(f"  pool {pid_short}  group={gid_short}  signals={p['signal_count']}  status={p['status']}")
    print(f"  negotiation_status: {p.get('negotiation_status')}")
    print(f"  selected_merchant_ids count={len(selected)}")
    print(f"  created_at: {p['created_at']}")
    print(f"  updated_at: {p.get('updated_at')}")
    for mid in selected:
        m = sb.table("merchants").select("name").eq("id", mid).execute().data
        name = m[0]["name"] if m else "UNKNOWN"
        print(f"    -> {mid} = {name}")

    # Manual formula check
    sc = p["signal_count"]
    gid = p["product_group_id"]
    mp_rows = sb.table("merchant_products").select(
        "merchant_id, merchants(id, name, is_active)"
    ).eq("product_group_id", gid).execute().data

    # Deduplicate active merchants (same logic as _select_merchants_9a)
    seen = set()
    active = []
    for row in mp_rows:
        merchant = row.get("merchants")
        if not merchant:
            continue
        mid2 = str(merchant["id"])
        if mid2 in seen:
            continue
        if not merchant.get("is_active", True):
            continue
        seen.add(mid2)
        active.append(merchant)

    print(f"  eligible active merchants for this group: {len(active)}")
    for a in active:
        print(f"    - {a['name']} ({a['id'][:8]})")

    # What formula SHOULD produce
    if len(active) <= 2:
        expected = len(active)
        reason = f"<=2 eligible, select all"
    elif sc < settings.SMALL_POOL_THRESHOLD:
        expected = 1
        reason = f"signal_count {sc} < SMALL_POOL_THRESHOLD {settings.SMALL_POOL_THRESHOLD} -> pick 1 best"
    else:
        expected = min(len(active), math.ceil(sc / settings.DEMAND_PER_MERCHANT))
        reason = f"ceil({sc}/{settings.DEMAND_PER_MERCHANT})={math.ceil(sc / settings.DEMAND_PER_MERCHANT)}, capped at {len(active)} eligible"

    actual = len(selected)
    match = "MATCH" if actual == expected else "MISMATCH"
    print(f"  FORMULA: expected={expected} ({reason}) vs actual={actual} -> {match}")
    print()


# ── Step 5: staleness check ───────────────────────────────────
print("=" * 80)
print("STEP 5: Pool creation vs merchant_products creation timestamps")
print("=" * 80)

for p in pools:
    gid = p["product_group_id"]
    pid_short = p["id"][:8]
    pool_created = p["created_at"]
    pool_updated = p.get("updated_at")

    mp_rows = sb.table("merchant_products").select(
        "merchant_id, created_at, merchants(name)"
    ).eq("product_group_id", gid).execute().data

    print(f"  Pool {pid_short} created_at={pool_created}  updated_at={pool_updated}")
    stale_count = 0
    for mp in mp_rows:
        mname = mp.get("merchants", {}).get("name", "?") if mp.get("merchants") else "?"
        mp_created = mp.get("created_at", "unknown")
        is_after = mp_created > pool_created if mp_created != "unknown" else "unknown"
        flag = " [ADDED AFTER POOL]" if is_after == True else ""
        if is_after == True:
            stale_count += 1
        print(f"    {mname}: created_at={mp_created}{flag}")

    if stale_count > 0:
        print(f"    ** {stale_count} merchants were added AFTER pool was created -> STALE SELECTION possible")
    else:
        print(f"    All merchants existed before pool creation")
    print()


# ── Config dump ───────────────────────────────────────────────
print("=" * 80)
print("STEP 3 supplement: Active config values")
print("=" * 80)
print(f"  SMALL_POOL_THRESHOLD = {settings.SMALL_POOL_THRESHOLD}")
print(f"  DEMAND_PER_MERCHANT  = {settings.DEMAND_PER_MERCHANT}")
print(f"  TIE_TOLERANCE_PCT    = {settings.TIE_TOLERANCE_PCT}")

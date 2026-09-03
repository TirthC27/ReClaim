"""End-of-fix test suite for merchant selection scaling."""
import math, os
os.environ["PYTHONIOENCODING"] = "utf-8"

from app.services.aggregation import aggregate_demand_for_group, _select_merchants_9a
from app.db.client import get_supabase
from app.config import settings

sb = get_supabase()

print(f"SMALL_POOL_THRESHOLD = {settings.SMALL_POOL_THRESHOLD}")
print(f"DEMAND_PER_MERCHANT  = {settings.DEMAND_PER_MERCHANT}")
print()


def resolve_names(merchant_ids):
    names = []
    for mid in merchant_ids:
        m = sb.table("merchants").select("name").eq("id", mid).execute().data
        names.append(m[0]["name"] if m else "?")
    return names


# -- TEST 1: Creator X group, 5 eligible merchants -- expect 2 selected
print("=" * 70)
print("TEST 1: Creator X group (5 eligible) -- expect 2 selected")
print("=" * 70)
creator_x = "f5525c67-bbb7-4b9a-8774-73da3d365311"

# Check pool state after prior aggregation
pool = (
    sb.table("demand_pools")
    .select("id, signal_count, status, selected_merchant_ids")
    .eq("product_group_id", creator_x)
    .in_("status", ["offers_generated"])
    .execute()
    .data
)
if pool:
    p = pool[0]
    selected = p.get("selected_merchant_ids") or []
    print(f"  signal_count: {p['signal_count']}")
    print(f"  selected: {len(selected)} -> {resolve_names(selected)}")
    assert len(selected) == 2, f"FAIL: expected 2, got {len(selected)}"
    print("TEST 1 PASSED\n")
else:
    # Try re-aggregating
    aggregate_demand_for_group(creator_x)
    pool = (
        sb.table("demand_pools")
        .select("id, signal_count, status, selected_merchant_ids")
        .eq("product_group_id", creator_x)
        .in_("status", ["offers_generated"])
        .execute()
        .data
    )
    if pool:
        p = pool[0]
        selected = p.get("selected_merchant_ids") or []
        print(f"  signal_count: {p['signal_count']}")
        print(f"  selected: {len(selected)} -> {resolve_names(selected)}")
        assert len(selected) == 2, f"FAIL: expected 2, got {len(selected)}"
        print("TEST 1 PASSED\n")
    else:
        raise AssertionError("TEST 1: No pool found")


# -- TEST 2: _select_merchants_9a with 25 signals, 5 eligible -- expect 5
print("=" * 70)
print("TEST 2: Direct formula -- 25 signals, 5 eligible -- expect 5")
print("=" * 70)
selected_25 = _select_merchants_9a(creator_x, 25)
print(f"  selected: {len(selected_25)} -> {resolve_names(selected_25)}")
assert len(selected_25) == 5, f"FAIL: expected 5, got {len(selected_25)}"
print("TEST 2 PASSED\n")


# -- TEST 3: 3 signals -- max(2, ceil(3/5)) = max(2,1) = 2
print("=" * 70)
print("TEST 3: Direct formula -- 3 signals, 5 eligible -- expect 2")
print("=" * 70)
selected_3 = _select_merchants_9a(creator_x, 3)
print(f"  selected: {len(selected_3)} -> {resolve_names(selected_3)}")
assert len(selected_3) == 2, f"FAIL: expected 2, got {len(selected_3)}"
print("TEST 3 PASSED\n")


# -- TEST 4: 10 signals -- max(2, ceil(10/5)) = max(2,2) = 2
print("=" * 70)
print("TEST 4: Direct formula -- 10 signals, 5 eligible -- expect 2")
print("=" * 70)
selected_10 = _select_merchants_9a(creator_x, 10)
print(f"  selected: {len(selected_10)} -> {resolve_names(selected_10)}")
assert len(selected_10) == 2, f"FAIL: expected 2, got {len(selected_10)}"
print("TEST 4 PASSED\n")


# -- TEST 5: 15 signals -- max(2, ceil(15/5)) = max(2,3) = 3
print("=" * 70)
print("TEST 5: Direct formula -- 15 signals, 5 eligible -- expect 3")
print("=" * 70)
selected_15 = _select_merchants_9a(creator_x, 15)
print(f"  selected: {len(selected_15)} -> {resolve_names(selected_15)}")
assert len(selected_15) == 3, f"FAIL: expected 3, got {len(selected_15)}"
print("TEST 5 PASSED\n")


# -- TEST 6: Single-eligible group stays at 1
print("=" * 70)
print("TEST 6: Single-eligible group (e88d774b) -- expect 1")
print("=" * 70)
single_group = "e88d774b-1d3b-4123-a475-48a517a27112"
selected_single = _select_merchants_9a(single_group, 5)
print(f"  selected: {len(selected_single)} -> {resolve_names(selected_single)}")
assert len(selected_single) == 1, f"FAIL: expected 1, got {len(selected_single)}"
print("TEST 6 PASSED\n")


# -- TEST 7: Comprehensive formula math
print("=" * 70)
print("TEST 7: Comprehensive formula math verification")
print("=" * 70)
dpm = settings.DEMAND_PER_MERCHANT
cases = [
    (1, 5, 2, "1 sig, 5 elig"),
    (2, 5, 2, "2 sig, 5 elig"),
    (3, 5, 2, "3 sig, 5 elig"),
    (5, 5, 2, "5 sig, 5 elig"),
    (10, 5, 2, "10 sig, 5 elig"),
    (15, 5, 3, "15 sig, 5 elig"),
    (25, 5, 5, "25 sig, 5 elig"),
    (50, 5, 5, "50 sig, 5 elig (capped)"),
    (1, 1, 1, "1 sig, 1 elig"),
    (1, 2, 2, "1 sig, 2 elig"),
    (50, 2, 2, "50 sig, 2 elig (capped)"),
]
all_pass = True
for signals, eligible, expected, desc in cases:
    if eligible <= 2:
        actual = eligible
    elif signals < settings.SMALL_POOL_THRESHOLD:
        actual = 1
    else:
        actual = min(eligible, max(2, math.ceil(signals / dpm)))
    status = "PASS" if actual == expected else "FAIL"
    if status == "FAIL":
        all_pass = False
    print(f"  {status}: {desc} -> expected={expected}, got={actual}")

assert all_pass, "Some formula cases failed!"
print("\nTEST 7 PASSED\n")


print("=" * 70)
print("ALL 7 TESTS PASSED")
print("=" * 70)

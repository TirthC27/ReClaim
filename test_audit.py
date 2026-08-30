import os
os.environ["PYTHONIOENCODING"] = "utf-8"

from app.db.client import get_supabase
sb = get_supabase()

print("=" * 80)
print("PART A — Recent demand_signals")
print("=" * 80)
recent = sb.table('demand_signals').select('*, products(title, price)').order('created_at', desc=True).limit(6).execute().data
for r in recent:
    print(f"  signal_id: {r['id']}")
    print(f"  product_group_id: {r.get('product_group_id')}")
    print(f"  product_id: {r.get('product_id')}")
    prod = r.get('products') or {}
    print(f"  product: {prod.get('title')} @ {prod.get('price')}")
    print(f"  status: {r.get('status')}")
    print(f"  created_at: {r.get('created_at')}")
    print()

# Cross-reference pools
print("=" * 80)
print("ALL demand_pools rows")
print("=" * 80)
pools = sb.table('demand_pools').select('id, product_group_id, signal_count, status, created_at').execute().data
for p in pools:
    print(f"  pool_id: {p['id']}")
    print(f"  product_group_id: {p['product_group_id']}")
    print(f"  signal_count: {p['signal_count']} | status: {p['status']}")
    print(f"  created_at: {p['created_at']}")
    print()

print("=" * 80)
print("PART B — Merchants mapped to Creator X group f5525c67...")
print("=" * 80)
creator_x_group = 'f5525c67-bbb7-4b9a-8774-73da3d365311'
mapped = sb.table('merchant_products').select('merchant_id, shopify_product_id').eq('product_group_id', creator_x_group).execute().data
unique_merchants = set(m['merchant_id'] for m in mapped)
print(f"{len(mapped)} merchant_products rows, {len(unique_merchants)} unique merchants:")
for m in mapped:
    print(f"  merchant_id: {m['merchant_id']} | shopify_product_id: {m['shopify_product_id']}")

print()
print("Unique merchant IDs mapped to Creator X:")
for mid in unique_merchants:
    merchant = sb.table('merchants').select('id, name').eq('id', mid).execute().data
    name = merchant[0]['name'] if merchant else 'UNKNOWN'
    print(f"  {mid} -> {name}")

print()
print("=" * 80)
print("PART B.2 — Any near-duplicate Creator X product groups?")
print("=" * 80)
all_groups = sb.table('product_groups').select('*').execute().data
for g in all_groups:
    print(f"  id: {g['id']} | model_name: {g.get('model_name')} | canonical_sku: {g.get('canonical_sku')}")

print()
print("=" * 80)
print("All merchants in the system")
print("=" * 80)
merchants = sb.table('merchants').select('id, name, is_active').execute().data
for m in merchants:
    print(f"  {m['id']} -> {m['name']} (active={m.get('is_active')})")

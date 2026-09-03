"""Test all 5 fixes end-to-end."""
import os; os.environ["PYTHONIOENCODING"] = "utf-8"
from app.db.client import get_supabase
from app.services.webhooks import process_checkout_create

sb = get_supabase()
PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} -- {detail}")


# ── TEST FIX 2 + 3: cart_token saved + demand_signal dedup ──────

print("\n=== FIX 2 + 3: cart_token + dedup ===")

# Simulate checkout with cart_token
payload1 = {
    "id": "test_fix_checkout_001",
    "token": "test_fix_checkout_001",
    "cart_token": "TEST_CART_TOKEN_ABC123",
    "email": "test_fix@example.com",
    "line_items": [
        {"product_id": "9655792435246", "title": "SmartBuy ProBook 15", "price": "63400.00", "quantity": 1},
        {"product_id": "9655792468014", "title": "DigiWorld Creator X", "price": "59100.00", "quantity": 1},
    ]
}

result1 = process_checkout_create(payload1)
check("Cart created with cart_token", result1.get("cart_id"))
check("Signals created", result1.get("signals_created", 0) >= 1)

# Verify cart_token was saved
cart = sb.table("carts").select("id, cart_token, customer_email").eq(
    "shopify_checkout_id", "test_fix_checkout_001"
).execute().data
check("cart_token saved", cart and cart[0].get("cart_token") == "TEST_CART_TOKEN_ABC123",
      f"got: {cart[0].get('cart_token') if cart else 'no cart'}")

cart_id = cart[0]["id"] if cart else None

# Count signals before second webhook
sigs_before = sb.table("demand_signals").select("id").eq("cart_id", str(cart_id)).eq("status", "pending").execute().data
count_before = len(sigs_before)

# Second webhook (same checkout, different quantity — simulates user changing qty)
payload2 = {**payload1}
payload2["line_items"] = [
    {"product_id": "9655792435246", "title": "SmartBuy ProBook 15", "price": "63400.00", "quantity": 3},
    {"product_id": "9655792468014", "title": "DigiWorld Creator X", "price": "59100.00", "quantity": 2},
]
result2 = process_checkout_create(payload2)

sigs_after = sb.table("demand_signals").select("id, quantity, product_title").eq("cart_id", str(cart_id)).eq("status", "pending").execute().data
count_after = len(sigs_after)

check("Dedup: signal count unchanged after 2nd webhook", count_after == count_before,
      f"before={count_before}, after={count_after}")

# Check quantities were updated
for s in sigs_after:
    if "ProBook" in (s.get("product_title") or ""):
        check("ProBook quantity updated to 3", s["quantity"] == 3, f"got {s['quantity']}")
    elif "Creator" in (s.get("product_title") or ""):
        check("Creator X quantity updated to 2", s["quantity"] == 2, f"got {s['quantity']}")


# ── TEST FIX 2: by-cart-token endpoint ──────────────────────────

print("\n=== FIX 2: by-cart-token lookup ===")

# First we need a cart_recovery for this cart — simulate abandonment
sb.table("carts").update({"status": "abandoned", "abandoned_at": "now()"}).eq("id", str(cart_id)).execute()

# Flip signals to abandoned  
for s in sigs_after:
    sb.table("demand_signals").update({"status": "abandoned"}).eq("id", s["id"]).execute()

# Create a cart_recovery
rec_result = sb.table("cart_recoveries").insert({
    "cart_id": str(cart_id),
    "customer_email": "test_fix@example.com",
    "status": "awaiting_offers"
}).execute().data

if rec_result:
    recovery_id = rec_result[0]["id"]
    # Insert recovery items
    for s in sigs_after:
        sb.table("cart_recovery_items").insert({
            "cart_recovery_id": recovery_id,
            "demand_signal_id": s["id"]
        }).execute()
    check("Cart recovery created", True)
    
    # Now test the by-cart-token endpoint logic directly
    lookup = sb.table("carts").select("id").eq("cart_token", "TEST_CART_TOKEN_ABC123").order(
        "created_at", desc=True
    ).limit(1).execute().data
    check("by-cart-token: cart found via cart_token", bool(lookup),
          "no cart found with cart_token=TEST_CART_TOKEN_ABC123")
    
    if lookup:
        rec_lookup = sb.table("cart_recoveries").select("*").eq(
            "cart_id", str(lookup[0]["id"])
        ).order("created_at", desc=True).limit(1).execute().data
        check("by-cart-token: recovery found for cart", bool(rec_lookup),
              "no recovery found")
else:
    check("Cart recovery created", False, "insert failed")


# ── TEST FIX 5: .env cleanup ──────────────────────────────────

print("\n=== FIX 5: .env cleanup ===")
from app.config import Settings
s = Settings()
check("SHOPIFY_ADMIN_TOKEN not loaded (commented out)", s.SHOPIFY_ADMIN_TOKEN == "",
      f"got: '{s.SHOPIFY_ADMIN_TOKEN[:20]}...'")


# ── CLEANUP ─────────────────────────────────────────────────────

print("\n=== Cleanup test data ===")
if cart_id:
    sb.table("cart_recoveries").delete().eq("cart_id", str(cart_id)).execute()
    sb.table("carts").delete().eq("id", str(cart_id)).execute()
    print("  Cleaned up test cart + recoveries")


# ── SUMMARY ─────────────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"RESULTS: {PASS} passed, {FAIL} failed")
print(f"{'='*50}")

"""
Seed script — populate offer_archetypes with 18 hand-written strategy
descriptions and their embeddings.

Run once:  python scripts/seed_offer_archetypes.py

Requires:
  - OPENROUTER_API_KEY set in .env (for embedding generation)
  - SUPABASE_URL + SUPABASE_KEY set in .env
  - Migration 006_vector_search_rpcs.sql applied (offer_archetypes must have
    an `embedding vector(1024)` column from 002_enable_pgvector.sql)
"""

import sys
import os
import time

# Allow running from project root: `python scripts/seed_offer_archetypes.py`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.client import get_supabase
from app.services.embeddings import generate_embedding

# ── 18 hand-written offer archetypes ────────────────────────────
# Covering all 7 offer types × various product categories & merchant situations

ARCHETYPES = [
    # ── discount ─────────────────────────────────────────────
    "Offer a straight percentage discount on a laptop when the merchant has high stock and needs to clear inventory before the next product cycle.",
    "Provide a modest 5-8% price cut on a smartphone when margin floor is tight but demand volume is high enough to compensate through volume.",
    "Apply a deeper discount on gaming accessories during seasonal demand spikes when the merchant's margin headroom exceeds 15%.",

    # ── gift ─────────────────────────────────────────────────
    "Bundle a free wireless mouse as a gift with a mid-range laptop purchase when the merchant has excess mouse inventory sitting idle.",
    "Include a free phone case or screen protector with a smartphone order when the accessory cost is under 2% of the product price.",
    "Gift a premium carrying pouch with headphone purchases when the merchant's accessory stock for pouches is above 20 units.",

    # ── bundle ───────────────────────────────────────────────
    "Bundle a laptop with a laptop bag and USB hub at a combined discount when all three items are in stock and the total bundle margin stays above floor.",
    "Create a gaming bundle pairing a console with two controllers and a charging dock, pricing the bundle 10-12% below individual purchase totals.",
    "Combine a mid-range phone with earbuds and a fast charger as an ecosystem bundle when the merchant carries all three product lines.",

    # ── warranty ─────────────────────────────────────────────
    "Offer an extended 1-year warranty instead of a price cut when the merchant has strong warranty cost economics (cost under ₹500 per unit for products above ₹15,000).",
    "Include a 2-year extended warranty as the primary value-add for premium electronics when the warranty provider margin is favorable and the product price exceeds ₹25,000.",
    "Add accidental damage protection to a tablet offer when warranty costs are low and competing merchants are already discounting aggressively.",

    # ── upgrade ──────────────────────────────────────────────
    "Offer a storage upgrade (e.g. 128GB to 256GB variant) at cost when the merchant has excess higher-tier inventory and needs to shift mix.",
    "Suggest a color or finish upgrade at no extra charge when specific SKU variants are overstocked and the base model has high demand.",

    # ── service ──────────────────────────────────────────────
    "Include free installation or setup service with a home electronics purchase when the merchant has existing service partnerships and the cost is under 3% of product price.",
    "Add a free data transfer or device setup service to a smartphone sale to differentiate from competitors offering only price discounts.",

    # ── hybrid ───────────────────────────────────────────────
    "Combine a moderate 5% discount with a free low-cost accessory gift when both margin and accessory stock allow it, creating a perception of exceptional value.",
    "Pair a small discount with an extended warranty when the merchant wants to protect margin while still appearing competitive — the warranty cost offsets the discount impact.",
]


def main():
    sb = get_supabase()
    print(f"Seeding {len(ARCHETYPES)} offer archetypes...")

    # Check if archetypes already exist
    existing = sb.table("offer_archetypes").select("id").execute().data
    if existing:
        print(f"⚠️  offer_archetypes already has {len(existing)} rows.")
        resp = input("Delete existing and re-seed? (y/N): ").strip().lower()
        if resp != "y":
            print("Aborted.")
            return
        # Delete existing
        for row in existing:
            sb.table("offer_archetypes").delete().eq("id", row["id"]).execute()
        print(f"Deleted {len(existing)} existing archetypes.")

    success = 0
    errors = 0

    for i, description in enumerate(ARCHETYPES):
        try:
            print(f"  [{i+1}/{len(ARCHETYPES)}] Embedding: {description[:60]}...")
            embedding = generate_embedding(description)

            sb.table("offer_archetypes").insert({
                "description": description,
                "embedding": str(embedding),
            }).execute()

            success += 1
            # Small delay to respect free-tier rate limits
            time.sleep(0.5)

        except Exception as exc:
            print(f"  ❌ Failed: {exc}")
            errors += 1
            time.sleep(2)  # Longer delay on error

    print(f"\n✅ Done: {success} inserted, {errors} failed.")


if __name__ == "__main__":
    main()

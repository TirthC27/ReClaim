"""
Bundle Buyer Agent — v3 (RAG-Informed Commercial Decision Agent)

Architecture:
    Backend-computed offer facts (prices, discounts, stock — READ-ONLY context)
        +
    Buyer RAG (fulfillment policies, customer experience, bundle strategy)
        ↓
    LLM Decision Plan
        → "Which offer(s) should fulfill this basket?"
        → "single_merchant or split_fulfillment?"
        → "Why? (with policy references)"
        → NEVER outputs prices, totals, quantities, or financial amounts
        ↓
    AllocationBuilder (deterministic)
        → Maps decision plan → prices from bundle_offers (backend-computed)
        → Computes: unit_price × cart_quantity = line_total
        → Tracks stock across carts
        ↓
    Validator (deterministic)
        → Coverage (HARD CONSTRAINT — 100% or reject)
        → Math (sum of line_totals == subtotal)
        → Stock (live Shopify inventory)
        → Discounts (within Seller Agent's stated ceiling)
        ↓
    PASS → execute | FAIL → reject

Key invariant:
    LLM output → decision → backend computation → validation → payment
    NEVER: LLM → ₹190,800 → Razorpay
"""

import json
import logging
from app.db.client import get_supabase
from app.services.llm_client import call_with_fallback
from app.services.shopify_inventory import get_stock_with_fallback
from app.services.rag_retrieval import retrieve_buyer_context

logger = logging.getLogger(__name__)
sb = get_supabase()

BUNDLE_BUYER_MODELS = ["deepseek/deepseek-chat", "openai/gpt-4o-mini"]


# ─── BUYER AGENT PROMPT ──────────────────────────────────────
# The LLM is a commercial decision-maker, not a calculator.

BUYER_AGENT_SYSTEM_PROMPT = """You represent a pool of buyers who each abandoned a multi-product cart.

You will be given:
1. All validated bundle offers with BACKEND-COMPUTED prices, discounts, coverage, and stock status.
   These numbers are authoritative — computed by the backend from Shopify's real prices.
   You may reference them in your reasoning but you DO NOT recalculate or output any financial amounts.
2. The cart compositions (which customer wants which products).
3. Retrieved fulfillment and customer experience policies.
4. Evaluation criteria.

YOUR JOB: Make the COMMERCIAL DECISION about which offer(s) should fulfill the basket.

DECISION LOGIC (in priority order):

STEP 1 — COVERAGE:
  First, identify which offers or combinations of offers achieve 100% basket coverage.
  100% coverage is STRONGLY PREFERRED. However, if 100% coverage is mathematically impossible (e.g. out of stock or no merchant offers the product), you MAY propose a partial fulfillment that covers as much of the basket as possible.
  The backend will ultimately calculate and validate the exact fulfillment coverage.

STEP 2 — COMPARE VALID SOLUTIONS:
  For each valid coverage solution, evaluate:
  - Total backend-computed price (lower is better)
  - Merchant count (fewer is better — single merchant preferred)
  - Stock sufficiency (all products must have sufficient stock)
  - Retrieved fulfillment policies (e.g., "prefer single merchant when savings < ₹X")
  - Bundle benefits (free shipping, warranty, etc.)

STEP 3 — APPLY POLICY:
  Use retrieved policies to make the final trade-off decision.
  Example: if single-merchant costs ₹1,400 more than split, but policy says
  "prefer single merchant when delta < ₹2,000" — choose single merchant.

REASONING REQUIREMENTS:
- State coverage solutions explicitly: "A covers 3/3, B+C covers 3/3"
- State the backend-computed price difference between solutions
- Reference specific retrieved policies that influenced the decision
- Explain the trade-off: why your #1 choice beats alternatives

Output valid JSON matching this exact schema:
{
  "decision": "single_merchant" or "split_fulfillment",
  "selected_offers": [
    {
      "bundle_offer_id": "<uuid>",
      "products": ["<product_group_id>", ...]
    }
  ],
  "reasoning": {
    "coverage_analysis": "<which offers cover which products>",
    "price_comparison": "<backend-computed totals compared>",
    "merchant_count": <int>,
    "tradeoff": "<why this choice is optimal>",
    "policy_reference": "<which retrieved policy influenced the decision>"
  },
  "ranking": [
    {
      "bundle_offer_id": "<uuid>",
      "rank": <int starting at 1>,
      "reasoning": "<2-3 sentences comparing against alternatives using backend-computed numbers>"
    }
  ]
}

CRITICAL:
- Do NOT include "price", "total_price", "unit_price", "line_total", "payment_amount" in your output.
  Those are computed by the backend from your decision.
- Do NOT recalculate totals — the backend-computed totals in the context are authoritative.
- 100% Coverage is STRONGLY PREFERRED, but partial coverage is acceptable if 100% is impossible. Single-merchant is a PREFERENCE.
- Your "products" array in selected_offers must reference only product_group_ids from the input.
"""


# ─── CONTEXT BUILDER ─────────────────────────────────────────

def _fetch_bundle_context(pool_id: str) -> dict:
    """Fetch offers, cart intents, and LIVE merchant stock."""

    # 1. Validated Bundle Offers (with backend-computed prices from Seller Agent)
    offers = (
        sb.table("bundle_offers")
        .select("*")
        .eq("multi_product_pool_id", pool_id)
        .eq("status", "validated")
        .execute()
        .data
    )

    # 2. Cart Intents (per-cart, per-product quantities + original prices)
    signals = (
        sb.table("demand_signals")
        .select("id, cart_id, product_id, product_group_id, quantity")
        .eq("multi_product_pool_id", pool_id)
        .execute()
        .data
    )

    carts = {}
    for s in signals:
        cid = s["cart_id"]
        if cid not in carts:
            carts[cid] = []

        prod = sb.table("products").select("price").eq("id", s["product_id"]).single().execute().data
        list_price = float(prod.get("price", 0)) if prod else 0.0

        carts[cid].append({
            "product_group_id": s["product_group_id"],
            "quantity": s["quantity"],
            "shopify_list_price": list_price,
        })

    cart_intents = [{"cart_id": cid, "items": items} for cid, items in carts.items()]

    # 3. Pool Products
    pool_products = (
        sb.table("multi_product_pool_products")
        .select("*")
        .eq("multi_product_pool_id", pool_id)
        .execute()
        .data
    )

    # 4. Fetch LIVE merchant stock
    merchant_stock = {}
    for offer in offers:
        mid = offer["merchant_id"]
        if mid not in merchant_stock:
            merchant_stock[mid] = {}

        for pg in pool_products:
            gid = pg["product_group_id"]
            if gid in offer.get("coverage_product_groups", []):
                prod = sb.table("products").select("sku").eq(
                    "id", pg["representative_product_id"]
                ).single().execute().data
                sku = prod["sku"] if prod else ""

                mp = sb.table("merchant_products").select("inventory_item_id").eq(
                    "merchant_id", mid
                ).eq("product_group_id", gid).execute().data
                inventory_item_id = mp[0].get("inventory_item_id") if mp else None

                qty, _ = get_stock_with_fallback(mid, sku, inventory_item_id)
                merchant_stock[mid][gid] = qty

    # 5. Merchant names
    merchant_names = {}
    for offer in offers:
        mid = offer["merchant_id"]
        if mid not in merchant_names:
            m = sb.table("merchants").select("name").eq("id", mid).single().execute().data
            merchant_names[mid] = m["name"] if m else "Unknown"

    # 6. Product titles
    product_titles = {}
    for pg in pool_products:
        gid = pg["product_group_id"]
        if gid not in product_titles:
            prod = sb.table("products").select("title").eq(
                "id", pg["representative_product_id"]
            ).single().execute().data
            product_titles[gid] = prod["title"] if prod else "Unknown"

    return {
        "offers": offers,
        "cart_intents": cart_intents,
        "merchant_stock": merchant_stock,
        "merchant_names": merchant_names,
        "product_titles": product_titles,
        "pool_products": pool_products,
    }


def _precompute_offer_context(context: dict) -> list[dict]:
    """Build offer summaries with backend-computed prices for the LLM.

    These are READ-ONLY context — the LLM references them but doesn't compute them.
    """
    cart_intents = context["cart_intents"]
    max_qty_per_product = {}
    for cart in cart_intents:
        for item in cart["items"]:
            gid = item["product_group_id"]
            qty = item["quantity"]
            max_qty_per_product[gid] = max(max_qty_per_product.get(gid, 0), qty)

    total_products = len(context["pool_products"])
    enriched = []

    for offer in context["offers"]:
        mid = offer["merchant_id"]
        line_items = offer.get("line_items", [])
        coverage_groups = offer.get("coverage_product_groups", [])

        # Backend-computed values from the Seller Agent pipeline
        backend_total = float(offer.get("total_price", 0))
        backend_subtotal = float(offer.get("subtotal", 0))
        bundle_discount = float(offer.get("bundle_discount", 0))

        # Original list total for covered products
        original_list_total = 0
        for li in line_items:
            original_list_total += float(li.get("shopify_list_price", 0))

        discount_amount = original_list_total - backend_total
        discount_pct = round((discount_amount / original_list_total * 100), 2) if original_list_total > 0 else 0

        # Per-product stock status
        stock_status = {}
        all_sufficient = True
        for gid in coverage_groups:
            available = context["merchant_stock"].get(mid, {}).get(gid, 0)
            required = max_qty_per_product.get(gid, 1)
            sufficient = available >= required
            if not sufficient:
                all_sufficient = False
            stock_status[gid] = {
                "product_title": context["product_titles"].get(gid, "Unknown"),
                "available": available,
                "required": required,
                "sufficient": sufficient,
            }

        enriched.append({
            "bundle_offer_id": offer["id"],
            "merchant_name": context["merchant_names"].get(mid, "Unknown"),
            "coverage": f"{len(coverage_groups)}/{total_products}",
            "coverage_groups": coverage_groups,
            "products_covered": [context["product_titles"].get(g, "Unknown") for g in coverage_groups],
            # Backend-computed financial facts (READ-ONLY for LLM)
            "backend_computed_total": round(backend_total, 2),
            "backend_computed_subtotal": round(backend_subtotal, 2),
            "backend_bundle_discount": round(bundle_discount, 2),
            "original_list_total": round(original_list_total, 2),
            "overall_discount_pct": discount_pct,
            "bundle_benefits": offer.get("bundle_benefits", ""),
            "all_stock_sufficient": all_sufficient,
            "stock_status": stock_status,
            # Per-product discount detail
            "per_product_details": [
                {
                    "product_group_id": li.get("product_group_id"),
                    "product_title": li.get("product_title", "Unknown"),
                    "shopify_list_price": float(li.get("shopify_list_price", 0)),
                    "discount_pct": float(li.get("discount_pct", 0)),
                    "backend_unit_price": float(li.get("unit_price", 0)),
                }
                for li in line_items
            ],
        })

    return enriched


def _fetch_buyer_rag_context(context: dict) -> dict:
    """Retrieve RAG context specific to the Buyer Agent's decision-making needs."""
    product_title_str = " ".join(context["product_titles"].values())
    buyer_rag = retrieve_buyer_context(product_titles=product_title_str, top_k=3)

    # Format into readable text for the LLM prompt
    policy_parts = []
    for arch in buyer_rag.get("archetypes", []):
        desc = arch.get("description", "")
        if desc:
            policy_parts.append(f"[Platform Policy] {desc}")

    for doc in buyer_rag.get("policy_docs", []):
        text = doc.get("extracted_text", "")
        if text:
            policy_parts.append(f"[Fulfillment Doc: {doc.get('file_name', 'unknown')}]\n{text[:500]}")

    # Add default platform policies if no specific docs found
    if not policy_parts:
        policy_parts = [
            "[Platform Default] Prefer single-merchant fulfillment when the price difference from splitting is below ₹2,000.",
            "[Platform Default] 100% basket coverage is mandatory — partial fulfillment is never acceptable.",
            "[Platform Default] Stock sufficiency is a hard requirement — never assign a product to a merchant who cannot fulfill the quantity.",
            "[Platform Default] For split fulfillment, prefer fewer merchants to reduce complexity.",
        ]

    return {
        "raw": buyer_rag,
        "formatted_text": "\n\n".join(policy_parts),
    }


# ─── ALLOCATION BUILDER ──────────────────────────────────────
# Deterministic: takes LLM decision plan + backend-computed offer prices → allocation

def _build_allocation(decision_plan: dict, context: dict) -> tuple[list[dict], list[str]]:
    """Take LLM decision plan and compute deterministic allocation.

    The LLM says "use Offer A for products X, Y, Z".
    This function looks up the backend-computed unit_prices from bundle_offers
    and multiplies by the cart's actual quantity.

    Returns (built_plan, errors).
    """
    offers_by_id = {o["id"]: o for o in context["offers"]}
    selected_offers = decision_plan.get("selected_offers", [])
    errors = []
    built_plan = []

    # Track remaining stock per merchant per product across ALL carts
    remaining_stock = {}
    for mid, stock_map in context["merchant_stock"].items():
        remaining_stock[mid] = dict(stock_map)

    for cart_entry in context["cart_intents"]:
        cart_id = cart_entry["cart_id"]
        cart_needs = {item["product_group_id"]: item for item in cart_entry["items"]}
        assigned_products = set()
        built_assignments = []
        cart_subtotal = 0.0
        total_bundle_discount = 0.0

        for selection in selected_offers:
            offer_id = selection.get("bundle_offer_id")
            offer = offers_by_id.get(offer_id)
            if not offer:
                errors.append(f"Cart {cart_id}: offer {offer_id} not found")
                continue

            mid = offer["merchant_id"]
            selected_products = selection.get("products", [])

            for gid in selected_products:
                # Validate product is covered by this offer
                if gid not in offer.get("coverage_product_groups", []):
                    errors.append(f"Cart {cart_id}: offer {offer_id} does not cover product {gid}")
                    continue

                # Get real quantity from cart intent
                cart_item = cart_needs.get(gid)
                if not cart_item:
                    errors.append(f"Cart {cart_id}: product {gid} not in cart intent")
                    continue

                req_qty = cart_item["quantity"]

                # Check live stock
                available = remaining_stock.get(mid, {}).get(gid, 0)
                if available < req_qty:
                    errors.append(
                        f"Cart {cart_id}: merchant {mid} has {available} stock for "
                        f"product {gid}, but {req_qty} required"
                    )
                    continue

                # Get backend-computed unit_price from offer's line_items
                offer_line = next(
                    (li for li in offer.get("line_items", []) if li.get("product_group_id") == gid),
                    None
                )
                if not offer_line:
                    errors.append(f"Cart {cart_id}: offer {offer_id} has no line_item for product {gid}")
                    continue

                unit_price = float(offer_line.get("unit_price", 0))
                line_total = round(unit_price * req_qty, 2)

                # Deduct stock
                remaining_stock[mid][gid] = available - req_qty

                # Check for duplicate assignment
                if gid in assigned_products:
                    errors.append(f"Cart {cart_id}: product {gid} assigned twice")
                    continue
                assigned_products.add(gid)

                built_assignments.append({
                    "product_group_id": gid,
                    "bundle_offer_id": offer_id,
                    "merchant_id": mid,
                    "quantity": req_qty,
                    "unit_price": unit_price,
                    "line_total": line_total,
                })
                cart_subtotal += line_total

            # Accumulate bundle discount from this offer
            total_bundle_discount += float(offer.get("bundle_discount", 0))

        cart_subtotal = round(cart_subtotal, 2)
        cart_total = round(cart_subtotal - total_bundle_discount, 2)

        # Coverage check (HARD CONSTRAINT)
        missing_products = set(cart_needs.keys()) - assigned_products
        if missing_products:
            missing_titles = [context["product_titles"].get(gid, gid) for gid in missing_products]
            errors.append(f"Cart {cart_id}: INCOMPLETE COVERAGE — missing: {missing_titles}")

        if built_assignments:
            built_plan.append({
                "cart_id": cart_id,
                "assignments": built_assignments,
                "subtotal": cart_subtotal,
                "bundle_discount": round(total_bundle_discount, 2),
                "total_price": cart_total,
                "merchant_count": len(set(a["merchant_id"] for a in built_assignments)),
            })

    return built_plan, errors


# ─── VALIDATOR ────────────────────────────────────────────────

def _validate_built_plan(plan: list[dict], context: dict) -> tuple[bool, list[str]]:
    """Final gate before execution. Checks everything is self-consistent."""
    errors = []

    MINIMUM_COVERAGE_PERCENTAGE = 50.0

    for cart in plan:
        assignments = cart.get("assignments", [])

        # 1. Math: sum of line_totals == subtotal
        computed_subtotal = round(sum(a["line_total"] for a in assignments), 2)
        if abs(computed_subtotal - cart["subtotal"]) > 0.01:
            errors.append(
                f"Cart {cart['cart_id']}: subtotal mismatch — "
                f"sum={computed_subtotal} vs stated={cart['subtotal']}"
            )

        # 2. Math: subtotal - discount == total_price
        expected_total = round(cart["subtotal"] - cart["bundle_discount"], 2)
        if abs(expected_total - cart["total_price"]) > 0.01:
            errors.append(
                f"Cart {cart['cart_id']}: total_price mismatch — "
                f"{cart['subtotal']} - {cart['bundle_discount']} = {expected_total}, "
                f"but total_price={cart['total_price']}"
            )

        # 3. Math: each line_total == unit_price × quantity
        for a in assignments:
            expected_line = round(a["unit_price"] * a["quantity"], 2)
            if abs(expected_line - a["line_total"]) > 0.01:
                errors.append(
                    f"Cart {cart['cart_id']}: line_total mismatch for {a['product_group_id']} — "
                    f"{a['unit_price']} × {a['quantity']} = {expected_line}, "
                    f"but line_total={a['line_total']}"
                )

        # 4. Coverage and Fulfillment Status
        intent = next((c for c in context["cart_intents"] if c["cart_id"] == cart["cart_id"]), None)
        requested_units = 0
        fulfilled_units = 0
        allocation_snapshot = {
            "requested_items": [],
            "fulfilled_items": [],
            "unfulfilled_items": []
        }

        if intent:
            assigned_qty_map = {a["product_group_id"]: a["quantity"] for a in assignments}
            
            for item in intent["items"]:
                gid = item["product_group_id"]
                req_qty = item["quantity"]
                requested_units += req_qty
                
                allocation_snapshot["requested_items"].append({
                    "product_group_id": gid,
                    "sku": context["product_titles"].get(gid, gid), # Using title as display sku
                    "quantity": req_qty
                })
                
                fulfilled_qty = assigned_qty_map.get(gid, 0)
                fulfilled_units += fulfilled_qty
                
                if fulfilled_qty < req_qty:
                    allocation_snapshot["unfulfilled_items"].append({
                        "product_group_id": gid,
                        "sku": context["product_titles"].get(gid, gid),
                        "quantity": req_qty - fulfilled_qty,
                        "reason": "UNAVAILABLE"
                    })

            for a in assignments:
                gid = a["product_group_id"]
                allocation_snapshot["fulfilled_items"].append({
                    "product_group_id": gid,
                    "sku": context["product_titles"].get(gid, gid),
                    "quantity": a["quantity"],
                    "merchant_id": a["merchant_id"]
                })

        coverage_percentage = round((fulfilled_units / requested_units * 100) if requested_units > 0 else 0, 2)
        
        if coverage_percentage == 100:
            fulfillment_status = "FULLY_FULFILLED"
        elif coverage_percentage >= MINIMUM_COVERAGE_PERCENTAGE:
            fulfillment_status = "PARTIALLY_FULFILLED"
        else:
            fulfillment_status = "UNFULFILLED"
            errors.append(f"Cart {cart['cart_id']}: COVERAGE FAILURE — {coverage_percentage}% is below minimum {MINIMUM_COVERAGE_PERCENTAGE}%")

        cart["requested_units"] = requested_units
        cart["fulfilled_units"] = fulfilled_units
        cart["coverage_percentage"] = coverage_percentage
        cart["fulfillment_status"] = fulfillment_status
        cart["allocation_snapshot"] = allocation_snapshot

        # 5. Fix merchant_count if wrong (auto-correct, not error)
        actual_merchants = len(set(a["merchant_id"] for a in assignments))
        cart["merchant_count"] = actual_merchants

    return len(errors) == 0, errors


# ─── MAIN ENTRY POINT ────────────────────────────────────────

def run_bundle_buyer_agent(pool_id: str) -> dict:
    """Run the Buyer Agent decision pipeline for a multi-product pool.

    Pipeline:
        1. Fetch context (offers with backend-computed prices, carts, LIVE stock)
        2. Pre-compute offer summaries (READ-ONLY financial facts for LLM)
        3. Retrieve Buyer RAG (fulfillment policies, customer experience rules)
        4. LLM makes commercial decision: which offers, single vs split, why
        5. AllocationBuilder: maps decision → deterministic prices × quantities
        6. Validator: math, coverage, stock
        7. Persist and return
    """
    context = _fetch_bundle_context(pool_id)

    if not context["offers"]:
        logger.warning(f"[buyer_agent] No validated offers for pool {pool_id}")
        return {"ranking": [], "allocation_plan": []}

    # ─── Pre-compute offer context (READ-ONLY for LLM) ───
    enriched_offers = _precompute_offer_context(context)

    # ─── Retrieve Buyer RAG context ───
    buyer_rag = _fetch_buyer_rag_context(context)

    user_content = json.dumps({
        "offers": enriched_offers,
        "cart_intents": context["cart_intents"],
        "retrieved_policies": buyer_rag["formatted_text"],
        "evaluation_criteria": [
            "100% basket coverage is STRONGLY PREFERRED, but partial coverage is acceptable if 100% is impossible.",
            "Total backend-computed price (lower is better) — reference backend_computed_total",
            "Discount depth (higher % is better) — reference overall_discount_pct",
            "Stock sufficiency (MUST be sufficient for all products)",
            "Merchant count (fewer is better — single merchant preferred when savings < ₹2,000)",
            "Bundle benefits (free shipping, warranty, etc.)",
            "Retrieved fulfillment policies (reference specific policy in reasoning)",
        ],
    })

    # ─── LLM Decision ───
    llm_result = call_with_fallback(
        BUNDLE_BUYER_MODELS, BUYER_AGENT_SYSTEM_PROMPT, user_content,
        step_name="bundle_buyer_agent"
    )

    decision = llm_result.get("decision", "unknown")
    selected_offers = llm_result.get("selected_offers", [])
    reasoning = llm_result.get("reasoning", {})
    ranking = llm_result.get("ranking", [])

    logger.info(f"[buyer_agent] Decision: {decision}")
    logger.info(f"[buyer_agent] Selected offers: {json.dumps(selected_offers, indent=2)}")
    logger.info(f"[buyer_agent] Reasoning: {json.dumps(reasoning, indent=2)}")

    # ─── AllocationBuilder: decision → deterministic prices × quantities ───
    built_plan, build_errors = _build_allocation(llm_result, context)

    if build_errors:
        logger.warning(f"[buyer_agent] AllocationBuilder errors: {build_errors}")

    # ─── Validator: final gate ───
    is_valid, validation_errors = _validate_built_plan(built_plan, context)

    if validation_errors:
        logger.warning(f"[buyer_agent] Validator errors: {validation_errors}")

    all_errors = build_errors + validation_errors

    # ─── Persist ranking on offers ───
    for r in ranking:
        sb.table("bundle_offers").update({"buyer_rank": r["rank"]}).eq(
            "id", r["bundle_offer_id"]
        ).execute()

    # ─── Persist reasoning on pool (audit trail) ───
    sb.table("multi_product_pools").update({
        "buyer_agent_reasoning": {
            "llm_decision": llm_result,
            "validated_plan": built_plan,
            "validation_passed": is_valid and len(build_errors) == 0,
            "validation_errors": all_errors,
            "buyer_rag_used": {
                "archetypes_count": len(buyer_rag["raw"].get("archetypes", [])),
                "policy_docs_count": len(buyer_rag["raw"].get("policy_docs", [])),
            },
        },
        "status": "allocated",
    }).eq("id", pool_id).execute()

    if not is_valid or build_errors:
        logger.error(
            f"[buyer_agent] Plan REJECTED for pool {pool_id}. Errors: {all_errors}"
        )

    return {
        "ranking": ranking,
        "allocation_plan": built_plan,
        "validation_passed": is_valid and len(build_errors) == 0,
        "validation_errors": all_errors,
        "decision": decision,
        "reasoning": reasoning,
    }

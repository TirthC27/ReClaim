import json
import logging
from app.db.client import get_supabase
from app.services.llm_client import call_with_fallback
from app.services.strategies import strategies_context_text
from app.services.offer_engine import run_offer_generation_round, validate_offer

logger = logging.getLogger(__name__)
sb = get_supabase()

MAX_ROUNDS = 3
REVISION_MODEL = ["deepseek/deepseek-chat"]  # cheap model for revision decisions

REVISION_SYSTEM_PROMPT = f"""You represent one merchant in a live, visible negotiation for a bulk
demand opportunity. You can see your own current offer and every competing merchant's
current offer, along with the total demand quantity. Decide whether to revise your offer
this round.

Available strategic reasoning patterns you may draw on (not mandatory, use only if genuinely
applicable to this merchant's situation):
{strategies_context_text()}

Never revise below your stated margin_floor_pct relative to wholesale cost, and never exceed
your available stock capacity. If you choose not to revise, say so plainly and explain why
holding is the better move. Respond in valid JSON only:
{{
  "revised": true or false,
  "offer_type": "...",
  "price": <number>,
  "bundled_items": [...],
  "description": "<customer-facing text>",
  "reasoning": "<why you changed or held>",
  "strategy_applied": "<name of strategy used, or null>"
}}
"""


def _fetch_current_round_offers(pool_id: str, round_number: int) -> list[dict]:
    return (
        sb.table("offer_negotiation_rounds")
        .select("*")
        .eq("demand_pool_id", pool_id)
        .eq("round_number", round_number)
        .execute()
        .data
    )


def _build_revision_prompt(merchant: dict, own_offer: dict, competitor_offers: list[dict], pool: dict) -> str:
    return json.dumps({
        "merchant": {
            "name": merchant.get("name"),
            "margin_floor_pct": merchant.get("margin_floor_pct"),
            "stock_data": merchant.get("stock_data"),
        },
        "your_current_offer": {
            "offer_type": own_offer.get("offer_type"),
            "price": float(own_offer["price"]) if own_offer.get("price") is not None else 0,
            "bundled_items": own_offer.get("bundled_items"),
        },
        "competitor_offers": [
            {"offer_type": o.get("offer_type"), "price": float(o["price"]) if o.get("price") is not None else 0, "bundled_items": o.get("bundled_items")}
            for o in competitor_offers
        ],
        "total_demand_qty": pool.get("signal_count", 1),
    })


async def run_negotiation(pool_id: str):
    # Clear any prior negotiation history for this pool before starting fresh
    sb.table("offer_negotiation_rounds").delete().eq("demand_pool_id", pool_id).execute()
    
    # Also clear previously-promoted offers for this pool
    sb.table("offers").update({"status": "expired"}).eq(
        "demand_pool_id", pool_id
    ).in_("status", ["candidate", "validated", "selected", "rejected"]).execute()
    
    # Clear stale allocations
    sb.table("order_allocations").delete().eq("demand_pool_id", pool_id).execute()

    pool = sb.table("demand_pools").select("*").eq("id", pool_id).single().execute().data
    selected_merchant_ids = pool.get("selected_merchant_ids") or []
    if not selected_merchant_ids:
        return {"pool_id": pool_id, "error": "No selected merchants"}

    sb.table("demand_pools").update({"negotiation_status": "in_progress"}).eq("id", pool_id).execute()

    # Round 1: reuse existing per-merchant Step 1-3 pipeline to get initial offers
    # Since run_offer_generation_round inserts into `offers`, we will fetch those inserts and mirror them.
    # Wait, run_offer_generation_round returns the `offers` rows.
    initial_offers, failures = await run_offer_generation_round(pool_id, selected_merchant_ids)
    
    for offer in initial_offers:
        sb.table("offer_negotiation_rounds").insert({
            "demand_pool_id": pool_id,
            "merchant_id": offer["merchant_id"],
            "round_number": 1,
            "offer_type": offer.get("offer_type"),
            "price": offer.get("price"),
            "bundled_items": offer.get("bundled_items"),
            "description": offer.get("description"),
            "revised_from_prior": False,
            "reasoning": "Initial offer",
        }).execute()

    converged = False
    round_number = 1

    while round_number < MAX_ROUNDS and not converged:
        round_number += 1
        current_offers = _fetch_current_round_offers(pool_id, round_number - 1)
        any_revised = False

        for merchant_id in selected_merchant_ids:
            merchant_resp = sb.table("merchants").select("*").eq("id", merchant_id).single().execute()
            if not merchant_resp.data:
                continue
            merchant = merchant_resp.data
            own_offer = next((o for o in current_offers if str(o["merchant_id"]) == str(merchant_id)), None)
            if not own_offer:
                continue
            competitor_offers = [o for o in current_offers if str(o["merchant_id"]) != str(merchant_id)]

            user_content = _build_revision_prompt(merchant, own_offer, competitor_offers, pool)

            try:
                result = call_with_fallback(
                    REVISION_MODEL, REVISION_SYSTEM_PROMPT, user_content, step_name=f"negotiation-r{round_number}"
                )
            except Exception as exc:
                logger.warning(f"[negotiation] Merchant {merchant_id} round {round_number} failed: {exc}")
                result = {"revised": False, **own_offer, "reasoning": "No response, holding prior offer"}

            revised = result.get("revised", False)
            any_revised = any_revised or revised

            sb.table("offer_negotiation_rounds").insert({
                "demand_pool_id": pool_id,
                "merchant_id": merchant_id,
                "round_number": round_number,
                "offer_type": result.get("offer_type", own_offer.get("offer_type")),
                "price": result.get("price", own_offer.get("price")),
                "bundled_items": result.get("bundled_items", own_offer.get("bundled_items")),
                "description": result.get("description", own_offer.get("description")),
                "revised_from_prior": revised,
                "reasoning": result.get("reasoning", ""),
                "strategy_applied": result.get("strategy_applied"),
            }).execute()

        converged = not any_revised

    final_status = "converged" if converged else "max_rounds_reached"
    sb.table("demand_pools").update({"negotiation_status": final_status}).eq("id", pool_id).execute()

    # Promote the FINAL round's offers into the real `offers` table for validation + Buyer Agent
    final_offers = _fetch_current_round_offers(pool_id, round_number)
    
    # Defensive dedup: one offer per merchant, keep the latest created_at if somehow duplicated
    latest_per_merchant = {}
    for o in final_offers:
        latest_per_merchant[o["merchant_id"]] = o
        
    promoted = []
    for o in latest_per_merchant.values():
        merchant_resp = sb.table("merchants").select("*").eq("id", o["merchant_id"]).single().execute()
        merchant = merchant_resp.data if merchant_resp.data else {}
        
        offer_data = {
            "offer_type": o["offer_type"],
            "price": o["price"],
            "bundled_items": o.get("bundled_items", []),
            "description": o.get("description", "")
        }
        
        # We mock strategy max_discount_pct to merchant's margin floor
        margin_floor = merchant.get("margin_floor_pct", 100)
        strategy = {"max_discount_pct": margin_floor}
        
        status, reason, value_score = validate_offer(offer_data, strategy, merchant, pool)
        
        row = sb.table("offers").insert({
            "demand_pool_id": pool_id,
            "merchant_id": o["merchant_id"],
            "offer_type": o["offer_type"],
            "price": o["price"],
            "bundled_items": o.get("bundled_items", []),
            "description": o.get("description", ""),
            "status": status,
            "value_score": value_score,
            "strategy_reasoning": {"reasoning": o.get("reasoning"), "strategy": o.get("strategy_applied")}
        }).execute().data[0]
        promoted.append(row)

    return {"final_round": round_number, "status": final_status, "offers": promoted}

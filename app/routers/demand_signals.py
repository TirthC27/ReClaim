from fastapi import APIRouter, HTTPException
from app.db.client import get_supabase

router = APIRouter(prefix="/demand-signals", tags=["demand-signals"])

@router.get("/{signal_id}/offer")
def get_offer_for_signal(signal_id: str):
    """
    Returns the offer allocated to this specific customer's demand_signal,
    for rendering on the on-site special offer page.
    """
    supabase = get_supabase()
    
    allocation = (
        supabase.table("order_allocations")
        .select("merchant_id, demand_pool_id")
        .eq("demand_signal_id", signal_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not allocation.data:
        raise HTTPException(status_code=404, detail="No offer allocated for this signal yet")

    alloc_data = allocation.data[0]
    
    offer = (
        supabase.table("offers")
        .select("id, offer_type, price, bundled_items, description, buyer_rank")
        .eq("demand_pool_id", alloc_data["demand_pool_id"])
        .eq("merchant_id", alloc_data["merchant_id"])
        .eq("status", "selected")
        .limit(1)
        .execute()
    )
    if not offer.data:
        # Also check validated just in case
        offer = (
            supabase.table("offers")
            .select("id, offer_type, price, bundled_items, description, buyer_rank")
            .eq("demand_pool_id", alloc_data["demand_pool_id"])
            .eq("merchant_id", alloc_data["merchant_id"])
            .eq("status", "validated")
            .limit(1)
            .execute()
        )
        if not offer.data:
            raise HTTPException(status_code=404, detail="Offer not found")

    return {
        "demand_signal_id": signal_id,
        "offer": offer.data[0],
    }

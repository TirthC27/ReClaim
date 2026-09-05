"""Bundle Offers router."""

from uuid import UUID
from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.db.client import get_supabase
from app.services.shopify_inventory import get_live_stock
from app.services.razorpay_payments import create_payment_link

router = APIRouter(prefix="/bundle-offers", tags=["bundle-offers"])
sb = get_supabase()


@router.get("")
def list_bundle_offers(
    pool_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None)
):
    query = sb.table("bundle_offers").select("*")
    if pool_id:
        query = query.eq("multi_product_pool_id", str(pool_id))
    if status:
        query = query.eq("status", status)
    
    return query.execute().data


@router.get("/{offer_id}")
def get_bundle_offer(offer_id: UUID):
    row = sb.table("bundle_offers").select("*").eq("id", str(offer_id)).execute().data
    if not row:
        raise HTTPException(status_code=404, detail="Bundle offer not found")
    return row[0]


@router.post("/{offer_id}/select")
def select_bundle_offer(offer_id: UUID):
    # Fetch the bundle offer
    offer_data = sb.table("bundle_offers").select("*").eq("id", str(offer_id)).execute().data
    if not offer_data:
        raise HTTPException(status_code=404, detail="Bundle offer not found")
    offer = offer_data[0]

    if offer.get("status") not in ["validated", "selected"]:
        raise HTTPException(status_code=400, detail="Offer is not selectable")

    line_items = offer.get("line_items", [])
    if not line_items:
        raise HTTPException(status_code=400, detail="Offer has no line items")

    # 1. Pre-checkout inventory re-verification using live Shopify data
    for item in line_items:
        merchant_id = item["merchant_id"]
        qty_needed = item["quantity"]
        mapping = sb.table("merchant_products").select("inventory_item_id").eq("merchant_id", merchant_id).eq("product_group_id", item["product_group_id"]).execute().data
        inventory_item_id = mapping[0].get("inventory_item_id") if mapping else None
        
        live_stock = get_live_stock(merchant_id, inventory_item_id=inventory_item_id)
        if live_stock is None or live_stock < qty_needed:
            sb.table("bundle_offers").update({"status": "rejected"}).eq("id", str(offer_id)).execute()
            raise HTTPException(
                status_code=409, 
                detail=f"Stock verification failed for product group {item['product_group_id']}. Required: {qty_needed}, Available: {live_stock or 0}"
            )

    # 2. Create N merchant orders
    created_orders = []
    merchant_groups = {}
    for item in line_items:
        mid = item["merchant_id"]
        if mid not in merchant_groups:
            merchant_groups[mid] = []
        merchant_groups[mid].append(item)

    for mid, items in merchant_groups.items():
        order = sb.table("orders").insert({
            "bundle_offer_id": str(offer_id),
            "merchant_id": mid,
            "status": "pending_payment",
        }).execute().data[0]
        created_orders.append(order["id"])

    # 3. Create a single Razorpay payment link for the total bundle price
    total_price = float(offer.get("total_price", 0))
    if total_price <= 0:
        raise HTTPException(status_code=400, detail="Offer price is invalid")
    
    cart_id = offer.get("cart_id")
    customer_email = None
    if cart_id:
        cart_data = sb.table("carts").select("customer_email").eq("id", cart_id).execute().data
        if cart_data:
            customer_email = cart_data[0].get("customer_email")

    callback_url = f"{settings.FRONTEND_BASE_URL}/payment-success?bundle_offer_id={offer_id}"

    pl = create_payment_link(
        amount_paise=int(total_price * 100),
        description="Project Flow Bundle Offer",
        notes={"bundle_offer_id": str(offer_id)},
        callback_url=callback_url,
        customer_email=customer_email,
    )

    payment_link_url = pl.get("short_url") or pl.get("short_url".upper()) or pl.get("url")
    if not payment_link_url:
        raise HTTPException(status_code=500, detail="Razorpay payment link URL missing")

    # 4. Insert into payments table mapping 1 payment to N orders via bundle_offer_id
    sb.table("payments").insert({
        "bundle_offer_id": str(offer_id),
        "razorpay_payment_link_id": pl.get("id"),
        "amount": total_price,
        "status": "created",
    }).execute()

    return {"payment_link_url": payment_link_url}

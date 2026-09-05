"""
Reconciliation command to map Quotation SKUs to Shopify Variants.
Run with: python -m app.services.reconcile_quotation_shopify
"""
import sys
import logging
from app.db.client import get_supabase
from app.services import shopify as shopify_svc

logger = logging.getLogger(__name__)

def reconcile_all():
    sb = get_supabase()
    
    print("==================================================")
    print("QUOTATION ? SHOPIFY RECONCILIATION")
    print("==================================================")
    
    # 1. Fetch all distinct SKUs from merchant_documents metadata
    docs = sb.table("merchant_documents").select("merchant_id, metadata").execute().data
    
    quotation_skus = {}
    for doc in docs:
        meta = doc.get("metadata")
        if meta and meta.get("sku"):
            key = (doc["merchant_id"], meta["sku"])
            if key not in quotation_skus:
                quotation_skus[key] = {
                    "merchant_id": doc["merchant_id"],
                    "sku": meta["sku"],
                    "merchant_name": meta.get("merchant_name", "")
                }
                
    if not quotation_skus:
        print("No quotation SKUs found in merchant_documents metadata. Run document ingestion first.")
        return
        
    print(f"Found {len(quotation_skus)} distinct quotation SKUs to reconcile.")
    
    merchants_resp = sb.table("merchants").select("id, shopify_vendor_name").execute().data
    merchant_vendors = {m["id"]: m["shopify_vendor_name"] for m in merchants_resp}
    
    stats = {
        "MATCHED": 0,
        "MISSING_IN_SHOPIFY": 0,
        "MISSING_IN_QUOTATION": 0,
        "DUPLICATE_QUOTATION_SKU": 0,
        "DUPLICATE_SHOPIFY_SKU": 0,
        "PRICE_MISMATCH": 0
    }
    
    for merchant_id in set(v["merchant_id"] for v in quotation_skus.values()):
        vendor_name = merchant_vendors.get(merchant_id)
        if not vendor_name:
            continue
            
        print(f"\nReconciling Merchant: {vendor_name} ({merchant_id})")
        shopify_products = shopify_svc.fetch_products_by_vendor(vendor_name)
        
        shopify_variants_by_sku = {}
        for sp in shopify_products:
            shopify_pid = str(sp.get("id", "")).split("/")[-1]
            for variant in sp.get("variants", []):
                sku = variant.get("sku")
                if sku:
                    if sku in shopify_variants_by_sku:
                        stats["DUPLICATE_SHOPIFY_SKU"] += 1
                        continue
                    shopify_variants_by_sku[sku] = {
                        "shopify_product_id": shopify_pid,
                        "shopify_variant_id": str(variant.get("id", "")).split("/")[-1],
                        "title": sp.get("title"),
                        "price": variant.get("price")
                    }
                    
        merchant_q_skus = [v for k, v in quotation_skus.items() if k[0] == merchant_id]
        
        for mq in merchant_q_skus:
            q_sku = mq["sku"]
            if q_sku in shopify_variants_by_sku:
                sv = shopify_variants_by_sku[q_sku]
                
                mp_row = {
                    "merchant_id": merchant_id,
                    "shopify_product_id": sv["shopify_product_id"],
                    "shopify_variant_id": sv["shopify_variant_id"],
                    "quotation_sku": q_sku
                }
                sb.table("merchant_products").upsert(
                    mp_row, 
                    on_conflict="merchant_id,shopify_product_id"
                ).execute()
                
                stats["MATCHED"] += 1
                print(f"  [MATCH] {q_sku} -> Product {sv['shopify_product_id']} / Variant {sv['shopify_variant_id']}")
                
                del shopify_variants_by_sku[q_sku]
            else:
                stats["MISSING_IN_SHOPIFY"] += 1
                print(f"  [MISSING IN SHOPIFY] {q_sku}")
                
        for s_sku in shopify_variants_by_sku:
            stats["MISSING_IN_QUOTATION"] += 1
            print(f"  [MISSING IN QUOTATION] {s_sku}")
            
    print("\n==================================================")
    for k, v in stats.items():
        print(f"{k.ljust(31)} {v}")
    print("==================================================")

if __name__ == "__main__":
    reconcile_all()

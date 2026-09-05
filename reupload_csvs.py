import sys
import logging
import os
from app.db.client import get_supabase
from app.services.merchant_documents import upload_document

sb = get_supabase()

def reupload_all_csvs():
    # 1. Clear existing chunks
    # Actually, we should just delete from merchant_documents where source is CSV, or clear all
    # For now, let's just clear all to be safe and clean since these are the main docs
    sb.table('merchant_documents').delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    print("Cleared existing merchant_documents.")

    # 2. Get merchants to map names to IDs
    merchants = sb.table('merchants').select('id, name').execute().data
    merchant_map = {m['name']: m['id'] for m in merchants}

    # 3. Upload CSVs
    public_dir = "merchant-dashboard/public"
    csvs = [f for f in os.listdir(public_dir) if f.endswith('_quotation.csv')]
    for csv in csvs:
        merchant_name = csv.replace("_quotation.csv", "")
        if merchant_name in merchant_map:
            print(f"Uploading {csv} for {merchant_name}...")
            filepath = os.path.join(public_dir, csv)
            with open(filepath, 'rb') as f:
                upload_document(merchant_map[merchant_name], csv, f.read())
        else:
            print(f"Warning: Merchant {merchant_name} not found in DB.")

if __name__ == "__main__":
    reupload_all_csvs()

import psycopg2

password = "B0tSCKqyjEiDfvSd"
db_url = f"postgresql://postgres.lefpbdeuxvzkkmmulxje:{password}@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"

sql = """
ALTER TABLE cart_recoveries ADD COLUMN IF NOT EXISTS shopify_draft_order_id TEXT;
ALTER TABLE cart_recoveries ADD COLUMN IF NOT EXISTS razorpay_payment_link_id TEXT;
ALTER TABLE merchant_products ADD COLUMN IF NOT EXISTS inventory_item_id TEXT;
ALTER TABLE merchant_products ADD COLUMN IF NOT EXISTS shopify_location_id TEXT;
ALTER TABLE merchant_products ADD COLUMN IF NOT EXISTS cached_stock_qty INT;
ALTER TABLE merchant_products ADD COLUMN IF NOT EXISTS stock_cached_at TIMESTAMPTZ;
"""

try:
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute(sql)
    conn.commit()
    print("Migration executed successfully.")
    cur.close()
    conn.close()
except Exception as e:
    print("Migration failed:", e)

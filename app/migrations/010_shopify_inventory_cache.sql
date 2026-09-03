-- Shopify inventory identifiers and short-lived quantity cache.
ALTER TABLE merchant_products
    ADD COLUMN IF NOT EXISTS inventory_item_id TEXT,
    ADD COLUMN IF NOT EXISTS shopify_location_id TEXT,
    ADD COLUMN IF NOT EXISTS cached_stock_qty INT,
    ADD COLUMN IF NOT EXISTS stock_cached_at TIMESTAMPTZ;

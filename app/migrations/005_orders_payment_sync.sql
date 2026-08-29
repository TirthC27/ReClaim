-- =============================================================
-- 005_orders_payment_sync.sql
-- Adds order linkage + retry flags for Razorpay → Shopify sync
-- =============================================================

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS demand_signal_id UUID REFERENCES demand_signals(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS merchant_id UUID REFERENCES merchants(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS order_creation_failed BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS last_shopify_error TEXT;

CREATE INDEX IF NOT EXISTS idx_orders_status_retry
    ON orders(status, order_creation_failed);


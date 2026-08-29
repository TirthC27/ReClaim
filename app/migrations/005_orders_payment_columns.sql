-- =============================================================
-- 005_orders_payment_columns.sql
-- Adds columns to orders for allocation tracking and retry logic
-- =============================================================

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS demand_signal_id UUID REFERENCES demand_signals(id),
    ADD COLUMN IF NOT EXISTS merchant_id UUID REFERENCES merchants(id),
    ADD COLUMN IF NOT EXISTS order_creation_failed BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS last_shopify_error TEXT;

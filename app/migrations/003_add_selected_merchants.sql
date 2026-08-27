-- =============================================================
-- 003_add_selected_merchants.sql
-- Adds selected_merchant_ids column to demand_pools for
-- Section 9A merchant selection results.
-- =============================================================

ALTER TABLE demand_pools
    ADD COLUMN IF NOT EXISTS selected_merchant_ids JSONB;

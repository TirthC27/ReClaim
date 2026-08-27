-- =============================================================
-- 004_offer_engine_schema.sql
-- Adds columns/tables for the RAG offer engine + 9A.2 fairness
-- =============================================================

-- ── offers: add RAG context + value score ───────────────────
ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS rag_context_used JSONB,
    ADD COLUMN IF NOT EXISTS value_score NUMERIC(10,4);

-- ── demand_pools: add rotation order for 9A.2 ──────────────
ALTER TABLE demand_pools
    ADD COLUMN IF NOT EXISTS rotation_order JSONB;

-- ── order_allocations (9A.2 round-robin assignments) ────────
CREATE TABLE IF NOT EXISTS order_allocations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    demand_pool_id      UUID NOT NULL REFERENCES demand_pools(id) ON DELETE CASCADE,
    demand_signal_id    UUID NOT NULL REFERENCES demand_signals(id) ON DELETE CASCADE,
    merchant_id         UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    rotation_position   INT,
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_order_allocations_pool
    ON order_allocations(demand_pool_id);

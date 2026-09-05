-- 017: Bundle Negotiation Rounds
-- Stores per-merchant, per-round negotiation events for the live dashboard feed.

CREATE TABLE IF NOT EXISTS bundle_negotiation_rounds (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    multi_product_pool_id   UUID NOT NULL REFERENCES multi_product_pools(id) ON DELETE CASCADE,
    merchant_id             UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    merchant_name           TEXT,
    round_number            INT NOT NULL,        -- 1 or 2
    action                  TEXT NOT NULL,        -- 'initial', 'undercut', 'hold'
    -- Agent discount decision (percentages only — LLM output)
    per_product_discounts   JSONB,
    bundle_discount_pct     NUMERIC(5,2) DEFAULT 0,
    -- Backend-computed prices (source of truth)
    total_price             NUMERIC(12,2),
    line_items              JSONB,
    -- Previous state (for dashboard ladder)
    previous_price          NUMERIC(12,2),
    -- What the agent saw (competitor prices, NOT floors)
    competitor_snapshot     JSONB,
    -- Agent reasoning (visible in dashboard)
    reasoning               TEXT,
    strategy_applied        TEXT,
    -- Economics snapshot (private, for audit/debug only — never shown to other agents)
    economics_snapshot      JSONB,
    -- Validation
    status                  TEXT DEFAULT 'valid' CHECK (status IN ('valid', 'clamped', 'rejected')),
    validation_errors       JSONB,
    -- Ordering
    is_final                BOOLEAN DEFAULT FALSE,
    created_at              TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bundle_neg_rounds_pool
    ON bundle_negotiation_rounds(multi_product_pool_id, round_number);

-- Add negotiation state columns to multi_product_pools
ALTER TABLE multi_product_pools
    ADD COLUMN IF NOT EXISTS negotiation_status TEXT DEFAULT 'not_started';

ALTER TABLE multi_product_pools
    ADD COLUMN IF NOT EXISTS total_rounds INT DEFAULT 0;

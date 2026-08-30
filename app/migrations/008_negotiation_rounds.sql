CREATE TABLE IF NOT EXISTS offer_negotiation_rounds (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    demand_pool_id      UUID NOT NULL REFERENCES demand_pools(id) ON DELETE CASCADE,
    merchant_id         UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    round_number        INT NOT NULL,
    offer_type          TEXT,
    price               NUMERIC(10,2),
    bundled_items       JSONB,
    description         TEXT,
    revised_from_prior  BOOLEAN DEFAULT false,
    reasoning           TEXT,
    strategy_applied    TEXT,  -- which named strategy (if any) influenced this round's change
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_negotiation_rounds_pool ON offer_negotiation_rounds(demand_pool_id, round_number);

ALTER TABLE demand_pools
    ADD COLUMN IF NOT EXISTS negotiation_status TEXT DEFAULT 'not_started'
        CHECK (negotiation_status IN ('not_started','in_progress','converged','max_rounds_reached'));

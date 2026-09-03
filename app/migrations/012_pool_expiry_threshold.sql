-- Time-windowed demand pools and cart recoveries.
ALTER TABLE demand_pools
    ADD COLUMN IF NOT EXISTS window_start TIMESTAMPTZ DEFAULT now(),
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS min_carts_required INT DEFAULT 1;

ALTER TABLE cart_recoveries
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

UPDATE demand_pools
SET window_start = COALESCE(window_start, created_at),
    expires_at = COALESCE(expires_at, created_at + interval '24 hours'),
    min_carts_required = COALESCE(min_carts_required, 1)
WHERE expires_at IS NULL OR window_start IS NULL OR min_carts_required IS NULL;

UPDATE cart_recoveries
SET expires_at = COALESCE(expires_at, created_at + interval '24 hours')
WHERE expires_at IS NULL;

ALTER TABLE demand_pools DROP CONSTRAINT IF EXISTS demand_pools_status_check;
ALTER TABLE demand_pools ADD CONSTRAINT demand_pools_status_check
    CHECK (status IN ('open', 'offers_generated', 'closed', 'expired'));

CREATE INDEX IF NOT EXISTS idx_demand_pools_expires_at ON demand_pools(expires_at);
CREATE INDEX IF NOT EXISTS idx_cart_recoveries_expires_at ON cart_recoveries(expires_at);

-- =============================================================
-- 013_multi_product_pools.sql — Multi-Product Cart Pool Architecture
-- =============================================================

-- ── multi_product_pools ─────────────────────────────────────
-- One pool per unique basket signature (sorted product group IDs).
CREATE TABLE IF NOT EXISTS multi_product_pools (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    basket_signature      TEXT NOT NULL,
    product_group_ids     JSONB NOT NULL,
    signal_count          INT DEFAULT 0,
    cart_count            INT DEFAULT 0,
    total_items           INT DEFAULT 0,
    status                TEXT DEFAULT 'open'
                          CHECK (status IN ('open','offers_generated','allocated','expired')),
    selected_merchant_ids JSONB,
    buyer_agent_reasoning JSONB,
    window_start          TIMESTAMPTZ DEFAULT now(),
    expires_at            TIMESTAMPTZ,
    min_carts_required    INT DEFAULT 1,
    created_at            TIMESTAMPTZ DEFAULT now(),
    updated_at            TIMESTAMPTZ DEFAULT now()
);

-- Only one active pool per basket signature
CREATE UNIQUE INDEX IF NOT EXISTS idx_mp_pools_active_signature
    ON multi_product_pools(basket_signature)
    WHERE status IN ('open', 'offers_generated');

CREATE INDEX IF NOT EXISTS idx_mp_pool_status ON multi_product_pools(status);

-- ── multi_product_pool_products ─────────────────────────────
-- Per-product-group demand breakdown within a multi-product pool.
CREATE TABLE IF NOT EXISTS multi_product_pool_products (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    multi_product_pool_id    UUID NOT NULL REFERENCES multi_product_pools(id) ON DELETE CASCADE,
    product_group_id         UUID NOT NULL REFERENCES product_groups(id),
    aggregated_qty           INT DEFAULT 0,
    representative_product_id UUID REFERENCES products(id),
    UNIQUE (multi_product_pool_id, product_group_id)
);

-- ── bundle_offers ───────────────────────────────────────────
-- One merchant offering multiple products from the same basket.
CREATE TABLE IF NOT EXISTS bundle_offers (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    multi_product_pool_id    UUID NOT NULL REFERENCES multi_product_pools(id) ON DELETE CASCADE,
    merchant_id              UUID NOT NULL REFERENCES merchants(id),
    coverage_product_groups  JSONB NOT NULL,
    coverage_ratio           NUMERIC(3,2) DEFAULT 0,
    line_items               JSONB NOT NULL,
    subtotal                 NUMERIC(10,2),
    bundle_discount          NUMERIC(10,2) DEFAULT 0,
    total_price              NUMERIC(10,2),
    bundle_benefits          TEXT,
    strategy_reasoning       JSONB,
    rag_context_used         JSONB,
    value_score              NUMERIC(6,4) DEFAULT 0,
    status                   TEXT DEFAULT 'candidate'
                             CHECK (status IN ('candidate','validated','rejected','selected','expired')),
    buyer_rank               INT,
    created_at               TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bundle_offers_pool ON bundle_offers(multi_product_pool_id);
CREATE INDEX IF NOT EXISTS idx_bundle_offers_status ON bundle_offers(status);

-- ── basket_co_occurrences ───────────────────────────────────
-- Lightweight analytics: which product groups appear together.
CREATE TABLE IF NOT EXISTS basket_co_occurrences (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_group_id_a    UUID NOT NULL REFERENCES product_groups(id),
    product_group_id_b    UUID NOT NULL REFERENCES product_groups(id),
    co_occurrence_count   INT DEFAULT 1,
    last_seen_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (product_group_id_a, product_group_id_b)
);

-- ── New columns on existing tables ──────────────────────────

ALTER TABLE demand_signals
    ADD COLUMN IF NOT EXISTS multi_product_pool_id UUID REFERENCES multi_product_pools(id);

ALTER TABLE cart_recoveries
    ADD COLUMN IF NOT EXISTS pool_type TEXT DEFAULT 'single'
        CHECK (pool_type IN ('single', 'multi'));

ALTER TABLE cart_recoveries
    ADD COLUMN IF NOT EXISTS multi_product_pool_id UUID REFERENCES multi_product_pools(id);

ALTER TABLE cart_recovery_items
    ADD COLUMN IF NOT EXISTS bundle_offer_id UUID REFERENCES bundle_offers(id);

CREATE INDEX IF NOT EXISTS idx_ds_mp_pool ON demand_signals(multi_product_pool_id);

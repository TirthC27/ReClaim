-- =============================================================
-- 001_init_schema.sql  –  Project Flow: full relational schema
-- Run against your Supabase Postgres instance.
-- =============================================================

-- ── product_groups ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS product_groups (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_sku   TEXT UNIQUE,
    model_name      TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ── products ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS products (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shopify_product_id  TEXT UNIQUE NOT NULL,
    title               TEXT NOT NULL,
    price               NUMERIC(10,2) NOT NULL,
    sku                 TEXT UNIQUE,
    vendor              TEXT,
    category            TEXT,
    product_group_id    UUID REFERENCES product_groups(id) ON DELETE SET NULL,
    raw_shopify_data    JSONB,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

-- ── merchants ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS merchants (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 TEXT NOT NULL,
    shopify_vendor_name  TEXT UNIQUE NOT NULL,
    margin_floor_pct     NUMERIC(5,2),
    stock_data           JSONB,
    accessory_inventory  JSONB,
    warranty_cost_data   JSONB,
    is_active            BOOLEAN DEFAULT true,
    created_at           TIMESTAMPTZ DEFAULT now()
);

-- ── merchant_products (join table) ──────────────────────────
CREATE TABLE IF NOT EXISTS merchant_products (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id         UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    shopify_product_id  TEXT NOT NULL,
    product_group_id    UUID REFERENCES product_groups(id) ON DELETE SET NULL,
    UNIQUE (merchant_id, shopify_product_id)
);

-- ── carts ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS carts (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shopify_checkout_id  TEXT UNIQUE NOT NULL,
    customer_email       TEXT,
    created_at           TIMESTAMPTZ DEFAULT now(),
    abandoned_at         TIMESTAMPTZ,
    converted_at         TIMESTAMPTZ,
    status               TEXT DEFAULT 'active'
                         CHECK (status IN ('active','abandoned','converted'))
);

-- ── demand_signals ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS demand_signals (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cart_id           UUID NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    product_id        UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    product_group_id  UUID REFERENCES product_groups(id) ON DELETE SET NULL,
    merchant_id       UUID REFERENCES merchants(id) ON DELETE SET NULL,
    quantity          INT DEFAULT 1,
    status            TEXT DEFAULT 'pending'
                      CHECK (status IN ('pending','abandoned','pooled','expired')),
    created_at        TIMESTAMPTZ DEFAULT now()
);

-- ── demand_pools ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS demand_pools (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_group_id  UUID NOT NULL REFERENCES product_groups(id) ON DELETE CASCADE,
    signal_count      INT DEFAULT 0,
    status            TEXT DEFAULT 'open'
                      CHECK (status IN ('open','offers_generated','closed')),
    threshold         INT DEFAULT 1,
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);

-- ── merchant_documents ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS merchant_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id     UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    file_name       TEXT,
    file_url        TEXT,
    extracted_text  TEXT,
    -- embedding column created in 002_enable_pgvector.sql
    uploaded_at     TIMESTAMPTZ DEFAULT now()
);

-- ── product_embeddings ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS product_embeddings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id  UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    -- embedding column created in 002_enable_pgvector.sql
    metadata    JSONB
);

-- ── offer_archetypes ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS offer_archetypes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    description TEXT
    -- embedding column created in 002_enable_pgvector.sql
);

-- ── offers ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS offers (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    demand_pool_id      UUID NOT NULL REFERENCES demand_pools(id) ON DELETE CASCADE,
    merchant_id         UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    offer_type          TEXT CHECK (offer_type IN (
                            'discount','gift','bundle','warranty',
                            'upgrade','service','hybrid'
                        )),
    price               NUMERIC(10,2),
    bundled_items       JSONB,
    description         TEXT,
    strategy_reasoning  JSONB,
    status              TEXT DEFAULT 'candidate'
                        CHECK (status IN (
                            'candidate','validated','rejected',
                            'selected','expired'
                        )),
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- ── orders ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orders (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    offer_id          UUID NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    shopify_order_id  TEXT,
    status            TEXT CHECK (status IN (
                          'pending_payment','paid','order_created','failed'
                      )),
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);

-- ── payments ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS payments (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id                  UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    razorpay_payment_link_id  TEXT,
    razorpay_payment_id       TEXT,
    amount                    NUMERIC(10,2),
    status                    TEXT DEFAULT 'created'
                              CHECK (status IN ('created','paid','failed')),
    raw_webhook_payload       JSONB,
    created_at                TIMESTAMPTZ DEFAULT now()
);

-- ── Indexes ─────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_carts_status           ON carts(status);
CREATE INDEX IF NOT EXISTS idx_demand_signals_status   ON demand_signals(status);
CREATE INDEX IF NOT EXISTS idx_demand_pools_status     ON demand_pools(status);
CREATE INDEX IF NOT EXISTS idx_offers_status           ON offers(status);
CREATE INDEX IF NOT EXISTS idx_merchant_products_group ON merchant_products(product_group_id);

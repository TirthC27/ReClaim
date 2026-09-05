-- Core flow reliability fixes. Apply after migration 015.
CREATE TABLE IF NOT EXISTS merchant_pools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    demand_pool_id UUID NOT NULL REFERENCES demand_pools(id) ON DELETE CASCADE,
    merchant_id UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    offer_id UUID REFERENCES offers(id),
    fixed_price NUMERIC(10,2), allocated_qty INT DEFAULT 0, fulfilled_qty INT DEFAULT 0,
    status TEXT DEFAULT 'proposed' CHECK (status IN ('proposed','finalized','fulfilling','completed')),
    created_at TIMESTAMPTZ DEFAULT now(), UNIQUE (demand_pool_id, merchant_id)
);
ALTER TABLE product_groups ADD COLUMN IF NOT EXISTS category TEXT;
ALTER TABLE cart_recoveries ADD COLUMN IF NOT EXISTS order_creation_failed BOOLEAN DEFAULT false;
ALTER TABLE cart_recoveries ADD COLUMN IF NOT EXISTS last_shopify_error TEXT;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'unique_cart_recovery_per_cart') THEN
        ALTER TABLE cart_recoveries ADD CONSTRAINT unique_cart_recovery_per_cart UNIQUE (cart_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'unique_allocation_per_signal') THEN
        ALTER TABLE order_allocations ADD CONSTRAINT unique_allocation_per_signal UNIQUE (demand_signal_id);
    END IF;
END $$;

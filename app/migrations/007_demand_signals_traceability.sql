ALTER TABLE demand_signals
    ADD COLUMN IF NOT EXISTS product_title TEXT,
    ADD COLUMN IF NOT EXISTS resolved_offer_id UUID REFERENCES offers(id);

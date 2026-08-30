CREATE TABLE IF NOT EXISTS cart_recoveries (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cart_id             UUID NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    customer_email      TEXT,
    status              TEXT DEFAULT 'awaiting_offers'
                        CHECK (status IN ('awaiting_offers','ready','pending_payment','paid','order_created','failed')),
    total_price         NUMERIC(10,2),
    razorpay_payment_link_id TEXT,
    shopify_order_id    TEXT,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cart_recovery_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cart_recovery_id    UUID NOT NULL REFERENCES cart_recoveries(id) ON DELETE CASCADE,
    demand_signal_id    UUID NOT NULL REFERENCES demand_signals(id),
    offer_id            UUID REFERENCES offers(id),
    merchant_id         UUID REFERENCES merchants(id),
    price               NUMERIC(10,2),
    UNIQUE (cart_recovery_id, demand_signal_id)
);

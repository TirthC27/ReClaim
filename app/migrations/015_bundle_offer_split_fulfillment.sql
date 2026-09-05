-- Add explicit fulfillment and payment status, units, and allocation snapshot
ALTER TABLE bundle_offers
ADD COLUMN fulfillment_status TEXT DEFAULT 'FULLY_FULFILLED' CHECK (fulfillment_status IN ('FULLY_FULFILLED', 'PARTIALLY_FULFILLED', 'UNFULFILLED')),
ADD COLUMN payment_status TEXT DEFAULT 'PENDING' CHECK (payment_status IN ('PENDING', 'PAID', 'FAILED', 'REFUNDED')),
ADD COLUMN requested_units INTEGER DEFAULT 0,
ADD COLUMN fulfilled_units INTEGER DEFAULT 0,
ADD COLUMN coverage_percentage NUMERIC(5,2) DEFAULT 0,
ADD COLUMN allocation_snapshot JSONB;

-- Change payments to support multi-order bundles (not just 1:1 order)
ALTER TABLE payments
ALTER COLUMN order_id DROP NOT NULL,
ADD COLUMN bundle_offer_id UUID REFERENCES bundle_offers(id) ON DELETE CASCADE;

-- Add bundle_offer_id to orders
ALTER TABLE orders
ADD COLUMN bundle_offer_id UUID REFERENCES bundle_offers(id) ON DELETE SET NULL;


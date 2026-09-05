-- =============================================================
-- 014_quotation_shopify_mapping.sql
-- =============================================================

-- Add columns to merchant_products to create a stable canonical mapping
-- from the Quotation SKU to the live Shopify Variant.
ALTER TABLE merchant_products
ADD COLUMN IF NOT EXISTS quotation_sku TEXT,
ADD COLUMN IF NOT EXISTS shopify_variant_id TEXT;

-- Add indexes as requested by the user
CREATE INDEX IF NOT EXISTS idx_merchant_products_quotation_sku 
ON merchant_products (quotation_sku);

CREATE INDEX IF NOT EXISTS idx_merchant_products_shopify_variant_id 
ON merchant_products (shopify_variant_id);

-- Add metadata column to merchant_documents to store structured RAG info
ALTER TABLE merchant_documents
ADD COLUMN IF NOT EXISTS metadata JSONB;

-- =============================================================
-- 002_enable_pgvector.sql  –  pgvector extension + columns + indexes
-- Run AFTER 001_init_schema.sql
-- =============================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- ── Add vector columns ──────────────────────────────────────
ALTER TABLE merchant_documents
    ADD COLUMN IF NOT EXISTS embedding vector(1024);

ALTER TABLE product_embeddings
    ADD COLUMN IF NOT EXISTS embedding vector(1024);

ALTER TABLE offer_archetypes
    ADD COLUMN IF NOT EXISTS embedding vector(1024);

-- ── HNSW indexes for cosine similarity ──────────────────────
-- HNSW is preferred over IVFFlat for most workloads (no training step).
CREATE INDEX IF NOT EXISTS idx_merchant_docs_embedding
    ON merchant_documents
    USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_product_embeddings_embedding
    ON product_embeddings
    USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_offer_archetypes_embedding
    ON offer_archetypes
    USING hnsw (embedding vector_cosine_ops);

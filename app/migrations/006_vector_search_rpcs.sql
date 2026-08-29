-- =============================================================
-- 006_vector_search_rpcs.sql
-- Creates typed RPC functions for pgvector similarity search.
-- Replaces the broken exec_sql approach in rag_retrieval.py.
-- Run in Supabase SQL Editor AFTER all previous migrations.
-- =============================================================

-- ── 1. Merchant documents (scoped to one merchant) ──────────
CREATE OR REPLACE FUNCTION match_merchant_documents(
    query_embedding vector(1024),
    match_merchant_id uuid,
    match_count int DEFAULT 3
)
RETURNS TABLE (
    id uuid,
    file_name text,
    extracted_text text,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        md.id,
        md.file_name,
        md.extracted_text,
        (1 - (md.embedding <=> query_embedding))::float AS similarity
    FROM merchant_documents md
    WHERE md.embedding IS NOT NULL
      AND md.merchant_id = match_merchant_id
    ORDER BY md.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;


-- ── 2. Product embeddings (global) ──────────────────────────
CREATE OR REPLACE FUNCTION match_product_embeddings(
    query_embedding vector(1024),
    match_count int DEFAULT 3
)
RETURNS TABLE (
    id uuid,
    product_id uuid,
    metadata jsonb,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        pe.id,
        pe.product_id,
        pe.metadata,
        (1 - (pe.embedding <=> query_embedding))::float AS similarity
    FROM product_embeddings pe
    WHERE pe.embedding IS NOT NULL
    ORDER BY pe.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;


-- ── 3. Offer archetypes (global) ────────────────────────────
CREATE OR REPLACE FUNCTION match_offer_archetypes(
    query_embedding vector(1024),
    match_count int DEFAULT 3
)
RETURNS TABLE (
    id uuid,
    description text,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        oa.id,
        oa.description,
        (1 - (oa.embedding <=> query_embedding))::float AS similarity
    FROM offer_archetypes oa
    WHERE oa.embedding IS NOT NULL
    ORDER BY oa.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

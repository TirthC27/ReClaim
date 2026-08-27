"""
RAG retrieval service.

Retrieves relevant context from 3 vector sources for a merchant's
offer generation pipeline:
1. merchant_documents (scoped to this merchant only)
2. product_embeddings (general product knowledge)
3. offer_archetypes  (reusable strategy patterns)
"""

import logging
from app.db.client import get_supabase
from app.services.embeddings import generate_embedding

logger = logging.getLogger(__name__)


def retrieve_context(
    merchant_id: str,
    product_title: str,
    strategy_hint: str = "",
    top_k: int = 3,
) -> dict:
    """
    Build a query from product_title + strategy_hint, embed it,
    and retrieve top-k similar chunks from each vector source.

    Returns a combined context object with text + similarity scores.
    """
    query_text = f"{product_title}. Strategy: {strategy_hint}" if strategy_hint else product_title

    try:
        query_embedding = generate_embedding(query_text)
    except Exception as exc:
        logger.error(f"Failed to embed query: {exc}")
        return {"merchant_docs": [], "product_context": [], "archetypes": [], "error": str(exc)}

    embedding_str = str(query_embedding)
    sb = get_supabase()

    # ── 1. Merchant documents (scoped to this merchant) ──────
    merchant_docs = _vector_search(
        sb,
        table="merchant_documents",
        embedding_str=embedding_str,
        top_k=top_k,
        select_fields="id, file_name, extracted_text",
        filter_col="merchant_id",
        filter_val=str(merchant_id),
    )

    # ── 2. Product embeddings (global) ───────────────────────
    product_context = _vector_search(
        sb,
        table="product_embeddings",
        embedding_str=embedding_str,
        top_k=top_k,
        select_fields="id, product_id, metadata",
    )

    # ── 3. Offer archetypes (global) ─────────────────────────
    archetypes = _vector_search(
        sb,
        table="offer_archetypes",
        embedding_str=embedding_str,
        top_k=top_k,
        select_fields="id, description",
    )

    return {
        "merchant_docs": merchant_docs,
        "product_context": product_context,
        "archetypes": archetypes,
    }


def _vector_search(
    sb,
    table: str,
    embedding_str: str,
    top_k: int,
    select_fields: str,
    filter_col: str | None = None,
    filter_val: str | None = None,
) -> list[dict]:
    """
    Run a cosine-similarity vector search via Supabase RPC.

    Falls back to a raw REST query using the pgvector <=> operator
    via Supabase's PostgREST interface.
    """
    try:
        # Use Supabase RPC for vector similarity search
        # Build the SQL query for cosine similarity
        rpc_query = f"""
            SELECT {select_fields},
                   1 - (embedding <=> '{embedding_str}'::vector) AS similarity
            FROM {table}
            WHERE embedding IS NOT NULL
        """
        if filter_col and filter_val:
            rpc_query += f" AND {filter_col} = '{filter_val}'"
        rpc_query += f" ORDER BY embedding <=> '{embedding_str}'::vector LIMIT {top_k}"

        # Execute via Supabase's rpc or raw postgres
        result = sb.rpc("exec_sql", {"query": rpc_query}).execute()

        if result.data:
            return result.data

    except Exception as exc:
        logger.warning(f"RPC vector search failed on {table}: {exc}")

    # Fallback: simple table query without vector ranking
    try:
        query = sb.table(table).select(select_fields)
        if filter_col and filter_val:
            query = query.eq(filter_col, filter_val)
        query = query.not_.is_("embedding", "null")
        result = query.limit(top_k).execute()
        return [dict(r, similarity=None) for r in result.data]
    except Exception as exc:
        logger.warning(f"Fallback query failed on {table}: {exc}")
        return []

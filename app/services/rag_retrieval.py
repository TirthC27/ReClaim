"""
RAG retrieval service.

Retrieves relevant context from 3 vector sources for a merchant's
offer generation pipeline:
1. merchant_documents (scoped to this merchant only)
2. product_embeddings (general product knowledge)
3. offer_archetypes  (reusable strategy patterns)

Uses typed Supabase RPC functions (created in 006_vector_search_rpcs.sql)
for proper pgvector cosine similarity search.

Supports a `sources` filter to limit retrieval to specific sources
(e.g. only merchant_docs for Step 1's lightweight RAG call).
"""

import logging
from app.db.client import get_supabase
from app.services.embeddings import generate_embedding
from app.services.shopify_inventory import resolve_inventory_item_id

logger = logging.getLogger(__name__)

# All available retrieval sources
ALL_SOURCES = {"merchant_docs", "product_context", "archetypes"}


def resolve_merchant_sku(
    merchant_id: str, product_group_id: str, product_title: str = ""
) -> str | None:
    """Resolve the Shopify SKU belonging to this merchant's group mapping."""
    sb = get_supabase()
    mappings = (sb.table("merchant_products").select("shopify_product_id")
                .eq("merchant_id", str(merchant_id))
                .eq("product_group_id", str(product_group_id))
                .execute().data or [])
    if not mappings:
        return None

    title_tokens = set((product_title or "").lower().split())
    candidates = []
    for mapping in mappings:
        shopify_id = mapping.get("shopify_product_id")
        if not shopify_id:
            continue
        product = (sb.table("products").select("sku,title")
                   .eq("shopify_product_id", str(shopify_id))
                   .limit(1).execute().data)
        info = product[0] if product else None
        if not info or not info.get("sku"):
            info = resolve_inventory_item_id(str(shopify_id))
        if not info or not info.get("sku"):
            continue
        score = len(title_tokens & set((info.get("title") or "").lower().split()))
        candidates.append((score, str(info["sku"])))

    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def retrieve_context(
    merchant_id: str,
    product_title: str,
    product_sku: str = "",
    strategy_hint: str = "",
    top_k: int = 3,
    sources: list[str] | None = None,
) -> dict:
    """
    Build a query from product_title + strategy_hint, embed it,
    and retrieve top-k similar chunks from each vector source.

    Args:
        sources: Optional list of source names to query.
                 Valid values: "merchant_docs", "product_context", "archetypes".
                 If None, queries all three sources.

    Returns a combined context object with text + similarity scores.
    """
    base_query = f"{product_title} {product_sku} pricing stock margin".strip()
    query_text = f"{base_query}. Strategy: {strategy_hint}" if strategy_hint else base_query
    active_sources = set(sources) if sources else ALL_SOURCES

    try:
        query_embedding = generate_embedding(query_text)
    except Exception as exc:
        logger.error(f"Failed to embed query: {exc}")
        return {"merchant_docs": [], "product_context": [], "archetypes": [], "error": str(exc)}

    logger.info(f"[RAG] Query embedding generated — length={len(query_embedding)}, text='{query_text[:80]}...', sources={active_sources}")

    sb = get_supabase()
    result = {}

    # ── 1. Merchant documents (scoped to this merchant) ──────
    if "merchant_docs" in active_sources:
        merchant_docs = _rpc_match_merchant_documents(
            sb, query_embedding, str(merchant_id), top_k
        )
        merchant_docs = _prioritize_product_documents(
            sb, merchant_docs, str(merchant_id), product_sku, product_title, top_k
        )
        logger.info(
            f"[RAG] merchant_documents: {len(merchant_docs)} rows returned"
            + (f", top_similarity={merchant_docs[0].get('similarity', 'N/A')}" if merchant_docs else "")
        )
        result["merchant_docs"] = merchant_docs
    else:
        result["merchant_docs"] = []

    # ── 2. Product embeddings (global) ───────────────────────
    if "product_context" in active_sources:
        product_context = _rpc_match_product_embeddings(
            sb, query_embedding, top_k
        )
        logger.info(
            f"[RAG] product_embeddings: {len(product_context)} rows returned"
            + (f", top_similarity={product_context[0].get('similarity', 'N/A')}" if product_context else "")
        )
        result["product_context"] = product_context
    else:
        result["product_context"] = []

    # ── 3. Offer archetypes (global) ─────────────────────────
    if "archetypes" in active_sources:
        archetypes = _rpc_match_offer_archetypes(
            sb, query_embedding, top_k
        )
        logger.info(
            f"[RAG] offer_archetypes: {len(archetypes)} rows returned"
            + (f", top_similarity={archetypes[0].get('similarity', 'N/A')}" if archetypes else "")
        )
        result["archetypes"] = archetypes
    else:
        result["archetypes"] = []

    return result


def _prioritize_product_documents(
    sb, documents: list[dict], merchant_id: str, product_sku: str,
    product_title: str, top_k: int
) -> list[dict]:
    """Put this merchant's exact SKU row ahead of neighboring catalog rows."""
    if not product_sku:
        return documents
    exact = [d for d in documents if product_sku in (d.get("extracted_text") or "")]
    try:
        query = (sb.table("merchant_documents")
                .select("id,file_name,extracted_text")
                .eq("merchant_id", merchant_id)
                .ilike("extracted_text", f"%{product_sku}%"))
        rows = query.limit(top_k).execute().data or []
        if not rows and product_title:
            # Uploaded merchant CSVs can use a merchant-branded title/SKU
            # (e.g. GAD-008) while Shopify uses the canonical vendor SKU.
            title_words = product_title.split()
            product_phrase = " ".join(title_words[-2:]) if len(title_words) > 1 else product_title
            rows = (sb.table("merchant_documents").select("id,file_name,extracted_text")
                    .eq("merchant_id", merchant_id)
                    .ilike("extracted_text", f"%{product_phrase}%")
                    .limit(top_k).execute().data or [])
        existing = {d.get("id") for d in exact}
        exact.extend({**row, "similarity": None} for row in rows if row.get("id") not in existing)
    except Exception as exc:
        logger.warning("Exact SKU document lookup failed for %s/%s: %s", merchant_id, product_sku, exc)
    exact_ids = {d.get("id") for d in exact}
    supplemental = [d for d in documents if d.get("id") not in exact_ids]
    return (exact + supplemental)[:top_k]


def _rpc_match_merchant_documents(
    sb, query_embedding: list[float], merchant_id: str, top_k: int
) -> list[dict]:
    """
    Call the match_merchant_documents RPC function for vector similarity
    search scoped to a single merchant.
    """
    try:
        result = sb.rpc("match_merchant_documents", {
            "query_embedding": str(query_embedding),
            "match_merchant_id": merchant_id,
            "match_count": top_k,
        }).execute()
        return result.data or []
    except Exception as exc:
        logger.warning(f"[RAG] match_merchant_documents RPC failed: {exc}")
        # Fallback: plain query without vector ranking
        return _fallback_query(sb, "merchant_documents", "id, file_name, extracted_text",
                               filter_col="merchant_id", filter_val=merchant_id, top_k=top_k)


def _rpc_match_product_embeddings(
    sb, query_embedding: list[float], top_k: int
) -> list[dict]:
    """
    Call the match_product_embeddings RPC function for global vector
    similarity search on product embeddings.
    """
    try:
        result = sb.rpc("match_product_embeddings", {
            "query_embedding": str(query_embedding),
            "match_count": top_k,
        }).execute()
        return result.data or []
    except Exception as exc:
        logger.warning(f"[RAG] match_product_embeddings RPC failed: {exc}")
        return _fallback_query(sb, "product_embeddings", "id, product_id, metadata", top_k=top_k)


def _rpc_match_offer_archetypes(
    sb, query_embedding: list[float], top_k: int
) -> list[dict]:
    """
    Call the match_offer_archetypes RPC function for global vector
    similarity search on offer strategy archetypes.
    """
    try:
        result = sb.rpc("match_offer_archetypes", {
            "query_embedding": str(query_embedding),
            "match_count": top_k,
        }).execute()
        return result.data or []
    except Exception as exc:
        logger.warning(f"[RAG] match_offer_archetypes RPC failed: {exc}")
        return _fallback_query(sb, "offer_archetypes", "id, description", top_k=top_k)


def _fallback_query(
    sb,
    table: str,
    select_fields: str,
    filter_col: str | None = None,
    filter_val: str | None = None,
    top_k: int = 3,
) -> list[dict]:
    """
    Fallback: plain table query without vector ranking.
    Used only when the RPC functions are unavailable (e.g. migration not run).
    """
    try:
        query = sb.table(table).select(select_fields)
        if filter_col and filter_val:
            query = query.eq(filter_col, filter_val)
        result = query.limit(top_k).execute()
        logger.warning(f"[RAG] Using fallback (no vector ranking) for {table}: {len(result.data)} rows")
        return [dict(r, similarity=None) for r in result.data]
    except Exception as exc:
        logger.warning(f"[RAG] Fallback query failed on {table}: {exc}")
        return []

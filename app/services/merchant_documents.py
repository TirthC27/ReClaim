"""
Merchant document upload, text extraction, and embedding service.

Handles:
- Uploading files to Supabase Storage (bucket: merchant-documents)
- Extracting text from PDF (pypdf) and DOCX (python-docx)
- Generating embeddings from extracted text
- Storing metadata + embedding in merchant_documents table
"""

import io
import os
from uuid import UUID

from app.db.client import get_supabase
from app.services.embeddings import generate_embedding


BUCKET = "merchant-documents"


def _extract_text_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF file using pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages).strip()


def _extract_text_docx(file_bytes: bytes) -> str:
    """Extract text from a DOCX file using python-docx."""
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs]
    return "\n".join(paragraphs).strip()


def _extract_text(file_bytes: bytes, filename: str) -> str:
    """Detect file type by extension and extract text."""
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return _extract_text_pdf(file_bytes)
    elif ext in (".docx", ".doc"):
        return _extract_text_docx(file_bytes)
    elif ext in (".txt", ".csv", ".md"):
        return file_bytes.decode("utf-8", errors="replace")
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def upload_document(merchant_id: UUID, filename: str, file_bytes: bytes) -> dict:
    """
    Full document pipeline:
    1. Upload to Supabase Storage
    2. Extract text
    3. Generate embedding
    4. Insert merchant_documents row
    """
    sb = get_supabase()

    # ── 1. Upload to Supabase Storage ────────────────────────
    storage_path = f"{merchant_id}/{filename}"
    sb.storage.from_(BUCKET).upload(
        path=storage_path,
        file=file_bytes,
        file_options={"content-type": "application/octet-stream", "upsert": "true"},
    )
    file_url = f"{BUCKET}/{storage_path}"

    # ── 2. Extract text ──────────────────────────────────────
    extracted_text = _extract_text(file_bytes, filename)

    # ── 3. Generate embedding ────────────────────────────────
    embedding: list[float] | None = None
    if extracted_text:
        try:
            embedding = generate_embedding(extracted_text)
        except Exception:
            # Embedding generation is best-effort; log but don't block upload
            embedding = None

    # ── 4. Insert DB row ─────────────────────────────────────
    row = {
        "merchant_id": str(merchant_id),
        "file_name": filename,
        "file_url": file_url,
        "extracted_text": extracted_text or None,
    }
    if embedding:
        row["embedding"] = str(embedding)  # pgvector accepts text representation

    result = sb.table("merchant_documents").insert(row).execute().data[0]
    return result


def list_documents(merchant_id: UUID) -> list[dict]:
    """List all uploaded documents for a merchant."""
    return (
        get_supabase()
        .table("merchant_documents")
        .select("id, merchant_id, file_name, file_url, uploaded_at, extracted_text")
        .eq("merchant_id", str(merchant_id))
        .order("uploaded_at", desc=True)
        .execute()
        .data
    )

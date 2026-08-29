"""
Merchant document upload, text extraction, and embedding service.

Handles:
- Uploading files to Supabase Storage (bucket: merchant-documents)
- Extracting text from PDF (pypdf) and DOCX (python-docx)
- CSV section-aware chunking: splits CSV uploads by logical sections
  (PRODUCT QUOTATION, WARRANTY OPTIONS, ACCESSORY BUNDLE MAP) so that
  RAG retrieval returns the relevant product row instead of the whole file
- Generating embeddings from extracted text
- Storing metadata + embedding in merchant_documents table
"""

import csv
import io
import logging
import os
from uuid import UUID

from app.db.client import get_supabase
from app.services.embeddings import generate_embedding

logger = logging.getLogger(__name__)

BUCKET = "merchant-documents"

# Section headers we detect in CSV files for chunking
CSV_SECTION_HEADERS = [
    "PRODUCT QUOTATION",
    "WARRANTY OPTIONS",
    "ACCESSORY BUNDLE MAP",
]


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


def _is_section_header(row: list[str]) -> str | None:
    """
    Check if a CSV row is a section header.
    Returns the section name if found, None otherwise.

    Section headers are detected by checking if the first cell
    (uppercased, stripped) matches a known section header name.
    """
    if not row:
        return None
    first_cell = row[0].strip().upper()
    for header in CSV_SECTION_HEADERS:
        if header in first_cell:
            return header
    return None


def _chunk_csv(text: str, filename: str) -> list[dict]:
    """
    Split a CSV file into logical section-based chunks.

    Returns a list of dicts, each with:
      - chunk_name: human-readable label (e.g. "PRODUCT QUOTATION", "Row 3")
      - text: the text content of that chunk

    Strategy:
    1. Try to detect section headers (PRODUCT QUOTATION, WARRANTY OPTIONS, etc.)
    2. If sections are found, group rows under their section header
    3. If no sections detected, fall back to row-by-row chunking
       (grouping every 5 rows together to avoid too many tiny chunks)
    """
    lines = text.strip().split("\n")
    if len(lines) <= 2:
        # Too small to chunk — return as single chunk
        return [{"chunk_name": filename, "text": text}]

    # Try parsing with csv reader for better handling
    try:
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
    except Exception:
        rows = [line.split(",") for line in lines]

    if not rows:
        return [{"chunk_name": filename, "text": text}]

    # ── Detect sections ──────────────────────────────────────
    sections: list[dict] = []
    current_section = {"name": "HEADER", "rows": []}

    for row in rows:
        section_name = _is_section_header(row)
        if section_name:
            # Save previous section if it has content
            if current_section["rows"]:
                sections.append(current_section)
            current_section = {"name": section_name, "rows": []}
        else:
            current_section["rows"].append(row)

    # Don't forget the last section
    if current_section["rows"]:
        sections.append(current_section)

    # ── If we found named sections, chunk by section ─────────
    named_sections = [s for s in sections if s["name"] != "HEADER"]
    if named_sections:
        chunks = []
        for section in sections:
            if not section["rows"]:
                continue

            # For PRODUCT QUOTATION, chunk each product row individually
            # (first row in section is typically the column header)
            if section["name"] == "PRODUCT QUOTATION" and len(section["rows"]) > 2:
                # First row = column headers
                col_header = ",".join(section["rows"][0])
                for i, data_row in enumerate(section["rows"][1:], 1):
                    row_text = f"[{section['name']} — Row {i}]\n{col_header}\n{','.join(data_row)}"
                    chunks.append({
                        "chunk_name": f"{filename} | {section['name']} Row {i}",
                        "text": row_text,
                    })
            else:
                # Other sections: keep as one chunk
                section_text = f"[{section['name']}]\n"
                section_text += "\n".join(",".join(r) for r in section["rows"])
                chunks.append({
                    "chunk_name": f"{filename} | {section['name']}",
                    "text": section_text,
                })

        if chunks:
            logger.info(f"CSV section chunking: {len(chunks)} chunks from {len(named_sections)} sections")
            return chunks

    # ── Fallback: group rows (batch of 5) ────────────────────
    chunks = []
    header_row = ",".join(rows[0]) if rows else ""
    batch_size = 5
    data_rows = rows[1:]  # Skip header

    for i in range(0, len(data_rows), batch_size):
        batch = data_rows[i:i + batch_size]
        batch_text = header_row + "\n" + "\n".join(",".join(r) for r in batch)
        chunk_name = f"{filename} | Rows {i + 1}-{min(i + batch_size, len(data_rows))}"
        chunks.append({"chunk_name": chunk_name, "text": batch_text})

    if not chunks:
        return [{"chunk_name": filename, "text": text}]

    logger.info(f"CSV row-batch chunking: {len(chunks)} chunks (batch_size={batch_size})")
    return chunks


def upload_document(merchant_id: UUID, filename: str, file_bytes: bytes) -> dict:
    """
    Full document pipeline:
    1. Upload to Supabase Storage
    2. Extract text
    3. For CSVs: split into section-aware chunks
    4. Generate embedding(s)
    5. Insert merchant_documents row(s)

    Returns the first inserted row (for API response compatibility).
    """
    sb = get_supabase()
    ext = os.path.splitext(filename)[1].lower()

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

    # ── 3. Determine chunks ──────────────────────────────────
    if ext == ".csv" and extracted_text:
        chunks = _chunk_csv(extracted_text, filename)
    else:
        # Non-CSV: single chunk = whole file
        chunks = [{"chunk_name": filename, "text": extracted_text}]

    # ── 4 & 5. Embed + insert each chunk ─────────────────────
    inserted_rows = []
    for chunk in chunks:
        chunk_text = chunk["text"]
        chunk_name = chunk["chunk_name"]

        embedding: list[float] | None = None
        if chunk_text:
            try:
                embedding = generate_embedding(chunk_text)
            except Exception as exc:
                logger.warning(f"Embedding failed for chunk '{chunk_name}': {exc}")
                embedding = None

        row = {
            "merchant_id": str(merchant_id),
            "file_name": chunk_name,
            "file_url": file_url,
            "extracted_text": chunk_text or None,
        }
        if embedding:
            row["embedding"] = str(embedding)

        try:
            result = sb.table("merchant_documents").insert(row).execute().data[0]
            inserted_rows.append(result)
        except Exception as exc:
            logger.error(f"Failed to insert chunk '{chunk_name}': {exc}")

    if not inserted_rows:
        raise ValueError("No document chunks were successfully inserted")

    logger.info(f"Document '{filename}' uploaded: {len(inserted_rows)} chunk(s) created")

    # Return first row for backward compatibility with the API response
    return inserted_rows[0]


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

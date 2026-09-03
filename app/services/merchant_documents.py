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
      - chunk_name: human-readable label (e.g. "PRODUCT QUOTATION Row 13", etc.)
      - text: the text content of that chunk

    Strategy:
    1. Detect section boundaries by column 0 matching a known section name.
       IMPORTANT: These CSVs use the section name as column 0 on EVERY data row,
       not just a single header row. A row belongs to the current section if its
       first cell matches the active section name — only a DIFFERENT section keyword
       signals a real boundary change.
    2. For PRODUCT QUOTATION: emit one chunk per product row (row_text = col header + data row)
    3. For other sections: emit one chunk for the whole section.
    4. Fallback: row-batch chunking if no sections detected.
    """
    lines = text.strip().split("\n")
    if len(lines) <= 2:
        return [{"chunk_name": filename, "text": text}]

    try:
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
    except Exception:
        rows = [line.split(",") for line in lines]

    if not rows:
        return [{"chunk_name": filename, "text": text}]

    # ── Detect sections ──────────────────────────────────────
    # Key fix: a row whose first cell = current section name is a DATA row, not a new boundary.
    # Only switch section when a DIFFERENT known section name appears in column 0.
    sections: list[dict] = []
    current_section = {"name": "HEADER", "rows": []}

    for row in rows:
        detected = _is_section_header(row)
        if detected and detected != current_section["name"]:
            # Genuine section transition — save current and start new
            if current_section["rows"]:
                sections.append(current_section)
            current_section = {"name": detected, "rows": []}
            # The row itself is just the section label — don't append it as a data row
        elif detected and detected == current_section["name"]:
            # Same section name in col 0: this IS a data row, not a new boundary.
            # Strip the leading section-name cell so the row contains only real data.
            current_section["rows"].append(row[1:] if len(row) > 1 else row)
        else:
            current_section["rows"].append(row)

    if current_section["rows"]:
        sections.append(current_section)

    # ── If we found named sections, chunk by section ─────────
    named_sections = [s for s in sections if s["name"] != "HEADER"]
    if named_sections:
        chunks = []
        # Extract the global column header from the HEADER section for use in PRODUCT QUOTATION chunks
        header_section = next((s for s in sections if s["name"] == "HEADER"), None)
        global_col_header = ",".join(header_section["rows"][0]) if header_section and header_section["rows"] else ""
        # Strip the leading "Section" label cell from the column header (it's always col 0)
        if global_col_header.startswith("Section,"):
            global_col_header = global_col_header[len("Section,"):]

        for section in sections:
            if not section["rows"]:
                continue

            # For PRODUCT QUOTATION, chunk each product row individually
            if section["name"] == "PRODUCT QUOTATION":
                # All rows in this section are data rows (col 0 stripped), use global header
                for i, data_row in enumerate(section["rows"], 1):
                    row_text = f"[{section['name']} — Row {i}]\n{global_col_header}\n{','.join(data_row)}"
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
    data_rows = rows[1:]

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
    result_doc = inserted_rows[0]
    
    if ext == ".csv" and extracted_text:
        try:
            auto_group_from_quotation(merchant_id, extracted_text)
        except Exception as exc:
            logger.error(f"Failed to auto-group from quotation: {exc}")
            
    return result_doc


def auto_group_from_quotation(merchant_id: UUID, extracted_text: str):
    """
    Parse the CSV text, detect PRODUCT QUOTATION rows,
    and automatically create product_groups and merchant_products.
    """
    sb = get_supabase()
    
    # 1. Fetch the merchant's vendor name to strip it from products
    merchant = sb.table("merchants").select("shopify_vendor_name, name").eq("id", str(merchant_id)).single().execute().data
    vendor_name = merchant.get("shopify_vendor_name") or merchant.get("name") or ""
    vendor_prefix = vendor_name.split()[0] if vendor_name else ""
    
    # Fetch real Shopify products to map to real IDs instead of demo IDs
    from app.services.shopify import fetch_products_by_vendor
    real_shopify_products = []
    if vendor_name:
        try:
            real_shopify_products = fetch_products_by_vendor(vendor_name)
        except Exception as exc:
            logger.warning(f"Failed to fetch Shopify products for {vendor_name}: {exc}")
            
    # Build a lookup dictionary: sku -> shopify_product_id (string)
    sku_to_shopify_id = {}
    for p in real_shopify_products:
        p_id = str(p.get("id"))
        for variant in p.get("variants", []):
            if variant.get("sku"):
                sku_to_shopify_id[variant["sku"]] = p_id
                
    reader = csv.DictReader(io.StringIO(extracted_text))
    for row in reader:
        # Check if the row belongs to PRODUCT QUOTATION
        # Depending on how the CSV is structured, it might be in 'Section' column or the first column
        if row.get("Section") != "PRODUCT QUOTATION" and list(row.values())[0] != "PRODUCT QUOTATION":
            continue
            
        category = row.get("Category", "General")
        raw_product_name = row.get("Product", row.get("Product Name", ""))
        sku = row.get("SKU", "")
        
        if not raw_product_name or not sku:
            continue
            
        # Strip merchant name prefix to get generic model name
        model_name = raw_product_name
        if vendor_prefix and model_name.startswith(vendor_prefix):
            model_name = model_name[len(vendor_prefix):].strip()
            
        # 1. Upsert product_group (match by model_name or create)
        existing_group = sb.table("product_groups").select("id").eq("model_name", model_name).execute().data
        if existing_group:
            group_id = existing_group[0]["id"]
        else:
            new_group = sb.table("product_groups").insert({
                "model_name": model_name,
                "canonical_sku": f"canonical-{sku}",
                "category": category
            }).execute().data[0]
            group_id = new_group["id"]
            
        # 2. Add to merchant_products map
        # Use the real Shopify Product ID if found, otherwise fallback to a demo ID
        shopify_product_id = sku_to_shopify_id.get(sku, f"demo_shp_{sku}")
        
        # Upsert mapping
        sb.table("merchant_products").upsert({
            "merchant_id": str(merchant_id),
            "shopify_product_id": shopify_product_id,
            "product_group_id": group_id
        }, on_conflict="merchant_id,shopify_product_id").execute()


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

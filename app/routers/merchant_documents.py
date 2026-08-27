"""
Merchant documents router.

POST /merchants/{id}/documents  — upload a document (multipart)
GET  /merchants/{id}/documents  — list uploaded documents
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile, File

from app.services import merchant_documents as svc

router = APIRouter(prefix="/merchants", tags=["merchant-documents"])


@router.post("/{merchant_id}/documents", status_code=201)
async def upload_document(merchant_id: UUID, file: UploadFile = File(...)):
    """
    Upload a document (PDF, DOCX, TXT) for a merchant.

    Pipeline: Storage upload → text extraction → embedding → DB row.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        result = svc.upload_document(merchant_id, file.filename, file_bytes)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")


@router.get("/{merchant_id}/documents")
def list_documents(merchant_id: UUID):
    """List all uploaded documents for a merchant."""
    docs = svc.list_documents(merchant_id)
    return {"documents": docs}

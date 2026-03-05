"""
Documents management API (for RAG knowledge base)
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
from app.db.database import get_db
from app.db.models import Document, User
from app.auth.dependencies import get_current_user, require_admin_or_above
from datetime import datetime
import logging

router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = logging.getLogger(__name__)


class DocumentResponse(BaseModel):
    id: int
    filename: str
    uploaded_at: datetime
    indexed: bool

    class Config:
        from_attributes = True


@router.get("", response_model=List[DocumentResponse])
async def get_documents(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get all documents"""
    documents = db.query(Document).order_by(Document.uploaded_at.desc()).all()
    return documents


@router.post("/upload")
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_above)):
    """Upload document (mock - only saves metadata in demo mode)"""
    logger.info(f"📄 [MOCK DOCUMENT UPLOAD] Filename: {file.filename}")
    logger.info(f"   ⚠️  In production mode, this will:")
    logger.info(f"      1. Save file to storage")
    logger.info(f"      2. Extract text content")
    logger.info(f"      3. Index in ChromaDB for RAG")

    # Read content (mock)
    content = await file.read()
    content_text = content.decode("utf-8", errors="ignore")[:500]  # Preview only

    # Save metadata to DB
    doc = Document(
        filename=file.filename,
        content=content_text,
        file_path=f"/uploads/{file.filename}",
        indexed=False,  # In production, this will be True after ChromaDB indexing
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return {
        "status": "success",
        "document_id": doc.id,
        "filename": file.filename,
        "message": "Document uploaded (mock mode - not actually indexed)",
    }


@router.delete("/{document_id}")
async def delete_document(document_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_above)):
    """Delete document"""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    db.delete(doc)
    db.commit()
    return {"status": "success", "message": "Document deleted"}

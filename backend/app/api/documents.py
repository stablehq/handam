"""
Documents management API (for RAG knowledge base)
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
from app.api.deps import get_tenant_scoped_db
from app.db.models import Document, User
from app.auth.dependencies import get_current_user, require_admin_or_above
from app.api.shared_schemas import ActionResponse
from datetime import datetime
import logging
import os
import uuid

router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'.txt', '.pdf', '.doc', '.docx', '.csv', '.xlsx'}


class DocumentResponse(BaseModel):
    id: int
    filename: str
    uploaded_at: datetime
    indexed: bool

    class Config:
        from_attributes = True


def _doc_to_response(doc: Document) -> DocumentResponse:
    """Convert Document ORM object to DocumentResponse."""
    return DocumentResponse(
        id=doc.id,
        filename=doc.filename,
        uploaded_at=doc.uploaded_at,
        indexed=doc.is_indexed,
    )


@router.get("", response_model=List[DocumentResponse])
async def get_documents(db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Get all documents"""
    documents = db.query(Document).order_by(Document.uploaded_at.desc()).all()
    return [_doc_to_response(d) for d in documents]


@router.post("/upload")
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(require_admin_or_above)):
    """Upload document (mock - only saves metadata in demo mode)"""
    # M16: Path Traversal 방어 - 확장자 검증 및 안전한 파일명 생성
    original_filename = file.filename or ""
    ext = os.path.splitext(original_filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="허용되지 않는 파일 형식입니다")

    safe_filename = f"{uuid.uuid4()}_{os.path.basename(original_filename)}"

    logger.info(f"📄 [MOCK DOCUMENT UPLOAD] Filename: {safe_filename}")
    logger.info(f"   ⚠️  In production mode, this will:")
    logger.info(f"      1. Save file to storage")
    logger.info(f"      2. Extract text content")
    logger.info(f"      3. Index in ChromaDB for RAG")

    # Read content (mock)
    content = await file.read()
    content_text = content.decode("utf-8", errors="ignore")[:500]  # Preview only

    # Save metadata to DB
    doc = Document(
        filename=safe_filename,
        content=content_text,
        file_path=f"/uploads/{safe_filename}",
        is_indexed=False,  # In production, this will be True after ChromaDB indexing
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return {
        "success": True,
        "document_id": doc.id,
        "filename": safe_filename,
        "message": "문서가 업로드되었습니다 (데모 모드)",
    }


@router.delete("/{document_id}", response_model=ActionResponse)
async def delete_document(document_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(require_admin_or_above)):
    """Delete document"""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    db.delete(doc)
    db.commit()
    return {"success": True, "message": "문서가 삭제되었습니다"}

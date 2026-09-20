# backend/app/routers/memory.py
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..models import User, Document, DocumentChunk, LearningProgress
from ..schemas import DocumentResponse, LearningProgressResponse
from .chat import get_current_user

router = APIRouter(prefix="/memory", tags=["Memory"])


@router.get("/documents", response_model=List[DocumentResponse])
def list_documents(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Lists PDFs the user has uploaded, most recent first. Powers the Memory page."""
    return db.query(Document).filter(
        Document.user_id == user.id
    ).order_by(Document.created_at.desc()).all()


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Deletes a document, its indexed chunks, and the underlying PDF file on disk.
    File cleanup is best-effort — if the file's already gone, we don't fail
    the whole request over it.
    """
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == user.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()

    try:
        if os.path.exists(doc.file_path):
            os.remove(doc.file_path)
    except OSError:
        pass

    db.delete(doc)
    db.commit()


@router.get("/learning", response_model=List[LearningProgressResponse])
def list_learning_progress(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Lists topics the TutorAgent has recorded via record_mastery, most recent first."""
    return db.query(LearningProgress).filter(
        LearningProgress.user_id == user.id
    ).order_by(LearningProgress.updated_at.desc()).all()
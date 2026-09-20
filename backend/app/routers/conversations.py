# backend/app/routers/conversations.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..models import User, Conversation, Message
from ..schemas import ConversationSummaryResponse, MessageResponse
from .chat import get_current_user   # reuses the same auth dependency as chat.py

router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.get("/", response_model=List[ConversationSummaryResponse])
def list_conversations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Lists the user's conversations, most recently updated first.
    Powers the sidebar list — this is what makes conversation history
    survive a page refresh instead of living only in browser memory.
    """
    return db.query(Conversation).filter(
        Conversation.user_id == user.id
    ).order_by(Conversation.updated_at.desc()).all()


@router.get("/{conversation_id}/messages", response_model=List[MessageResponse])
def get_conversation_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Returns every message in a conversation, oldest first.
    Called once per conversation, the first time it's opened in a session —
    the frontend caches the result after that, so reopening the same
    conversation later in the same session doesn't refetch.
    """
    convo = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == user.id
    ).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.created_at.asc()).all()


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Deletes a conversation and all its messages.
    Messages must be deleted first — there's no CASCADE on the foreign key,
    so leaving this out would raise an IntegrityError on the DELETE below.
    """
    convo = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == user.id
    ).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    db.query(Message).filter(Message.conversation_id == conversation_id).delete()
    db.delete(convo)
    db.commit()
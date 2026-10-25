# backend/app/routers/chat.py
import os
import json
import shutil
import asyncio
from typing import List, Dict

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from ..database import get_db, SessionLocal
from ..models import User, Conversation, Message
from ..schemas import ChatRequest, MessageResponse
from ..config import settings
from ..services.agents.base import OgunAIAgent
from ..services.agents.configs import SUPERVISOR_CONFIG
from ..services.agents.guards import approve_latest_pending_if_confirmed
from ..services.agents.tools import _process_pdf, store_conversation_memory, generate_conversation_title

router  = APIRouter(prefix="/chat", tags=["Chat"])
_bearer = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db)
) -> User:
    try:
        payload = jwt.decode(credentials.credentials, settings.SECRET_KEY, algorithms=["HS256"])
        email   = payload.get("sub")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def _load_recent_history(db: Session, conversation_id: int, limit: int = 10) -> List[Dict[str, str]]:
    """
    Loads the most recent exchanges in a conversation and converts them into
    the {"role", "content"} shape the agent expects. This is the fix for the
    core bug: without it, every request starts the Supervisor from zero,
    with no awareness of anything said earlier in the SAME conversation.

    'supervisor' (the DB label, used for the frontend's display) becomes
    'assistant' (what the OpenAI-compatible API requires) — two different
    labels for the same thing, one for humans, one for the protocol.

    limit is in exchanges (user+response pairs), so up to limit*2 messages
    are fetched — kept comfortably under MAX_HISTORY in base.py so a resumed
    conversation doesn't need immediate trimming.
    """
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit * 2)
        .all()
    )
    rows.reverse()   # oldest first — chronological order for the agent's history

    history = []
    for row in rows:
        role = "assistant" if row.role == "supervisor" else row.role
        if role not in ("user", "assistant"):
            continue   # skip anything unexpected rather than risk a malformed API call
        history.append({"role": role, "content": row.content})
    return history


@router.post("/", response_model=MessageResponse)
def chat_with_supervisor(
    req: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if req.conversation_id:
        convo = db.query(Conversation).filter(
            Conversation.id == req.conversation_id,
            Conversation.user_id == user.id
        ).first()
        if not convo:
            raise HTTPException(status_code=404, detail="Conversation not found")
        prior_history = _load_recent_history(db, convo.id)
        is_new_conversation = False
    else:
        # Placeholder title — replaced with a real one after the first response
        # comes back, once we actually have content to summarise.
        convo = Conversation(user_id=user.id, title=req.message[:50])
        db.add(convo)
        db.commit()
        db.refresh(convo)
        prior_history = []
        is_new_conversation = True

    db.add(Message(conversation_id=convo.id, role="user", content=req.message))
    db.commit()

    # If this message is a plain "yes / confirm / approve" and a fresh proposal
    # (transfer draft, command awaiting approval) is waiting in this conversation,
    # mark it approved. This runs in code, on the user's raw message, before the
    # agent starts. Nothing the model reads can reach this step.
    approve_latest_pending_if_confirmed(user.id, convo.id, req.message)

    supervisor = OgunAIAgent(
        role_config=SUPERVISOR_CONFIG,
        user_id=user.id,
        conversation_id=convo.id,
        history_messages=prior_history,
    )
    final_text = supervisor.run(req.message)

    if is_new_conversation:
        convo.title = generate_conversation_title(req.message, final_text)
        db.commit()

    agent_msg = Message(conversation_id=convo.id, role="supervisor", content=final_text)
    db.add(agent_msg)
    db.commit()
    db.refresh(agent_msg)

    # Fire-and-forget-style: stores an embedding of this exchange for future
    # cross-conversation recall. Failure here is logged, never raised —
    # a memory-storage hiccup shouldn't break the actual chat response.
    store_conversation_memory(user.id, convo.id, req.message, final_text)

    return agent_msg


@router.post("/stream")
async def stream_chat(
    req: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if req.conversation_id:
        convo = db.query(Conversation).filter(
            Conversation.id == req.conversation_id,
            Conversation.user_id == user.id
        ).first()
        if not convo:
            raise HTTPException(status_code=404, detail="Conversation not found")
        prior_history = _load_recent_history(db, convo.id)
        is_new_conversation = False          # ← was missing
    else:
        convo = Conversation(user_id=user.id, title=req.message[:50])
        db.add(convo)
        db.commit()
        db.refresh(convo)
        prior_history = []
        is_new_conversation = True           # ← was missing

    db.add(Message(conversation_id=convo.id, role="user", content=req.message))
    db.commit()

    user_id  = user.id
    convo_id = convo.id
    msg_text = req.message
    loop     = asyncio.get_event_loop()

    queue: asyncio.Queue = asyncio.Queue()
    final_response        = [None]

    def on_event(event_type: str, data: dict):
        payload = json.dumps({"type": event_type, **data})
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    def run_agent_sync():
        try:
            supervisor = OgunAIAgent(
                role_config=SUPERVISOR_CONFIG,
                user_id=user_id,
                conversation_id=convo_id,
                history_messages=prior_history,
            )
            final_response[0] = supervisor.run(msg_text, event_callback=on_event)

            if is_new_conversation:
                title_db = SessionLocal()
                try:
                    c = title_db.query(Conversation).filter(Conversation.id == convo_id).first()
                    if c:
                        c.title = generate_conversation_title(msg_text, final_response[0])
                        title_db.commit()
                finally:
                    title_db.close()
        except Exception as e:
            final_response[0] = f"Error: {e}"
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(None, run_agent_sync)

    async def event_generator():
        try:
            while True:
                item = await asyncio.wait_for(queue.get(), timeout=120)
                if item is None:
                    break
                yield f"data: {item}\n\n"

            save_db = SessionLocal()
            try:
                msg = Message(
                    conversation_id=convo_id,
                    role="supervisor",
                    content=final_response[0] or ""
                )
                save_db.add(msg)
                save_db.commit()
                save_db.refresh(msg)

                store_conversation_memory(user_id, convo_id, msg_text, final_response[0] or "")

                yield f"data: {json.dumps({'type': 'saved', 'message_id': msg.id, 'conversation_id': convo_id, 'content': msg.content})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': f'Save failed: {e}'})}\n\n"
            finally:
                save_db.close()

        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Agent timed out after 120s'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "Connection":        "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user)
):
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    uploads_dir   = os.path.abspath(settings.UPLOADS_DIR)
    os.makedirs(uploads_dir, exist_ok=True)
    safe_filename = f"{user.id}_{file.filename.replace(' ', '_')}"
    dest_path     = os.path.join(uploads_dir, safe_filename)

    try:
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")
    finally:
        await file.close()

    result = _process_pdf(dest_path, user.id)
    if "error" in result:
        try:
            os.remove(dest_path)
        except OSError:
            pass
        raise HTTPException(status_code=422, detail=result["error"])

    return {
        "message":       "PDF uploaded and indexed successfully.",
        "document_id":   result["document_id"],
        "filename":      file.filename,
        "total_pages":   result["total_pages"],
        "total_chunks":  result["total_chunks"],
        "usage":         f"Say: 'Using document {result['document_id']}, answer: <question>'"
    }
# backend/app/routers/chat.py
import os
import json
import shutil
import asyncio
import threading
from typing import List, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from ..database import get_db, SessionLocal
from ..models import User, Conversation, Message
from ..schemas import ChatRequest, MessageResponse
from ..config import settings
from ..services.agents.base import OgunAIAgent
from ..services.agents.configs import SUPERVISOR_CONFIG
from ..services.agents.formatting import normalize_code_fences
from ..services.agents.guards import approve_latest_pending_if_confirmed, pending_notice, utcnow
from ..services.agents.tools import _process_pdf, store_conversation_memory, generate_conversation_title

router  = APIRouter(prefix="/chat", tags=["Chat"])
_bearer = HTTPBearer()

# The stream sends nothing while a slow tool runs; if nothing at all arrives
# for this long, give up on the turn (and stop the agent, see event_generator).
AGENT_EVENT_TIMEOUT = 120

_SSE_HEADERS = {
    "Cache-Control":     "no-cache",
    "Connection":        "keep-alive",
    "X-Accel-Buffering": "no",
}

STOPPED_REPLY = "Stopped before I finished. Steps that had already completed were not undone."


# ─── Running turns (so the Stop button can find them) ────────────────────────
# One entry per in-flight streamed turn, keyed by (user, conversation). The
# value is the threading.Event the agent loop checks (see guards.is_cancelled).
# The user id is part of the key, so nobody can stop someone else's turn.

_active_runs: Dict[Tuple[int, int], threading.Event] = {}
_active_lock = threading.Lock()


def _register_run(user_id: int, conversation_id: int, event: threading.Event) -> None:
    with _active_lock:
        _active_runs[(user_id, conversation_id)] = event


def _unregister_run(user_id: int, conversation_id: int, event: threading.Event) -> None:
    with _active_lock:
        # Only remove our own entry: a newer turn may have replaced it.
        if _active_runs.get((user_id, conversation_id)) is event:
            del _active_runs[(user_id, conversation_id)]


def _get_run(user_id: int, conversation_id: int) -> Optional[threading.Event]:
    with _active_lock:
        return _active_runs.get((user_id, conversation_id))


# ─── Auth ─────────────────────────────────────────────────────────────────────

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


# ─── Helpers shared by both chat endpoints ───────────────────────────────────

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


def _open_conversation(
    req: ChatRequest, user: User, db: Session
) -> Tuple[Conversation, List[Dict[str, str]], bool]:
    """Find the requested conversation (or start one) and save the user's message in it."""
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
    return convo, prior_history, is_new_conversation


def _save_supervisor_message(db: Session, conversation_id: int, content: str) -> Message:
    msg = Message(conversation_id=conversation_id, role="supervisor", content=content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def _finalize_reply(
    agent_text: str, user_id: int, conversation_id: int, turn_started, cancelled: bool = False
) -> str:
    """
    The text that is saved and shown. Two things happen in code, after the
    model has finished and out of its reach:
      1. untagged / ```text code blocks get their real language tag;
      2. any action that was queued for approval this turn is listed, so the
         user always sees exactly what they would be approving.
    """
    body = STOPPED_REPLY if cancelled else normalize_code_fences(agent_text or "")
    return body + pending_notice(user_id, conversation_id, turn_started)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/", response_model=MessageResponse)
def chat_with_supervisor(
    req: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    convo, prior_history, is_new_conversation = _open_conversation(req, user, db)

    # A plain "yes / approve" is matched in code, on the user's raw message,
    # before the agent starts. Nothing the model reads can reach this step.
    # If it is ambiguous (several actions waiting) or names something that is
    # not waiting, answer right here with code-written text: no agent run.
    approval = approve_latest_pending_if_confirmed(user.id, convo.id, req.message)
    if approval and approval.get("reply"):
        return _save_supervisor_message(db, convo.id, approval["reply"])

    turn_started = utcnow()
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

    agent_msg = _save_supervisor_message(
        db, convo.id, _finalize_reply(final_text, user.id, convo.id, turn_started)
    )

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
    convo, prior_history, is_new_conversation = _open_conversation(req, user, db)

    user_id  = user.id
    convo_id = convo.id
    msg_text = req.message

    # Same approval step as the non-streaming endpoint (this one used to skip
    # it, so "yes" could never approve anything from the streaming UI).
    approval = approve_latest_pending_if_confirmed(user_id, convo_id, msg_text)
    if approval and approval.get("reply"):
        saved = _save_supervisor_message(db, convo_id, approval["reply"])
        saved_id, saved_content = saved.id, saved.content

        async def instant_reply():
            yield _sse({"type": "started", "conversation_id": convo_id})
            yield _sse({"type": "saved", "message_id": saved_id,
                        "conversation_id": convo_id, "content": saved_content})
            yield "data: [DONE]\n\n"

        return StreamingResponse(instant_reply(), media_type="text/event-stream", headers=_SSE_HEADERS)

    loop         = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    cancel_event = threading.Event()
    turn_started = utcnow()
    _register_run(user_id, convo_id, cancel_event)

    def on_event(event_type: str, data: dict):
        payload = json.dumps({"type": event_type, **data})
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    def run_agent_sync():
        """
        Runs the whole turn on a worker thread AND saves its result. Saving
        happens here (not in the SSE generator below) so that a turn the user
        stopped, or whose browser tab closed, still ends with a saved message.
        """
        agent_text = ""
        try:
            try:
                supervisor = OgunAIAgent(
                    role_config=SUPERVISOR_CONFIG,
                    user_id=user_id,
                    conversation_id=convo_id,
                    history_messages=prior_history,
                )
                agent_text = supervisor.run(msg_text, event_callback=on_event, cancel_event=cancel_event)
            except Exception as e:
                agent_text = f"Error: {e}"

            cancelled = cancel_event.is_set()
            failed    = agent_text.startswith("Error: ")

            save_db = SessionLocal()
            try:
                if is_new_conversation and not cancelled and not failed:
                    c = save_db.query(Conversation).filter(Conversation.id == convo_id).first()
                    if c:
                        c.title = generate_conversation_title(msg_text, agent_text)
                        save_db.commit()

                msg = _save_supervisor_message(
                    save_db, convo_id,
                    _finalize_reply(agent_text, user_id, convo_id, turn_started, cancelled=cancelled),
                )
                saved_id, saved_content = msg.id, msg.content
            finally:
                save_db.close()

            if not cancelled and not failed:
                store_conversation_memory(user_id, convo_id, msg_text, agent_text)

            on_event("saved", {
                "message_id": saved_id, "conversation_id": convo_id, "content": saved_content,
            })
        except Exception as e:
            on_event("error", {"message": f"Save failed: {e}"})
        finally:
            _unregister_run(user_id, convo_id, cancel_event)
            loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(None, run_agent_sync)

    async def event_generator():
        try:
            # Tells the frontend the conversation id straight away, so its Stop
            # button can call POST /chat/cancel even for a brand-new chat.
            yield _sse({"type": "started", "conversation_id": convo_id})
            while True:
                item = await asyncio.wait_for(queue.get(), timeout=AGENT_EVENT_TIMEOUT)
                if item is None:
                    break
                yield f"data: {item}\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            # The browser disconnected (tab closed, fetch aborted by Stop).
            # Without this the agent would keep running with nobody listening:
            # still calling the LLM, still able to run tools.
            cancel_event.set()
            raise
        except asyncio.TimeoutError:
            cancel_event.set()
            yield _sse({"type": "error", "message": f"Agent timed out after {AGENT_EVENT_TIMEOUT}s"})
        except Exception as e:
            cancel_event.set()
            yield _sse({"type": "error", "message": str(e)})
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=_SSE_HEADERS)


class CancelRequest(BaseModel):
    conversation_id: int


@router.post("/cancel")
def cancel_run(req: CancelRequest, user: User = Depends(get_current_user)):
    """
    The Stop button. Tells the running agent for this conversation to stop at
    its next step: no further LLM calls, no further tools, and a shell command
    already running is killed. Steps that already finished are not undone.
    """
    event = _get_run(user.id, req.conversation_id)
    if event is None:
        return {"cancelled": False, "detail": "Nothing is running for that conversation."}
    event.set()
    return {"cancelled": True}


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

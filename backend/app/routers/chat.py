# backend/app/routers/chat.py
import os
import json
import shutil
import asyncio
from concurrent.futures import ThreadPoolExecutor

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
from ..services.agents.tools import _process_pdf

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


@router.post("/", response_model=MessageResponse)
def chat_with_supervisor(
    req: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Blocking chat endpoint. Waits for full response before returning."""
    if req.conversation_id:
        convo = db.query(Conversation).filter(
            Conversation.id == req.conversation_id,
            Conversation.user_id == user.id
        ).first()
        if not convo:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        convo = Conversation(user_id=user.id, title=req.message[:50])
        db.add(convo)
        db.commit()
        db.refresh(convo)

    db.add(Message(conversation_id=convo.id, role="user", content=req.message))
    db.commit()

    supervisor = OgunAIAgent(
        role_config=SUPERVISOR_CONFIG,
        user_id=user.id,
        conversation_id=convo.id
    )
    final_text = supervisor.run(req.message)

    agent_msg = Message(conversation_id=convo.id, role="supervisor", content=final_text)
    db.add(agent_msg)
    db.commit()
    db.refresh(agent_msg)
    return agent_msg


@router.post("/stream")
async def stream_chat(
    req: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Streaming chat endpoint using Server-Sent Events.
    Use with @microsoft/fetch-event-source on the frontend (supports auth headers).
    
    Event types:
      thinking       — agent is about to call the LLM
      tool_call      — agent is about to execute a tool
      tool_result    — tool finished, includes success flag and preview
      specialist_start / specialist_done — Supervisor delegation events
      agent_done     — specialist finished its loop
      saved          — final message saved to DB (includes message_id)
      error          — something went wrong
      [DONE]         — stream is finished, close the connection
    """
    # ── All DB work happens synchronously here, before the generator starts ──
    if req.conversation_id:
        convo = db.query(Conversation).filter(
            Conversation.id == req.conversation_id,
            Conversation.user_id == user.id
        ).first()
        if not convo:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        convo = Conversation(user_id=user.id, title=req.message[:50])
        db.add(convo)
        db.commit()
        db.refresh(convo)

    db.add(Message(conversation_id=convo.id, role="user", content=req.message))
    db.commit()

    # Capture IDs for use inside the generator thread (DB sessions are not thread-safe)
    user_id  = user.id
    convo_id = convo.id
    msg_text = req.message
    loop     = asyncio.get_event_loop()

    # Queue bridges the sync agent thread → async generator
    queue: asyncio.Queue = asyncio.Queue()
    final_response        = [None]  # mutable holder for agent result

    def on_event(event_type: str, data: dict):
        """Sync callback. Forwards agent events into the async queue safely."""
        payload = json.dumps({"type": event_type, **data})
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    def run_agent_sync():
        """Runs in a thread pool. Never touches the FastAPI event loop directly."""
        try:
            supervisor = OgunAIAgent(
                role_config=SUPERVISOR_CONFIG,
                user_id=user_id,
                conversation_id=convo_id,
            )
            final_response[0] = supervisor.run(msg_text, event_callback=on_event)
        except Exception as e:
            final_response[0] = f"Error: {e}"
        finally:
            # Sentinel — tells the generator the agent is done
            loop.call_soon_threadsafe(queue.put_nowait, None)

    # Start agent in a thread — don't await it, the generator reads events as they arrive
    loop.run_in_executor(None, run_agent_sync)

    async def event_generator():
        try:
            while True:
                item = await asyncio.wait_for(queue.get(), timeout=120)
                if item is None:
                    break
                yield f"data: {item}\n\n"

            # ── Save final response to DB with a fresh session ──
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
            "X-Accel-Buffering": "no",   # Tells nginx not to buffer SSE responses
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
# backend/app/schemas.py
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional, Any, List

# --- Auth Schemas ---
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None

class UserResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: Optional[str]
    role: str
    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class ApiKeyCreate(BaseModel):
    name: str

class ApiKeyResponse(BaseModel):
    id: int
    key_prefix: str
    name: str
    raw_key: Optional[str] = None
    created_at: datetime
    class Config:
        from_attributes = True

# --- Chat Schemas ---
class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[int] = None

class ToolCallSchema(BaseModel):
    name: str
    arguments: dict

class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    role: str
    agent_name: Optional[str]
    content: str
    tool_calls: Optional[List[ToolCallSchema]]
    created_at: datetime
    class Config:
        from_attributes = True

# --- Memory Schemas ---
class FactCreate(BaseModel):
    key: str
    value: str
    scope: str = "global"

class EpisodeCreate(BaseModel):
    agent_name: str
    action: str
    metadata: Optional[dict] = None
    feedback: Optional[int] = None
    result: Optional[dict] = None

# --- Phase 4: Conversations & Memory Browsing ---

class ConversationSummaryResponse(BaseModel):
    """Sidebar list item — no messages included, just enough to render the list."""
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True

class DocumentResponse(BaseModel):
    """Metadata only — never returns chunk text, that stays server-side for RAG."""
    id: int
    filename: str
    total_pages: Optional[int]
    total_chunks: int
    created_at: datetime
    class Config:
        from_attributes = True

class LearningProgressResponse(BaseModel):
    """One row per topic the TutorAgent has recorded via record_mastery."""
    id: int
    topic: str
    confidence: int
    updated_at: datetime
    class Config:
        from_attributes = True
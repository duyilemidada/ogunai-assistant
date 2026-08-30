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
    raw_key: Optional[str] = None # Only present on creation
    created_at: datetime
    class Config:
        from_attributes = True

# --- Chat Schemas ---
class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[int] = None # If None, start new convo

class ToolCallSchema(BaseModel):
    name: str
    arguments: dict

class MessageResponse(BaseModel):
    id: int
    role: str
    agent_name: Optional[str]
    content: str
    tool_calls: Optional[List[ToolCallSchema]]
    created_at: datetime
    class Config:
        from_attributes = True

# --- Memory Schemas (For Random Forest data collection) ---
class FactCreate(BaseModel):
    key: str
    value: str
    scope: str = "global"

class EpisodeCreate(BaseModel):
    agent_name: str
    action: str
    metadata: Optional[dict] = None
    feedback: Optional[int] = None # 1 or 0
    result: Optional[dict] = None
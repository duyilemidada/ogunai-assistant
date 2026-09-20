# backend/app/models.py
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean,
    ForeignKey, JSON, LargeBinary, Float, Date
)
from datetime import datetime, date, UTC
from .database import Base


# ─── Auth & Core ─────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    role = Column(String, default="user")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    last_login = Column(DateTime, nullable=True)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    key_prefix = Column(String, index=True)
    key_hash = Column(String, nullable=False)
    name = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, default="New Conversation")
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    role = Column(String, nullable=False)
    agent_name = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    tool_calls = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class Fact(Base):
    """Reserved for a future explicit 'remember this' tool (key/value facts).
    Distinct from ConversationMemory below, which is automatic and exchange-level."""
    __tablename__ = "facts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    scope = Column(String, default="global")
    key = Column(String, nullable=False)
    value = Column(Text, nullable=False)
    embedding = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class Episode(Base):
    __tablename__ = "episodes"
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    agent_name = Column(String, nullable=False)
    action = Column(String, nullable=False)
    meta_data = Column(JSON, nullable=True)
    feedback = Column(Integer, nullable=True)
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class UserLike(Base):
    __tablename__ = "user_likes"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    item_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    embedding = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


# ─── Fitness ─────────────────────────────────────────────────────────────────

class DailyNutrition(Base):
    __tablename__ = "daily_nutrition"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False, default=lambda: date.today())
    food_name = Column(String, nullable=False)
    portion_grams = Column(Float, nullable=False)
    calories = Column(Float, default=0.0)
    protein_grams = Column(Float, default=0.0)
    carb_grams = Column(Float, default=0.0)
    fat_grams = Column(Float, default=0.0)
    fiber_grams = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class WorkoutLog(Base):
    __tablename__ = "workout_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False, default=lambda: date.today())
    exercise_name = Column(String, nullable=False)
    sets = Column(Integer, nullable=False)
    reps = Column(Integer, nullable=False)
    load_kg = Column(Float, nullable=False)
    rpe = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class PhysicalStatus(Base):
    __tablename__ = "physical_status"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False, default=lambda: date.today())
    pain_level = Column(Integer, nullable=False)
    injury_site = Column(String, nullable=True)
    sleep_hours = Column(Float, nullable=False)
    energy_level = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


# ─── Documents (RAG pipeline) ─────────────────────────────────────────────────

class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    total_pages = Column(Integer, nullable=True)
    total_chunks = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=True)
    text = Column(Text, nullable=False)
    embedding = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


# ─── Learning (Tutor) ──────────────────────────────────────────────────────────

class LearningProgress(Base):
    __tablename__ = "learning_progress"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    topic = Column(String, nullable=False)
    confidence = Column(Integer, nullable=False)
    gap_identified = Column(Boolean, default=False)
    prerequisite_for = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


# ─── Cross-conversation memory ────────────────────────────────────────────────

class ConversationMemory(Base):
    """
    One embedded record per completed exchange (user message + Ogun's final
    answer), stored across ALL conversations for this user. Separate from
    Message (which holds the full raw transcript for display) — this table
    exists purely so recall_memory can search everything ever discussed,
    the same way Scout searches past audit findings: sentence-transformers
    + numpy cosine similarity, no vector database, no compiled dependency.
    """
    __tablename__ = "conversation_memory"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    summary = Column(Text, nullable=False)           # capped exchange text
    embedding = Column(LargeBinary, nullable=False)  # float32 bytes, 384 dims
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
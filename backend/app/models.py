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
    feedback = Column(Integer, nullable=True)   # 1 = good, 0 = bad — set via UI
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class UserLike(Base):
    """Stores explicit likes for the content-based recommender and XGBoost affinity model."""
    __tablename__ = "user_likes"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    item_type = Column(String, nullable=False)      # 'book', 'movie', 'product', etc.
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    embedding = Column(LargeBinary, nullable=False)  # float32 bytes
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


# ─── Fitness ─────────────────────────────────────────────────────────────────

class DailyNutrition(Base):
    """One row per food item logged per day. Macros from USDA FoodData Central."""
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
    """One row per exercise per session. Volume = sets × reps × load_kg."""
    __tablename__ = "workout_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False, default=lambda: date.today())
    exercise_name = Column(String, nullable=False)
    sets = Column(Integer, nullable=False)
    reps = Column(Integer, nullable=False)
    load_kg = Column(Float, nullable=False)
    rpe = Column(Integer, nullable=True)            # 1–10
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class PhysicalStatus(Base):
    """Daily recovery snapshot. pain_level > 5 within 3 days = positive injury label."""
    __tablename__ = "physical_status"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False, default=lambda: date.today())
    pain_level = Column(Integer, nullable=False)    # 0–10
    injury_site = Column(String, nullable=True)
    sleep_hours = Column(Float, nullable=False)
    energy_level = Column(Integer, nullable=True)   # 1–10
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


# ─── Documents (RAG pipeline) ─────────────────────────────────────────────────

class Document(Base):
    """Metadata for ingested PDFs. One row per file upload."""
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)      # Absolute path on disk
    total_pages = Column(Integer, nullable=True)
    total_chunks = Column(Integer, default=0)       # Updated after chunking
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class DocumentChunk(Base):
    """
    Text chunks from a Document with embeddings for semantic search.
    Cosine similarity against a question embedding gives us the relevant context.
    """
    __tablename__ = "document_chunks"
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)   # Ordering within the document
    page_number = Column(Integer, nullable=True)    # Source page — used in citations
    text = Column(Text, nullable=False)
    embedding = Column(LargeBinary, nullable=False) # float32 bytes, 384 dims
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

class LearningProgress(Base):
    """
    Tracks topics the user has studied and their self-reported confidence.
    confidence: 1 = just heard of it → 5 = can teach it to others.
    Used by TutorAgent to avoid re-teaching mastered concepts and to
    identify prerequisite gaps before starting a new topic.
    """
    __tablename__ = "learning_progress"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    topic = Column(String, nullable=False)          # lowercase, normalised
    confidence = Column(Integer, nullable=False)    # 1–5
    gap_identified = Column(Boolean, default=False) # True if this was flagged as a gap
    prerequisite_for = Column(String, nullable=True)# e.g. "XGBoost" if this is needed for that
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
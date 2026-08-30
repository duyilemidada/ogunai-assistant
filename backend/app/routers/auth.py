# backend/app/routers/auth.py
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from datetime import datetime, UTC

from ..database import get_db
from ..models import User, ApiKey
from ..schemas import LoginRequest, Token, UserCreate, UserResponse, ApiKeyCreate, ApiKeyResponse
from ..core.security import hash_password, verify_password, create_access_token, generate_api_key
from ..core.exceptions import AuthenticationError, ConflictError
from .chat import get_current_user
router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, db: Session = Depends(get_db)):
    # First user becomes admin automatically
    user_count = db.query(User).count()
    role = "admin" if user_count == 0 else "user"
    
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise ConflictError(f"Email '{data.email}' is already registered")
        
    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        role=role
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@router.post("/login", response_model=Token)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise AuthenticationError("Invalid email or password")
        
    user.last_login = datetime.now(UTC)
    db.commit()
    
    token = create_access_token(subject=user.email)
    return Token(access_token=token)


@router.post("/keys", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(
    data: ApiKeyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Generate a new API key for the authenticated user.

    The raw key is returned ONCE in this response.
    We store only the prefix + bcrypt hash — the raw key is not recoverable.
    If the user loses it, they must generate a new one.
    """
    raw_key, prefix, key_hash = generate_api_key()

    api_key = ApiKey(
        user_id=current_user.id,
        key_prefix=prefix,
        key_hash=key_hash,
        name=data.name
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    # Return the raw key in the response — this is the ONLY time it's visible
    response = ApiKeyResponse(
        id=api_key.id,
        key_prefix=prefix,
        name=api_key.name,
        raw_key=raw_key,  # Only in creation response
        created_at=api_key.created_at
    )
    return response


@router.get("/keys", response_model=list[ApiKeyResponse])
def list_api_keys(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List your API keys. Raw key is NOT shown — only prefix and metadata."""
    keys = db.query(ApiKey).filter(
        ApiKey.user_id == current_user.id,
        ApiKey.is_active == True
    ).all()
    return keys


@router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Revoke (soft-delete) an API key."""
    api_key = db.query(ApiKey).filter(
        ApiKey.id == key_id,
        ApiKey.user_id == current_user.id  # can only revoke your own keys
    ).first()

    if not api_key:
        from ..core.exceptions import NotFoundError
        raise NotFoundError("API key")

    api_key.is_active = False
    db.commit()


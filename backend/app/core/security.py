# backend/app/core/security.py
import secrets
import bcrypt
from datetime import datetime, timedelta, UTC
from typing import Tuple
from jose import jwt, JWTError
from ..config import settings

def hash_password(password: str) -> str:
    pwd_bytes = password.encode('utf-8')
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_access_token(subject: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"exp": expire, "sub": subject}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")

def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except JWTError:
        return None

def generate_api_key() -> Tuple[str, str, str]:
    """
    Generates an API key.
    Returns: (raw_key, prefix, bcrypt_hash)
    - raw_key: shown to user ONCE
    - prefix: stored in DB for identification (O(1) lookup)
    - bcrypt_hash: stored in DB for secure verification
    """
    raw_key = secrets.token_urlsafe(32)
    prefix = raw_key[:8]
    hashed = bcrypt.hashpw(raw_key.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    return raw_key, prefix, hashed



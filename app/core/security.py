from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials as HTTPAuthCredentials
from passlib.context import CryptContext
from jose import jwt, JWTError

from app.core.config import settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
security = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials or token has expired",
        ) from exc


def create_refresh_token(data: dict) -> str: 
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=7)  # Refresh token lasts 7 days
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_password_reset_token(user_id: int) -> str:
    """Generate a secure short-lived token for password recovery."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)  # Link expires in 15 mins
    to_encode = {"sub": str(user_id), "exp": expire, "action": "password_reset"}
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    
    
async def get_current_user(credentials: HTTPAuthCredentials = Depends(security)) -> dict:
    """
    FastAPI Dependency injection provider to guard protected API routes.
    Automatically parses incoming request authorization headers.
    """
    token = credentials.credentials
    payload = decode_token(token)
    sub_value = payload.get("sub")
    if sub_value is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload is missing subject identity data context.",
        )
    return payload
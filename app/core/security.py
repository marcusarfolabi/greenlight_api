from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi.security import APIKeyCookie
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from passlib.context import CryptContext
from jose import jwt, JWTError

from app.core.config import settings
from app.schemas.user import AuthContext

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
security = HTTPBearer()
from fastapi import Request # Add this import

cookie_scheme = APIKeyCookie(
name="auth_token",
auto_error=False
)

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
    


# async def get_current_user(request: Request) -> AuthContext:
#     token = request.cookies.get("auth_token")
#     if not token:
#         raise HTTPException(status_code=401, detail="Not authenticated")
    
#     payload = decode_token(token)
#     user_id = payload.get("sub")
    
#     if user_id is None:
#         raise HTTPException(status_code=401, detail="Invalid token payload")

#     # Return the structured model
#     return AuthContext(
#         token=token,
#         user_id=int(user_id),
#         role=payload.get("role", "user"),
#         username=payload.get("username", "")
#     )

async def get_current_user(request: Request) -> AuthContext:

    token = request.cookies.get("auth_token")
    
    if not token:
        # Debugging: log what cookies ARE present
        print(f"DEBUG: Cookies received: {request.cookies}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    payload = decode_token(token)

    user_id = payload.get("sub")

    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid token payload"
        )

    org_id = payload.get("org_id")
    
    return AuthContext(
        token=token,
        user_id=int(user_id),
        org_id=int(org_id) if org_id else 0,
        role=payload.get("role", "user"),
        username=payload.get("username", "")
    )
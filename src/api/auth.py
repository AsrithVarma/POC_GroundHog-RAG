import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from jose import JWTError, jwt
from passlib.context import CryptContext

logger = logging.getLogger(__name__)

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 1

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# --- Password hashing ---


def hash_password(plaintext: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return pwd_context.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return pwd_context.verify(plaintext, hashed)


# --- JWT creation and validation ---


def create_token(
    user_id: str,
    username: str,
    access_group: str,
    role: str,
) -> str:
    """Create a signed JWT with user claims and 1-hour expiry."""
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS)
    payload = {
        "sub": user_id,
        "username": username,
        "access_group": access_group,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT, returning the claims dict.

    Raises JWTError on invalid or expired tokens.
    """
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# --- FastAPI dependency ---


def get_current_user(request: Request) -> dict:
    """FastAPI dependency that extracts and validates the JWT from the
    Authorization header. Returns a dict with user_id, username,
    access_group, and role.

    Usage:
        @app.get("/protected")
        def endpoint(user: dict = Depends(get_current_user)):
            ...
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
        )

    token = auth_header[7:]
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {
        "user_id": payload["sub"],
        "username": payload.get("username"),
        "access_group": payload.get("access_group"),
        "role": payload.get("role"),
    }

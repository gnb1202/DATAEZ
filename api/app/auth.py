import base64
import hashlib
import hmac
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

logger = logging.getLogger(__name__)
from .db import (
    create_refresh_token_record,
    create_user,
    get_refresh_token_record,
    get_user_by_email,
    get_user_by_id,
    revoke_refresh_token,
)

bearer_scheme = HTTPBearer()
REFRESH_TOKEN_TYPE = "refresh"
ACCESS_TOKEN_TYPE = "access"


def signup(email: str, password: str, name: str = "") -> dict:
    """Register a new user and return access + refresh tokens."""
    if get_user_by_email(email):
        raise HTTPException(status_code=409, detail="Email already exists")
    _validate_password_policy(password)

    user_id = str(uuid4())
    password_hash = _hash_password(password)
    _ = name  # Reserved for future profile support.
    create_user(user_id=user_id, email=email, password_hash=password_hash)
    access_token = create_access_token(user_id=user_id, email=email)
    refresh_token = create_refresh_token(user_id=user_id, email=email)
    logger.info("User signed up: %s", email)
    return {"user_id": user_id, "access_token": access_token, "refresh_token": refresh_token}


def login(email: str, password: str) -> dict:
    """Authenticate user by email/password and return tokens."""
    user = get_user_by_email(email)
    if not user or not _verify_password(password, user["password_hash"]):
        logger.warning("Failed login attempt for %s", email)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user_id = str(user["id"])
    access_token = create_access_token(user_id=user_id, email=user["email"])
    refresh_token = create_refresh_token(user_id=user_id, email=user["email"])
    logger.info("User logged in: %s", email)
    return {"user_id": user_id, "access_token": access_token, "refresh_token": refresh_token}


def create_access_token(user_id: str, email: str) -> str:
    """Create a short-lived JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_exp_minutes)
    payload = {"sub": user_id, "email": email, "token_type": ACCESS_TOKEN_TYPE, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str, email: str) -> str:
    """Create a long-lived refresh token and persist its hash in DB."""
    token_id = str(uuid4())
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_exp_days)
    payload = {
        "sub": user_id,
        "email": email,
        "token_type": REFRESH_TOKEN_TYPE,
        "jti": token_id,
        "exp": expire,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    create_refresh_token_record(
        token_id=token_id,
        user_id=user_id,
        token_hash=_hash_token(token),
        expires_at=expire.replace(tzinfo=None),
    )
    return token


def refresh_access_token(refresh_token: str) -> dict:
    """Rotate refresh token: revoke old, issue new access + refresh pair."""
    payload = _decode_token(refresh_token)
    if payload.get("token_type") != REFRESH_TOKEN_TYPE:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    token_hash = _hash_token(refresh_token)
    record = get_refresh_token_record(token_hash)
    if not record or record["revoked_at"] is not None:
        raise HTTPException(status_code=401, detail="Refresh token revoked or not found")

    now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    if record["expires_at"] <= now_utc_naive:
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user_id = payload.get("sub")
    email = payload.get("email")
    if not user_id or not email:
        raise HTTPException(status_code=401, detail="Invalid refresh token payload")

    access_token = create_access_token(user_id=user_id, email=email)
    new_refresh_token = create_refresh_token(user_id=user_id, email=email)
    revoke_refresh_token(token_hash)
    return {"user_id": user_id, "access_token": access_token, "refresh_token": new_refresh_token}


def logout_refresh_token(refresh_token: str) -> None:
    """Revoke a refresh token on logout."""
    revoke_refresh_token(_hash_token(refresh_token))


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    """FastAPI dependency: extract and validate user from Bearer token."""
    payload = _decode_token(credentials.credentials)
    if payload.get("token_type") != ACCESS_TOKEN_TYPE:
        raise HTTPException(status_code=401, detail="Invalid access token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return {"id": str(user["id"]), "email": user["email"]}


def _hash_password(password: str) -> str:
    iterations = 200000
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    salt_b64 = base64.b64encode(salt).decode("utf-8")
    digest_b64 = base64.b64encode(digest).decode("utf-8")
    return f"pbkdf2_sha256${iterations}${salt_b64}${digest_b64}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, iterations_str, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        salt = base64.b64decode(salt_b64.encode("utf-8"))
        expected = base64.b64decode(digest_b64.encode("utf-8"))
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(candidate, expected)
    except (ValueError, KeyError):
        # Malformed hash string (wrong number of $ parts, bad base64, etc.)
        return False
    except Exception:
        logger.warning("Unexpected error during password verification", exc_info=True)
        return False


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _validate_password_policy(password: str) -> None:
    if len(password) < 10:
        raise HTTPException(status_code=400, detail="Password must be at least 10 characters")
    if not any(ch.islower() for ch in password):
        raise HTTPException(status_code=400, detail="Password must include a lowercase letter")
    if not any(ch.isupper() for ch in password):
        raise HTTPException(status_code=400, detail="Password must include an uppercase letter")
    if not any(ch.isdigit() for ch in password):
        raise HTTPException(status_code=400, detail="Password must include a number")
    if not any(not ch.isalnum() for ch in password):
        raise HTTPException(status_code=400, detail="Password must include a special character")

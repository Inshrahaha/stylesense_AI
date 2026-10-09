"""
Auth router — registration, login, logout, refresh, me.

Security: argon2id, JWT access + rotating refresh tokens with
reuse detection (reuse revokes the whole family), rate limiting,
generic error messages (no user enumeration), audit logging.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.audit import log_audit_event
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    hash_ip,
    hash_ua,
    password_needs_rehash,
    validate_password_strength,
    verify_password,
)
from app.db.models.models import Profile, RefreshToken, User
from app.db.session import get_db
from app.deps import get_client_ip, get_current_user, get_rate_limiter

logger = get_logger("auth")

router = APIRouter(prefix="/auth", tags=["auth"])


# ──────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=10, max_length=128)
    name: str | None = Field(None, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None = None
    is_active: bool
    is_admin: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

async def _create_refresh_token_in_db(
    db: AsyncSession,
    user_id: uuid.UUID,
    request: Request,
    family_id: uuid.UUID | None = None,
) -> str:
    """Create a refresh token, store the hash, and return the raw token."""
    settings = get_settings()
    raw_token = generate_refresh_token()
    token_hash_val = hash_token(raw_token)
    fid = family_id or uuid.uuid4()

    rt = RefreshToken(
        user_id=user_id,
        token_hash=token_hash_val,
        family_id=fid,
        expires_at=datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_expire_days),
        ua_hash=hash_ua(request.headers.get("user-agent", "")),
        ip_hash=hash_ip(get_client_ip(request)),
    )
    db.add(rt)
    await db.flush()
    return raw_token


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Set the refresh token as an httpOnly secure cookie."""
    settings = get_settings()
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
        max_age=settings.jwt_refresh_token_expire_days * 86400,
        path="/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Clear the refresh token cookie."""
    response.delete_cookie(key="refresh_token", path="/auth")


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Register a new user account."""
    limiter = get_rate_limiter()
    client_ip = get_client_ip(request)

    # Rate limit registration by IP
    if await limiter.is_rate_limited(f"register:ip:{client_ip}", 5, 300):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests.")

    # Validate password strength
    pwd_error = validate_password_strength(body.password)
    if pwd_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=pwd_error)

    # Check if email exists (generic error to prevent enumeration)
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    # Create user
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.flush()

    # Create profile
    profile = Profile(user_id=user.id, name=body.name)
    db.add(profile)

    # Create tokens
    access_token = create_access_token(user.id)
    raw_refresh = await _create_refresh_token_in_db(db, user.id, request)
    _set_refresh_cookie(response, raw_refresh)

    await log_audit_event(db, "register", user.id, client_ip)
    await db.commit()

    logger.info("User registered", extra={"user_id": str(user.id)})
    return TokenResponse(access_token=access_token)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Authenticate and receive tokens."""
    limiter = get_rate_limiter()
    client_ip = get_client_ip(request)

    # Rate limit login by IP
    if await limiter.is_rate_limited(
        f"login:ip:{client_ip}",
        get_settings().rate_limit_login_per_minute,
        60,
    ):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests.")

    # Look up user — generic error on failure
    result = await db.execute(
        select(User).where(User.email == body.email.lower(), User.is_active == True, User.deleted_at == None)
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        # Also rate limit per-account to prevent brute force on known emails
        if user:
            await limiter.is_rate_limited(f"login:account:{user.id}", 5, 300)
            await log_audit_event(db, "login_failed", user.id, client_ip)
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    # Rehash if needed (argon2 params changed)
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    # Create tokens
    access_token = create_access_token(user.id, user.is_admin)
    raw_refresh = await _create_refresh_token_in_db(db, user.id, request)
    _set_refresh_cookie(response, raw_refresh)

    await log_audit_event(db, "login", user.id, client_ip)
    await db.commit()

    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Rotate the refresh token and return a new access token.
    Reuse detection: if a previously-used token is presented,
    revoke the entire family (potential token theft).
    """
    raw_token = request.cookies.get("refresh_token")
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token.")

    token_hash_val = hash_token(raw_token)
    client_ip = get_client_ip(request)

    # Look up the token
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash_val)
    )
    stored = result.scalar_one_or_none()

    if stored is None:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")

    # Reuse detection: if this token was already replaced, revoke the whole family
    if stored.revoked_at is not None or stored.replaced_by is not None:
        # Token reuse detected! Revoke entire family
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == stored.family_id)
            .values(revoked_at=datetime.now(UTC))
        )
        await log_audit_event(
            db, "token_reuse_detected", stored.user_id, client_ip,
            meta={"family_id": str(stored.family_id)},
        )
        await db.commit()
        _clear_refresh_cookie(response)
        logger.warning(
            "Refresh token reuse detected — family revoked",
            extra={"user_id": str(stored.user_id), "family_id": str(stored.family_id)},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")

    # Check expiration
    if stored.expires_at < datetime.now(UTC):
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired.")

    # Verify user still active
    user_result = await db.execute(
        select(User).where(User.id == stored.user_id, User.is_active == True, User.deleted_at == None)
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")

    # Rotate: create new token in same family, mark old as replaced
    new_raw = await _create_refresh_token_in_db(db, user.id, request, family_id=stored.family_id)

    # Get the new token's ID for the replaced_by field
    new_result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(new_raw),
        )
    )
    new_stored = new_result.scalar_one()

    stored.revoked_at = datetime.now(UTC)
    stored.replaced_by = new_stored.id

    access_token = create_access_token(user.id, user.is_admin)
    _set_refresh_cookie(response, new_raw)

    await log_audit_event(db, "token_refresh", user.id, client_ip)
    await db.commit()

    return TokenResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Revoke the current refresh token and clear the cookie."""
    raw_token = request.cookies.get("refresh_token")
    if raw_token:
        token_hash_val = hash_token(raw_token)
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash_val)
        )
        stored = result.scalar_one_or_none()
        if stored and stored.user_id == user.id:
            stored.revoked_at = datetime.now(UTC)

    _clear_refresh_cookie(response)
    await log_audit_event(db, "logout", user.id, get_client_ip(request))
    await db.commit()


@router.get("/me", response_model=MeResponse)
async def get_me(user: Annotated[User, Depends(get_current_user)]):
    """Get the current authenticated user's info."""
    name = None
    if user.profile:
        name = user.profile.name
    return MeResponse(
        id=user.id,
        email=user.email,
        name=name,
        is_active=user.is_active,
        is_admin=user.is_admin,
        created_at=user.created_at,
    )

"""
Security utilities — JWT, password hashing (argon2id), token management.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import HashingError, VerificationError, VerifyMismatchError

from app.config import get_settings

# Argon2id hasher with sensible defaults
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MB
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,  # argon2id
)

# Small common-password block list (extend as needed)
COMMON_PASSWORDS = frozenset([
    "password123", "12345678901", "qwerty12345", "letmein1234",
    "welcome1234", "monkey12345", "1234567890a", "abc12345678",
    "password1234", "iloveyou123", "admin123456", "changeme123",
])


def hash_password(password: str) -> str:
    """Hash a password with argon2id."""
    return _hasher.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time password verification. Returns False on mismatch."""
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, HashingError):
        return False


def password_needs_rehash(hashed: str) -> bool:
    """Check if the hash parameters are outdated."""
    return _hasher.check_needs_rehash(hashed)


def validate_password_strength(password: str) -> str | None:
    """
    Validate password strength. Returns an error message or None if valid.
    Requirements: min 10 chars, not in common list.
    """
    if len(password) < 10:
        return "Password must be at least 10 characters long."
    if password.lower() in COMMON_PASSWORDS:
        return "This password is too common. Please choose a stronger password."
    return None


def create_access_token(user_id: uuid.UUID, is_admin: bool = False) -> str:
    """Create a short-lived JWT access token."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
        "type": "access",
        "admin": is_admin,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    """
    Decode and validate a JWT access token.
    Returns the payload dict or None if invalid/expired.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat", "type"]},
        )
        if payload.get("type") != "access":
            return None
        return payload
    except jwt.PyJWTError:
        return None


def generate_refresh_token() -> str:
    """Generate a cryptographically secure random refresh token (256-bit)."""
    return secrets.token_hex(32)


def hash_token(token: str) -> str:
    """Hash a refresh token with SHA-256 for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def hash_ip(ip: str) -> str:
    """One-way hash of IP address for audit logging (privacy)."""
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def hash_ua(ua: str) -> str:
    """One-way hash of User-Agent for audit logging (privacy)."""
    return hashlib.sha256(ua.encode()).hexdigest()[:16]

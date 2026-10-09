"""
Me router — account management, data export, account deletion.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit_event
from app.core.security import hash_password, validate_password_strength, verify_password
from app.db.models.models import RefreshToken, User
from app.db.session import get_db
from app.deps import get_client_ip, get_current_user

router = APIRouter(prefix="/me", tags=["me"])


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChangeRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Change the current user's password. Revokes all refresh tokens."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect.")

    pwd_error = validate_password_strength(body.new_password)
    if pwd_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=pwd_error)

    user.password_hash = hash_password(body.new_password)

    # Revoke all refresh tokens (force re-login on all devices)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at == None)
        .values(revoked_at=datetime.now(UTC))
    )

    await log_audit_event(db, "password_change", user.id, get_client_ip(request))
    await db.commit()


@router.get("/export")
async def export_data(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Export all user data as JSON (GDPR-style data portability)."""
    await log_audit_event(db, "data_export", user.id, get_client_ip(request))
    await db.commit()

    # TODO: Implement full data export (profile, wardrobe, outfits, events, media URLs)
    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "message": "Full export will include profile, wardrobe, outfits, events, and media.",
    }


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Soft-delete the account. A background purge job will:
    - Remove all media objects from storage
    - Remove all DB rows, vectors, events
    - Revoke all tokens
    """
    user.deleted_at = datetime.now(UTC)
    user.is_active = False

    # Revoke all refresh tokens immediately
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at == None)
        .values(revoked_at=datetime.now(UTC))
    )

    await log_audit_event(db, "account_delete", user.id, get_client_ip(request))
    await db.commit()
    # TODO: Enqueue purge job to delete all media from storage

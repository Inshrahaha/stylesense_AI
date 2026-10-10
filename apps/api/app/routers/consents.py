"""
Consent router — manage user consent for body media, third-party AI, analytics.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit_event
from app.db.models.models import Consent, ConsentKind, User
from app.db.session import get_db
from app.deps import get_current_user

router = APIRouter(prefix="/consents", tags=["consents"])


class ConsentUpdate(BaseModel):
    kind: ConsentKind
    granted: bool


class ConsentResponse(BaseModel):
    kind: ConsentKind
    granted: bool
    version: str
    granted_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=list[ConsentResponse])
async def get_consents(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get all consent settings for the current user."""
    result = await db.execute(
        select(Consent).where(Consent.user_id == user.id)
    )
    return result.scalars().all()


@router.put("", response_model=ConsentResponse)
async def update_consent(
    body: ConsentUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update a consent setting. Creates if not exists."""
    result = await db.execute(
        select(Consent).where(
            Consent.user_id == user.id,
            Consent.kind == body.kind,
        )
    )
    consent = result.scalar_one_or_none()

    if consent:
        consent.granted = body.granted
    else:
        consent = Consent(
            user_id=user.id,
            kind=body.kind,
            granted=body.granted,
        )
        db.add(consent)

    await log_audit_event(
        db, "consent_change", user.id, meta={"kind": body.kind.value, "granted": body.granted}
    )
    await db.flush()
    return consent

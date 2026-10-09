"""
Profile router — user style profile and preferences.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.models import Profile, User
from app.db.session import get_db
from app.deps import get_current_user

router = APIRouter(prefix="/profile", tags=["profile"])


class ProfileUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    age_range: str | None = Field(None, max_length=20)
    height_cm: float | None = Field(None, gt=0, le=300)
    preferred_categories: list[str] | None = None
    fav_colors: list[str] | None = None
    styles: list[str] | None = None
    budget_min: float | None = Field(None, ge=0)
    budget_max: float | None = Field(None, ge=0)
    occasions: list[str] | None = None
    region: str | None = Field(None, max_length=50)
    currency: str | None = Field(None, max_length=3)


class ProfileResponse(BaseModel):
    user_id: uuid.UUID
    name: str | None = None
    age_range: str | None = None
    height_cm: float | None = None
    preferred_categories: list[str] | None = None
    fav_colors: list[str] | None = None
    styles: list[str] | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    occasions: list[str] | None = None
    region: str | None = None
    currency: str = "INR"

    model_config = {"from_attributes": True}


@router.get("", response_model=ProfileResponse)
async def get_profile(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get the current user's style profile."""
    result = await db.execute(
        select(Profile).where(Profile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        # Create a default profile
        profile = Profile(user_id=user.id)
        db.add(profile)
        await db.flush()
    return profile


@router.patch("", response_model=ProfileResponse)
async def update_profile(
    body: ProfileUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update the current user's style profile."""
    result = await db.execute(
        select(Profile).where(Profile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = Profile(user_id=user.id)
        db.add(profile)
        await db.flush()

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(profile, field, value)

    await db.flush()
    return profile

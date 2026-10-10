"""
Body Analysis Router — Proportions calculation, styling guidance, and privacy controls.

Implements PLAN.md Phase 4:
- Manual path (P0) & Photo/Video visual path (P1)
- Proportional ratio calculation and soft-rule shape classification
- Field-level envelope encryption for raw measurements
- Privacy-by-design: automatically deletes raw body media post-analysis unless user opted in
- Strictly neutral, body-positive styling output
- Strict user-scoping (IDOR immunity)
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_bytes
from app.core.logging import get_logger
from app.db.models import (
    BodyProfile,
    BodySource,
    Consent,
    ConsentKind,
    MediaAsset,
    User,
)
from app.db.session import get_db
from app.deps import get_current_user
from app.services.body.measure import (
    VisualMeasurementError,
    encrypt_measurements,
    estimate_proportions_from_image,
)
from app.services.body.shape import classify_body_shape
from app.services.storage.base import get_storage

logger = get_logger("routers.body")
router = APIRouter(prefix="/body", tags=["body"])


# ── Schemas ──

class ManualMeasurementRequest(BaseModel):
    shoulder: float = Field(..., gt=10, lt=250, description="Shoulder width/circumference in cm")
    waist: float = Field(..., gt=10, lt=250, description="Waist circumference in cm")
    hip: float = Field(..., gt=10, lt=250, description="Hip circumference in cm")
    bust: float | None = Field(None, gt=10, lt=250, description="Optional bust/chest circumference in cm")
    height: float | None = Field(None, gt=50, lt=260, description="Optional total height in cm")
    inseam: float | None = Field(None, gt=20, lt=150, description="Optional inseam / leg length in cm")


class AnalyzeVisualRequest(BaseModel):
    asset_id: uuid.UUID


class ShapeCorrectionRequest(BaseModel):
    shape: str = Field(..., description="User-selected corrected body shape")


class BodyGuidanceResponse(BaseModel):
    shape: str
    confidence: float
    runner_up: str | None = None
    ratios: dict[str, float]
    recommended_silhouettes: list[str]
    suggested_fits: list[str]
    styles_to_try: list[str]
    notes: str
    source: str
    user_corrected_shape: str | None = None


# ── Endpoints ──

@router.post("/manual", response_model=BodyGuidanceResponse)
async def submit_manual_measurements(
    body: ManualMeasurementRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit manual bodily measurements.
    Computes proportions, classifies shape, and encrypts measurements at rest.
    """
    guidance = classify_body_shape(
        shoulder=body.shoulder,
        waist=body.waist,
        hip=body.hip,
        bust=body.bust,
        height=body.height,
        inseam=body.inseam,
    )

    measurements_dict = body.model_dump()
    measurements_enc = encrypt_measurements(measurements_dict)

    # Check if profile already exists
    stmt = select(BodyProfile).where(BodyProfile.user_id == current_user.id)
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        profile = BodyProfile(
            user_id=current_user.id,
            measurements_enc=measurements_enc,
            shape=guidance["shape"],
            shape_confidence=guidance["confidence"],
            ratios=guidance["ratios"],
            source=BodySource.MANUAL,
            model_version="rules_v1",
        )
        db.add(profile)
    else:
        profile.measurements_enc = measurements_enc
        profile.shape = guidance["shape"]
        profile.shape_confidence = guidance["confidence"]
        profile.ratios = guidance["ratios"]
        profile.source = BodySource.MANUAL

    await db.commit()
    await db.refresh(profile)

    return BodyGuidanceResponse(
        shape=profile.shape,
        confidence=profile.shape_confidence or 0.85,
        runner_up=guidance.get("runner_up"),
        ratios=profile.ratios or {},
        recommended_silhouettes=guidance["recommended_silhouettes"],
        suggested_fits=guidance["suggested_fits"],
        styles_to_try=guidance["styles_to_try"],
        notes=guidance["notes"],
        source=profile.source.value if profile.source else "manual",
        user_corrected_shape=profile.user_corrected_shape,
    )


@router.post("/analyze", response_model=BodyGuidanceResponse)
async def analyze_visual_body(
    body: AnalyzeVisualRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Analyze uploaded body photograph or video.
    Extracts silhouette proportions and classifies body shape.
    Privacy-by-design: purges raw media after landmark extraction unless opted in.
    """
    stmt = select(MediaAsset).where(
        MediaAsset.id == body.asset_id,
        MediaAsset.user_id == current_user.id,
        MediaAsset.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media asset not found")

    storage = get_storage()
    try:
        raw_stored_bytes = await storage.get(asset.object_key)
    except Exception as e:
        logger.error(f"Failed to fetch asset from storage: {e}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found in storage")

    image_bytes = decrypt_bytes(raw_stored_bytes) if asset.encrypted else raw_stored_bytes

    try:
        proportions = estimate_proportions_from_image(image_bytes)
    except VisualMeasurementError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    guidance = classify_body_shape(
        shoulder=proportions["shoulder"],
        waist=proportions["waist"],
        hip=proportions["hip"],
    )

    measurements_enc = encrypt_measurements(proportions)

    # Privacy by design default: delete raw body media unless consented
    consent_stmt = select(Consent).where(
        Consent.user_id == current_user.id,
        Consent.kind == ConsentKind.BODY_MEDIA,
        Consent.granted == True,
    )
    has_retention_consent = (await db.execute(consent_stmt)).scalar_one_or_none() is not None

    if not has_retention_consent:
        try:
            await storage.delete(asset.object_key)
            asset.deleted_at = datetime.now(UTC)
            logger.info(f"Privacy purge: raw body media {asset.id} deleted after feature extraction")
        except Exception as e:
            logger.warning(f"Failed to purge raw body asset: {e}")

    # Upsert profile
    profile_stmt = select(BodyProfile).where(BodyProfile.user_id == current_user.id)
    profile_res = await db.execute(profile_stmt)
    profile = profile_res.scalar_one_or_none()

    if not profile:
        profile = BodyProfile(
            user_id=current_user.id,
            measurements_enc=measurements_enc,
            shape=guidance["shape"],
            shape_confidence=guidance["confidence"],
            ratios=guidance["ratios"],
            source=BodySource.PHOTO,
            model_version="rules_v1",
        )
        db.add(profile)
    else:
        profile.measurements_enc = measurements_enc
        profile.shape = guidance["shape"]
        profile.shape_confidence = guidance["confidence"]
        profile.ratios = guidance["ratios"]
        profile.source = BodySource.PHOTO

    await db.commit()
    await db.refresh(profile)

    return BodyGuidanceResponse(
        shape=profile.shape,
        confidence=profile.shape_confidence or 0.80,
        runner_up=guidance.get("runner_up"),
        ratios=profile.ratios or {},
        recommended_silhouettes=guidance["recommended_silhouettes"],
        suggested_fits=guidance["suggested_fits"],
        styles_to_try=guidance["styles_to_try"],
        notes=guidance["notes"],
        source=profile.source.value if profile.source else "photo",
        user_corrected_shape=profile.user_corrected_shape,
    )


@router.get("", response_model=BodyGuidanceResponse)
async def get_body_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve current user's body shape and styling guidance."""
    stmt = select(BodyProfile).where(BodyProfile.user_id == current_user.id)
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile or not profile.shape:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Body profile not yet created")

    # Fetch shape recommendations
    from app.services.body.shape import BODY_RULES
    shape_info = BODY_RULES.get("shapes", {}).get(profile.shape, {})

    return BodyGuidanceResponse(
        shape=profile.shape,
        confidence=profile.shape_confidence or 0.85,
        ratios=profile.ratios or {},
        recommended_silhouettes=shape_info.get("recommended_silhouettes", []),
        suggested_fits=shape_info.get("suggested_fits", []),
        styles_to_try=shape_info.get("styles_to_try", []),
        notes=shape_info.get("notes", "Dress in silhouettes that bring comfort and confidence."),
        source=profile.source.value if profile.source else "manual",
        user_corrected_shape=profile.user_corrected_shape,
    )


@router.patch("/correction", response_model=BodyGuidanceResponse)
async def correct_body_shape(
    body: ShapeCorrectionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Allow user to correct or override predicted body shape.
    Stores user_corrected_shape for model calibration.
    """
    from app.services.body.shape import BODY_RULES
    valid_shapes = list(BODY_RULES.get("shapes", {}).keys())
    if body.shape not in valid_shapes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid body shape. Must be one of: {', '.join(valid_shapes)}",
        )

    stmt = select(BodyProfile).where(BodyProfile.user_id == current_user.id)
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Body profile not yet created")

    profile.user_corrected_shape = body.shape
    profile.shape = body.shape  # Active user preference overrides
    await db.commit()
    await db.refresh(profile)

    shape_info = BODY_RULES.get("shapes", {}).get(profile.shape, {})

    return BodyGuidanceResponse(
        shape=profile.shape,
        confidence=1.0,
        ratios=profile.ratios or {},
        recommended_silhouettes=shape_info.get("recommended_silhouettes", []),
        suggested_fits=shape_info.get("suggested_fits", []),
        styles_to_try=shape_info.get("styles_to_try", []),
        notes=shape_info.get("notes", "Personalized according to your shape selection."),
        source=profile.source.value if profile.source else "manual",
        user_corrected_shape=profile.user_corrected_shape,
    )

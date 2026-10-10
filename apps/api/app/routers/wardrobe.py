"""
Wardrobe AI router — clothes digitization, attribute editing, and inventory management.

Implements PLAN.md Phase 3:
- Digitization cascade (cutout -> embedding -> attribute classification)
- Learning hook: user corrections recorded in item_label_corrections for active learning
- Inventory tracking (wear count, availability, categorization)
- Strict user-scoping (IDOR immunity)
"""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import (
    AttrsSource,
    Consent,
    ConsentKind,
    ItemLabelCorrection,
    MediaAsset,
    MediaKind,
    MediaStatus,
    User,
    WardrobeItem,
)
from app.db.session import get_db
from app.deps import get_current_user
from app.services.storage.base import get_storage
from app.services.vision.attributes import get_attribute_classifier
from app.services.vision.cutout import generate_garment_cutout
from app.services.vision.embeddings import get_embedding_service

logger = get_logger("routers.wardrobe")
router = APIRouter(prefix="/wardrobe", tags=["wardrobe"])


# ── Schemas ──

class CreateWardrobeItemRequest(BaseModel):
    asset_id: uuid.UUID
    name: str | None = None


class UpdateWardrobeItemRequest(BaseModel):
    name: str | None = None
    category: str | None = None
    subcategory: str | None = None
    colors: list[dict[str, Any]] | None = None
    pattern: str | None = None
    material: str | None = None
    sleeve: str | None = None
    neckline: str | None = None
    fit: str | None = None
    length: str | None = None
    style_tags: list[str] | None = None
    occasions: list[str] | None = None
    seasons: list[str] | None = None
    formality: int | None = None
    is_available: bool | None = None


class WardrobeItemResponse(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID | None = None
    cutout_asset_id: uuid.UUID | None = None
    name: str | None = None
    category: str | None = None
    subcategory: str | None = None
    colors: list[dict[str, Any]] | None = None
    pattern: str | None = None
    material: str | None = None
    sleeve: str | None = None
    neckline: str | None = None
    fit: str | None = None
    length: str | None = None
    style_tags: list[str] | None = None
    occasions: list[str] | None = None
    seasons: list[str] | None = None
    formality: int | None = None
    attrs_confidence: dict[str, Any] | None = None
    attrs_source: str | None = None
    is_available: bool = True
    wear_count: int = 0
    last_worn_at: datetime | None = None
    created_at: datetime


class WardrobeSummaryResponse(BaseModel):
    total_items: int
    available_items: int
    by_category: dict[str, int]


# ── Endpoints ──

@router.post("/items", response_model=WardrobeItemResponse, status_code=status.HTTP_201_CREATED)
async def create_wardrobe_item(
    body: CreateWardrobeItemRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Digitize clothing item from uploaded media asset.
    Runs cutout, embedding, and attribute cascade.
    """
    # Verify media asset ownership
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
        raw_bytes = await storage.get(asset.object_key)
    except Exception as e:
        logger.error(f"Failed to fetch asset from storage: {e}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found in storage")

    # Check third_party_ai consent for Claude vision escalation
    consent_stmt = select(Consent).where(
        Consent.user_id == current_user.id,
        Consent.kind == ConsentKind.THIRD_PARTY_AI,
        Consent.granted == True,
    )
    has_ai_consent = (await db.execute(consent_stmt)).scalar_one_or_none() is not None

    # Step 1: Generate transparent cutout
    cutout_bytes = generate_garment_cutout(raw_bytes)
    cutout_key = storage.generate_key(current_user.id, "derived_cutout")
    await storage.put(cutout_key, cutout_bytes, content_type="image/png")

    cutout_asset = MediaAsset(
        id=uuid.uuid4(),
        user_id=current_user.id,
        kind=MediaKind.DERIVED,
        object_key=cutout_key,
        sha256=hashlib.sha256(cutout_bytes).hexdigest(),
        mime="image/png",
        size_bytes=len(cutout_bytes),
        encrypted=False,
        status=MediaStatus.READY,
    )
    db.add(cutout_asset)

    # Step 2: Compute embedding vector
    embedder = get_embedding_service()
    _ = embedder.embed_image(cutout_bytes)

    # Step 3: Run attribute classification cascade
    classifier = get_attribute_classifier()
    attrs = await classifier.classify_item(
        image_bytes=raw_bytes,
        cutout_bytes=cutout_bytes,
        has_ai_consent=has_ai_consent,
    )

    item = WardrobeItem(
        id=uuid.uuid4(),
        user_id=current_user.id,
        asset_id=asset.id,
        cutout_asset_id=cutout_asset.id,
        name=body.name or attrs["name"],
        category=attrs["category"],
        subcategory=attrs["subcategory"],
        colors=attrs["colors"],
        pattern=attrs["pattern"],
        material=attrs["material"],
        sleeve=attrs["sleeve"],
        neckline=attrs["neckline"],
        fit=attrs["fit"],
        length=attrs["length"],
        style_tags=attrs["style_tags"],
        occasions=attrs["occasions"],
        seasons=attrs["seasons"],
        formality=attrs["formality"],
        attrs_confidence=attrs["attrs_confidence"],
        attrs_source=attrs["attrs_source"],
        is_available=True,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    return WardrobeItemResponse(
        id=item.id,
        asset_id=item.asset_id,
        cutout_asset_id=item.cutout_asset_id,
        name=item.name,
        category=item.category,
        subcategory=item.subcategory,
        colors=item.colors,
        pattern=item.pattern,
        material=item.material,
        sleeve=item.sleeve,
        neckline=item.neckline,
        fit=item.fit,
        length=item.length,
        style_tags=item.style_tags,
        occasions=item.occasions,
        seasons=item.seasons,
        formality=item.formality,
        attrs_confidence=item.attrs_confidence,
        attrs_source=item.attrs_source.value if item.attrs_source else None,
        is_available=item.is_available,
        wear_count=item.wear_count,
        last_worn_at=item.last_worn_at,
        created_at=item.created_at,
    )


@router.get("/items", response_model=list[WardrobeItemResponse])
async def list_wardrobe_items(
    category: str | None = Query(None),
    occasion: str | None = Query(None),
    available_only: bool = Query(False),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List wardrobe items for current user with filtering and pagination."""
    stmt = select(WardrobeItem).where(WardrobeItem.user_id == current_user.id)

    if category:
        stmt = stmt.where(WardrobeItem.category == category)
    if available_only:
        stmt = stmt.where(WardrobeItem.is_available == True)
    if q:
        stmt = stmt.where(
            or_(
                WardrobeItem.name.ilike(f"%{q}%"),
                WardrobeItem.subcategory.ilike(f"%{q}%"),
                WardrobeItem.pattern.ilike(f"%{q}%"),
            )
        )

    stmt = stmt.order_by(WardrobeItem.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    items = result.scalars().all()

    return [
        WardrobeItemResponse(
            id=i.id,
            asset_id=i.asset_id,
            cutout_asset_id=i.cutout_asset_id,
            name=i.name,
            category=i.category,
            subcategory=i.subcategory,
            colors=i.colors,
            pattern=i.pattern,
            material=i.material,
            sleeve=i.sleeve,
            neckline=i.neckline,
            fit=i.fit,
            length=i.length,
            style_tags=i.style_tags,
            occasions=i.occasions,
            seasons=i.seasons,
            formality=i.formality,
            attrs_confidence=i.attrs_confidence,
            attrs_source=i.attrs_source.value if i.attrs_source else None,
            is_available=i.is_available,
            wear_count=i.wear_count,
            last_worn_at=i.last_worn_at,
            created_at=i.created_at,
        )
        for i in items
    ]


@router.get("/items/{item_id}", response_model=WardrobeItemResponse)
async def get_wardrobe_item(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve specific wardrobe item by ID."""
    stmt = select(WardrobeItem).where(
        WardrobeItem.id == item_id,
        WardrobeItem.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wardrobe item not found")

    return WardrobeItemResponse(
        id=item.id,
        asset_id=item.asset_id,
        cutout_asset_id=item.cutout_asset_id,
        name=item.name,
        category=item.category,
        subcategory=item.subcategory,
        colors=item.colors,
        pattern=item.pattern,
        material=item.material,
        sleeve=item.sleeve,
        neckline=item.neckline,
        fit=item.fit,
        length=item.length,
        style_tags=item.style_tags,
        occasions=item.occasions,
        seasons=item.seasons,
        formality=item.formality,
        attrs_confidence=item.attrs_confidence,
        attrs_source=item.attrs_source.value if item.attrs_source else None,
        is_available=item.is_available,
        wear_count=item.wear_count,
        last_worn_at=item.last_worn_at,
        created_at=item.created_at,
    )


@router.patch("/items/{item_id}", response_model=WardrobeItemResponse)
async def update_wardrobe_item(
    item_id: uuid.UUID,
    body: UpdateWardrobeItemRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update wardrobe item fields.
    Learning hook: writes corrections to item_label_corrections if ML predictions are modified.
    """
    stmt = select(WardrobeItem).where(
        WardrobeItem.id == item_id,
        WardrobeItem.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wardrobe item not found")

    # Learning hook: track corrections
    track_fields = ["category", "subcategory", "pattern", "sleeve", "neckline", "fit", "length", "material"]
    for field in track_fields:
        val = getattr(body, field, None)
        if val is not None:
            old_val = getattr(item, field)
            if old_val != val and item.attrs_source in (AttrsSource.ML, AttrsSource.LLM):
                correction = ItemLabelCorrection(
                    id=uuid.uuid4(),
                    item_id=item.id,
                    field=field,
                    predicted=str(old_val),
                    corrected=str(val),
                )
                db.add(correction)
                logger.info(f"Logged label correction for item {item.id}: {field} -> {val}")
            setattr(item, field, val)

    if body.name is not None:
        item.name = body.name
    if body.colors is not None:
        item.colors = body.colors
    if body.style_tags is not None:
        item.style_tags = body.style_tags
    if body.occasions is not None:
        item.occasions = body.occasions
    if body.seasons is not None:
        item.seasons = body.seasons
    if body.formality is not None:
        item.formality = body.formality
    if body.is_available is not None:
        item.is_available = body.is_available

    # User touched attributes
    item.attrs_source = AttrsSource.USER

    await db.commit()
    await db.refresh(item)

    return WardrobeItemResponse(
        id=item.id,
        asset_id=item.asset_id,
        cutout_asset_id=item.cutout_asset_id,
        name=item.name,
        category=item.category,
        subcategory=item.subcategory,
        colors=item.colors,
        pattern=item.pattern,
        material=item.material,
        sleeve=item.sleeve,
        neckline=item.neckline,
        fit=item.fit,
        length=item.length,
        style_tags=item.style_tags,
        occasions=item.occasions,
        seasons=item.seasons,
        formality=item.formality,
        attrs_confidence=item.attrs_confidence,
        attrs_source=item.attrs_source.value if item.attrs_source else None,
        is_available=item.is_available,
        wear_count=item.wear_count,
        last_worn_at=item.last_worn_at,
        created_at=item.created_at,
    )


@router.post("/items/{item_id}/worn", response_model=WardrobeItemResponse)
async def mark_item_worn(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Increment wear counter and update last_worn_at timestamp."""
    stmt = select(WardrobeItem).where(
        WardrobeItem.id == item_id,
        WardrobeItem.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wardrobe item not found")

    item.wear_count += 1
    item.last_worn_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(item)

    return WardrobeItemResponse(
        id=item.id,
        asset_id=item.asset_id,
        cutout_asset_id=item.cutout_asset_id,
        name=item.name,
        category=item.category,
        subcategory=item.subcategory,
        colors=item.colors,
        pattern=item.pattern,
        material=item.material,
        sleeve=item.sleeve,
        neckline=item.neckline,
        fit=item.fit,
        length=item.length,
        style_tags=item.style_tags,
        occasions=item.occasions,
        seasons=item.seasons,
        formality=item.formality,
        attrs_confidence=item.attrs_confidence,
        attrs_source=item.attrs_source.value if item.attrs_source else None,
        is_available=item.is_available,
        wear_count=item.wear_count,
        last_worn_at=item.last_worn_at,
        created_at=item.created_at,
    )


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wardrobe_item(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete wardrobe item."""
    stmt = select(WardrobeItem).where(
        WardrobeItem.id == item_id,
        WardrobeItem.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wardrobe item not found")

    await db.delete(item)
    await db.commit()
    return None


@router.get("/summary", response_model=WardrobeSummaryResponse)
async def get_wardrobe_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get wardrobe item counts per category and total available items."""
    stmt = select(WardrobeItem).where(WardrobeItem.user_id == current_user.id)
    result = await db.execute(stmt)
    items = result.scalars().all()

    total = len(items)
    available = sum(1 for i in items if i.is_available)

    by_category: dict[str, int] = {}
    for i in items:
        cat = i.category or "other"
        by_category[cat] = by_category.get(cat, 0) + 1

    return WardrobeSummaryResponse(
        total_items=total,
        available_items=available,
        by_category=by_category,
    )

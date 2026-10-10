"""
Media Router — Upload, retrieve, stream, and delete media assets.

Enforces:
- File validation (magic bytes, bomb guard, size caps)
- EXIF stripping and orientation normalization
- Default face blurring for body media
- Envelope encryption (AES-256-GCM) for body media
- Presigned URLs for wardrobe media (max 5 min TTL)
- Strict user-scoping (IDOR immunity)
"""

import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_bytes, encrypt_bytes
from app.core.logging import get_logger
from app.db.models import MediaAsset, MediaKind, MediaStatus, User
from app.db.session import get_db
from app.deps import get_current_user
from app.services.media.sanitize import blur_face_regions, sanitize_and_reencode_image
from app.services.media.validate import (
    MediaValidationError,
    validate_image_bytes,
    validate_video_bytes,
)
from app.services.storage.base import get_storage

logger = get_logger("routers.media")
router = APIRouter(prefix="/media", tags=["media"])


class MediaResponse(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    mime: str | None = None
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None
    size_bytes: int | None = None
    encrypted: bool
    url: str | None = None
    thumbnail_url: str | None = None
    created_at: datetime


@router.post("", response_model=MediaResponse, status_code=status.HTTP_201_CREATED)
async def upload_media(
    file: UploadFile = File(...),
    kind: MediaKind = Form(...),
    blur_face: bool = Form(True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Streamed upload endpoint.
    Validates magic bytes, sanitizes metadata, encrypts body media, and stores to object storage.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file uploaded")

    sha256_hash = hashlib.sha256(data).hexdigest()
    is_video = kind in (MediaKind.BODY_VIDEO, MediaKind.WARDROBE_VIDEO)
    storage = get_storage()

    # Validate
    try:
        if is_video:
            mime = validate_video_bytes(data, kind.value)
            width, height = None, None
            sanitized_data = data
        else:
            mime, width, height = validate_image_bytes(data)
            # Re-encode image to strip EXIF and metadata
            sanitized_data, width, height = sanitize_and_reencode_image(data, target_format="JPEG")
            # If body image, apply default face blurring
            if kind == MediaKind.BODY_IMAGE and blur_face:
                sanitized_data = blur_face_regions(sanitized_data)
    except MediaValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Media validation error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to process image")

    # Storage and encryption
    is_body_media = kind in (MediaKind.BODY_IMAGE, MediaKind.BODY_VIDEO)
    stored_bytes = encrypt_bytes(sanitized_data) if is_body_media else sanitized_data

    object_key = storage.generate_key(current_user.id, kind.value)
    await storage.put(object_key, stored_bytes, content_type=mime)

    media_asset = MediaAsset(
        id=uuid.uuid4(),
        user_id=current_user.id,
        kind=kind,
        object_key=object_key,
        sha256=sha256_hash,
        mime=mime,
        size_bytes=len(stored_bytes),
        width=width,
        height=height,
        encrypted=is_body_media,
        status=MediaStatus.READY,
    )
    db.add(media_asset)
    await db.commit()
    await db.refresh(media_asset)

    # Resolve URL
    url = None
    if not is_body_media:
        url = await storage.get_presigned_url(object_key, expires_in=300)
    else:
        url = f"/api/v1/media/{media_asset.id}/stream"

    return MediaResponse(
        id=media_asset.id,
        kind=media_asset.kind.value,
        status=media_asset.status.value,
        mime=media_asset.mime,
        width=media_asset.width,
        height=media_asset.height,
        duration_s=media_asset.duration_s,
        size_bytes=media_asset.size_bytes,
        encrypted=media_asset.encrypted,
        url=url,
        created_at=media_asset.created_at,
    )


@router.get("/{media_id}", response_model=MediaResponse)
async def get_media_details(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get media asset metadata with secure delivery URL."""
    stmt = select(MediaAsset).where(
        MediaAsset.id == media_id,
        MediaAsset.user_id == current_user.id,
        MediaAsset.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media asset not found")

    storage = get_storage()
    url = f"/api/v1/media/{asset.id}/stream" if asset.encrypted else await storage.get_presigned_url(asset.object_key)

    return MediaResponse(
        id=asset.id,
        kind=asset.kind.value,
        status=asset.status.value,
        mime=asset.mime,
        width=asset.width,
        height=asset.height,
        duration_s=asset.duration_s,
        size_bytes=asset.size_bytes,
        encrypted=asset.encrypted,
        url=url,
        created_at=asset.created_at,
    )


@router.get("/{media_id}/stream")
async def stream_media(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticated streaming endpoint for body media.
    Decrypts encrypted assets in memory and sets Cache-Control: no-store.
    """
    stmt = select(MediaAsset).where(
        MediaAsset.id == media_id,
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
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found in storage")

    if asset.encrypted:
        payload = decrypt_bytes(raw_bytes)
    else:
        payload = raw_bytes

    return Response(
        content=payload,
        media_type=asset.mime or "application/octet-stream",
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.delete("/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a media asset from storage and mark deleted in database."""
    stmt = select(MediaAsset).where(
        MediaAsset.id == media_id,
        MediaAsset.user_id == current_user.id,
        MediaAsset.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media asset not found")

    storage = get_storage()
    try:
        await storage.delete(asset.object_key)
    except Exception as e:
        logger.warning(f"Failed to delete object {asset.object_key} from storage: {e}")

    asset.deleted_at = datetime.now(UTC)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

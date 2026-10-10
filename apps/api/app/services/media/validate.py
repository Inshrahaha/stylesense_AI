"""
Media validation service.

Validates files by magic bytes, size, dimensions, and guards against decompression bombs.
Never trusts file extension or user-supplied Content-Type.
"""

import io

from PIL import Image

# Guard against decompression bombs (PLAN.md §2, Phase 2)
# Set MAX_IMAGE_PIXELS to 36_000_000 (e.g., 6000x6000 max)
Image.MAX_IMAGE_PIXELS = 36_000_000

# Limits
MAX_IMAGE_BYTES = 10 * 1024 * 1024       # 10 MB
MAX_BODY_VIDEO_BYTES = 100 * 1024 * 1024   # 100 MB
MAX_WARDROBE_VIDEO_BYTES = 200 * 1024 * 1024  # 200 MB
MAX_DIMENSION = 6000                      # 6000 px per side


class MediaValidationError(ValueError):
    """Raised when uploaded media fails validation."""
    pass


def detect_mime_by_magic_bytes(data: bytes) -> str:
    """
    Detect MIME type using file magic bytes / signatures.
    Rejects disguised files and polyglots.
    """
    if len(data) < 12:
        raise MediaValidationError("File is too small to be valid media")

    # JPEG: starts with FF D8 FF
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"

    # PNG: starts with 89 50 4E 47 0D 0A 1A 0A
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"

    # WebP: RIFF .... WEBP
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"

    # MP4 / QuickTime: check ftyp box at offset 4
    if len(data) >= 8 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"isom", b"iso2", b"mp41", b"mp42", b"M4V ", b"dash", b"avc1"):
            return "video/mp4"
        elif brand in (b"qt  ",):
            return "video/quicktime"
        return "video/mp4"

    # WebM: 1A 45 DF A3
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"

    # Check for polyglots: executable signatures (MZ, ELF, etc.)
    if data[:2] == b"MZ" or data[:4] == b"\x7fELF":
        raise MediaValidationError("Executable files are strictly forbidden")

    # Check for script polyglots (HTML/XML/SVG/PHP)
    header_sample = data[:256].lower()
    if b"<script" in header_sample or b"<?php" in header_sample or b"<html" in header_sample:
        raise MediaValidationError("Polyglot or script content detected")

    raise MediaValidationError("Unsupported file format or invalid magic bytes")


def validate_image_bytes(data: bytes) -> tuple[str, int, int]:
    """
    Validate an image buffer:
    - Checks magic bytes
    - Verifies image integrity using Pillow
    - Verifies dimensions <= 6000px
    - Guards against decompression bombs

    Returns: (mime_type, width, height)
    """
    if len(data) > MAX_IMAGE_BYTES:
        raise MediaValidationError(f"Image exceeds maximum size of {MAX_IMAGE_BYTES // (1024*1024)} MB")

    mime = detect_mime_by_magic_bytes(data)
    if not mime.startswith("image/"):
        raise MediaValidationError(f"Expected image, but got {mime}")

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
    except Image.DecompressionBombError:
        raise MediaValidationError("Decompression bomb detected")
    except Exception as e:
        raise MediaValidationError(f"Corrupted or invalid image data: {e}")

    # Re-open to read width and height since verify closes/invalidates the image
    with Image.open(io.BytesIO(data)) as img:
        width, height = img.size
        if width > MAX_DIMENSION or height > MAX_DIMENSION:
            raise MediaValidationError(f"Image dimensions ({width}x{height}) exceed maximum allowed {MAX_DIMENSION}px")

    return mime, width, height


def validate_video_bytes(data: bytes, kind: str) -> str:
    """
    Validate video buffer:
    - Checks magic bytes
    - Checks size limits per video kind
    """
    max_size = MAX_BODY_VIDEO_BYTES if kind == "body_video" else MAX_WARDROBE_VIDEO_BYTES
    if len(data) > max_size:
        limit_mb = max_size // (1024 * 1024)
        raise MediaValidationError(f"Video exceeds maximum size of {limit_mb} MB")

    mime = detect_mime_by_magic_bytes(data)
    if not mime.startswith("video/"):
        raise MediaValidationError(f"Expected video, but got {mime}")

    return mime

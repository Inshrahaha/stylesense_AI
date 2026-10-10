"""
Media sanitization service.

Strips EXIF/GPS metadata, fixes EXIF orientation, generates thumbnails,
and provides default face blurring for body media to preserve user privacy.
"""

import io

from PIL import Image, ImageFilter, ImageOps

from app.core.logging import get_logger

logger = get_logger("media.sanitize")


def sanitize_and_reencode_image(
    data: bytes,
    target_format: str = "JPEG",
    quality: int = 85,
) -> tuple[bytes, int, int]:
    """
    Re-encodes an image to strip all metadata, GPS tags, and EXIF profiles.
    Corrects orientation first according to EXIF tags.

    Returns: (clean_bytes, width, height)
    """
    with Image.open(io.BytesIO(data)) as img:
        # Transpose based on EXIF orientation if present
        img = ImageOps.exif_transpose(img) or img

        # Convert to RGB if needed (handles RGBA for JPEG or Palette modes)
        if target_format.upper() in ("JPEG", "JPG"):
            if img.mode in ("RGBA", "LA", "P"):
                # Create white background for transparent images converted to JPEG
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                clean_img = background
            elif img.mode != "RGB":
                clean_img = img.convert("RGB")
            else:
                clean_img = img.copy()
        else:
            clean_img = img.copy()

        width, height = clean_img.size

        # Save to buffer without EXIF metadata
        buf = io.BytesIO()
        clean_img.save(buf, format=target_format, quality=quality, optimize=True)
        return buf.getvalue(), width, height


def generate_thumbnail(
    data: bytes,
    size: tuple[int, int] = (300, 300),
    target_format: str = "JPEG",
) -> bytes:
    """
    Generate a scaled thumbnail preserving aspect ratio without metadata.
    """
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img) or img
        if target_format.upper() in ("JPEG", "JPG") and img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            thumb_img = background
        elif img.mode != "RGB":
            thumb_img = img.convert("RGB")
        else:
            thumb_img = img.copy()

        thumb_img.thumbnail(size, Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        thumb_img.save(buf, format=target_format, quality=80, optimize=True)
        return buf.getvalue()


def blur_face_regions(data: bytes, face_boxes: list[tuple[int, int, int, int]] | None = None) -> bytes:
    """
    Blurs face regions in an image for body privacy.
    If face_boxes are provided: list of (x, y, w, h).
    If face_boxes are None: attempts automatic face detection or blurs top-center region (upper 20% of full-body photo).
    """
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img) or img
        if img.mode != "RGB":
            img = img.convert("RGB")

        w, h = img.size

        if not face_boxes:
            # Automatic heuristic for full-body portraits: top 22% of height, center 40% of width
            top = int(h * 0.02)
            face_h = int(h * 0.20)
            face_w = int(w * 0.35)
            left = int((w - face_w) / 2)
            face_boxes = [(left, top, face_w, face_h)]

        blurred_img = img.copy()
        for x, y, fw, fh in face_boxes:
            # Clamp bounds
            x0 = max(0, x)
            y0 = max(0, y)
            x1 = min(w, x + fw)
            y1 = min(h, y + fh)

            if x1 > x0 and y1 > y0:
                box = (x0, y0, x1, y1)
                region = img.crop(box)
                # Heavy Gaussian blur to anonymize face
                blurred_region = region.filter(ImageFilter.GaussianBlur(radius=25))
                blurred_img.paste(blurred_region, box)

        buf = io.BytesIO()
        blurred_img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

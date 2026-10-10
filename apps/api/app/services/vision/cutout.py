"""
Garment background cutout service.

Uses rembg (U2-Net) if available; provides seamless fallback for offline/mock environments.
Returns PNG image bytes with transparent background.
"""

import io
from typing import cast

from PIL import Image

from app.core.logging import get_logger

logger = get_logger("vision.cutout")


def generate_garment_cutout(image_bytes: bytes) -> bytes:
    """
    Remove background from garment photo.
    Returns PNG bytes with alpha transparency.
    """
    try:
        import rembg
        output_bytes = cast(bytes, rembg.remove(image_bytes))
        logger.debug("Successfully generated cutout via rembg")
        return output_bytes
    except Exception as e:
        logger.debug(f"rembg not active ({e}); applying fallback alpha transparency mask")

    # Fallback: Convert to RGBA and apply corner-based background transparency mask
    with Image.open(io.BytesIO(image_bytes)) as opened:
        img: Image.Image = opened
        img = img.convert("RGBA")
        datas = list(img.getdata())

        # Sample top-left corner color as background reference
        bg_r, bg_g, bg_b, _ = datas[0]

        new_data = []
        tolerance = 35

        for item in datas:
            r, g, b, a = item
            # If pixel is close to corner background color, make it transparent
            if abs(r - bg_r) < tolerance and abs(g - bg_g) < tolerance and abs(b - bg_b) < tolerance:
                new_data.append((r, g, b, 0))
            else:
                new_data.append(item)

        img.putdata(new_data)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

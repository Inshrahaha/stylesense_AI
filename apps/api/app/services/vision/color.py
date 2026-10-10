"""
Color extraction service.

Quantizes colors, maps RGB to CIE Lab space, and matches against canonical color taxonomy.
Returns dominant colors with names, hex codes, and percentage shares.
"""

import io
import math
from typing import Any, cast

from PIL import Image

# Canonical color palette with sRGB and approx Lab values
COLOR_PALETTE: list[dict[str, Any]] = [
    {"name": "Black", "hex": "#000000", "rgb": (0, 0, 0), "lab": (0, 0, 0)},
    {"name": "White", "hex": "#FFFFFF", "rgb": (255, 255, 255), "lab": (100, 0, 0)},
    {"name": "Grey", "hex": "#808080", "rgb": (128, 128, 128), "lab": (53, 0, 0)},
    {"name": "Navy", "hex": "#000080", "rgb": (0, 0, 128), "lab": (13, 19, -44)},
    {"name": "Blue", "hex": "#1E90FF", "rgb": (30, 144, 255), "lab": (58, -3, -59)},
    {"name": "Light Blue", "hex": "#ADD8E6", "rgb": (173, 216, 230), "lab": (84, -14, -16)},
    {"name": "Beige", "hex": "#F5F5DC", "rgb": (245, 245, 220), "lab": (96, -2, 10)},
    {"name": "Brown", "hex": "#8B4513", "rgb": (139, 69, 19), "lab": (38, 28, 38)},
    {"name": "Olive", "hex": "#808000", "rgb": (128, 128, 0), "lab": (53, -13, 54)},
    {"name": "Green", "hex": "#2E8B57", "rgb": (46, 139, 87), "lab": (52, -40, 21)},
    {"name": "Red", "hex": "#DC143C", "rgb": (220, 20, 60), "lab": (46, 73, 38)},
    {"name": "Maroon", "hex": "#800000", "rgb": (128, 0, 0), "lab": (26, 48, 38)},
    {"name": "Pink", "hex": "#FFC0CB", "rgb": (255, 192, 203), "lab": (83, 27, 4)},
    {"name": "Yellow", "hex": "#FFD700", "rgb": (255, 215, 0), "lab": (87, 6, 85)},
    {"name": "Orange", "hex": "#FF8C00", "rgb": (255, 140, 0), "lab": (66, 38, 71)},
    {"name": "Purple", "hex": "#800080", "rgb": (128, 0, 128), "lab": (30, 58, -36)},
]


def rgb_to_lab(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Convert sRGB (0-255) to CIE-L*a*b* coordinates."""
    # Normalize sRGB
    r_n, g_n, b_n = r / 255.0, g / 255.0, b / 255.0

    # Linearize sRGB (gamma correction)
    def linearize(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r_l, g_l, b_l = linearize(r_n), linearize(g_n), linearize(b_n)

    # Convert to XYZ (D65 standard illuminant)
    x = (r_l * 0.4124564 + g_l * 0.3575761 + b_l * 0.1804375) / 0.95047
    y = (r_l * 0.2126729 + g_l * 0.7151522 + b_l * 0.0721750) / 1.00000
    z = (r_l * 0.0193339 + g_l * 0.1191920 + b_l * 0.9503041) / 1.08883

    # Nonlinear transformation to Lab
    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + (16 / 116)

    fx, fy, fz = f(x), f(y), f(z)
    L = max(0.0, min(100.0, (116.0 * fy) - 16.0))
    a = 500.0 * (fx - fy)
    b_val = 200.0 * (fy - fz)
    return L, a, b_val


# Initialize exact Lab coordinates for color palette
for _entry in COLOR_PALETTE:
    _entry["lab"] = rgb_to_lab(*_entry["rgb"])


def match_closest_color(r: int, g: int, b: int) -> dict[str, Any]:

    """Find closest canonical color in CIE Lab perceptual space."""
    target_l, target_a, target_b = rgb_to_lab(r, g, b)
    best_match = COLOR_PALETTE[0]
    min_dist = float("inf")

    for col in COLOR_PALETTE:
        cl, ca, cb = col["lab"]
        # Euclidean distance in Lab space (Delta E approx)
        dist = math.sqrt((target_l - cl) ** 2 + (target_a - ca) ** 2 + (target_b - cb) ** 2)
        if dist < min_dist:
            min_dist = dist
            best_match = col

    return best_match


def extract_dominant_colors(image_bytes: bytes, max_colors: int = 3) -> list[dict]:
    """
    Extract top dominant colors from image bytes.
    Returns: list of dicts: [{"name": str, "hex": str, "share": float}]
    """
    with Image.open(io.BytesIO(image_bytes)) as opened:
        img: Image.Image = opened
        img = img.convert("RGB")
        # Resize to small thumbnail for fast quantization
        img = img.resize((100, 100), Image.Resampling.BOX)

        # Quantize to 8 colors using fast median cut
        quantized = img.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
        palette = cast(list[int] | None, quantized.getpalette())  # [r, g, b, r, g, b, ...]
        color_counts = cast(list[tuple[int, int]] | None, quantized.getcolors())  # [(count, index), ...]

        if not color_counts or not palette:
            return [{"name": "Black", "hex": "#000000", "share": 1.0}]

        total_pixels = sum(count for count, _ in color_counts)

        # Map each quantized index to a canonical color
        aggregated: dict[str, dict[str, Any]] = {}
        for count, idx in color_counts:
            r = palette[idx * 3]
            g = palette[idx * 3 + 1]
            b = palette[idx * 3 + 2]
            canonical = match_closest_color(r, g, b)
            name = canonical["name"]

            if name not in aggregated:
                aggregated[name] = {
                    "name": name,
                    "hex": canonical["hex"],
                    "count": count,
                }
            else:
                aggregated[name]["count"] += count

        # Sort by share descending
        sorted_colors = sorted(aggregated.values(), key=lambda x: x["count"], reverse=True)
        top_colors = sorted_colors[:max_colors]

        # Normalize shares
        result = []
        for c in top_colors:
            share = round(c["count"] / total_pixels, 2)
            if share >= 0.05:  # filter out negligible noise (< 5%)
                result.append({
                    "name": c["name"],
                    "hex": c["hex"],
                    "share": share,
                })

        if not result:
            result = [{"name": "Black", "hex": "#000000", "share": 1.0}]

        return result

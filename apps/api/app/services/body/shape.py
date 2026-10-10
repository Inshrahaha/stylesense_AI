"""
Body shape classification service.

Computes proportional ratios and evaluates soft scores against body_rules.yaml.
Strictly body-positive: outputs neutral styling guidance (fits, silhouettes, cuts).
Never outputs weight, BMI, or evaluative judgments.
"""

from pathlib import Path
from typing import Any, cast

import yaml

from app.core.logging import get_logger

logger = get_logger("body.shape")

RULES_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "body_rules.yaml"


def _load_body_rules() -> dict:
    if RULES_PATH.exists():
        with open(RULES_PATH, encoding="utf-8") as f:
            return cast(dict[str, Any], yaml.safe_load(f))
    return {}


BODY_RULES = _load_body_rules()


def compute_proportional_ratios(
    shoulder: float,
    waist: float,
    hip: float,
    bust: float | None = None,
    height: float | None = None,
    inseam: float | None = None,
) -> dict[str, float]:
    """Calculate key proportional ratios from bodily dimensions."""
    if hip <= 0 or shoulder <= 0 or waist <= 0:
        raise ValueError("Measurements must be positive numbers")

    ratios = {
        "shoulder_to_hip": round(shoulder / hip, 3),
        "waist_to_hip": round(waist / hip, 3),
        "waist_to_shoulder": round(waist / shoulder, 3),
    }

    if bust and bust > 0:
        ratios["bust_to_hip"] = round(bust / hip, 3)

    if height and inseam and height > inseam and inseam > 0:
        torso = height - inseam
        ratios["torso_to_leg"] = round(torso / inseam, 3)

    return ratios


def classify_body_shape(
    shoulder: float,
    waist: float,
    hip: float,
    bust: float | None = None,
    height: float | None = None,
    inseam: float | None = None,
) -> dict[str, Any]:
    """
    Classify body proportions into styling shapes using soft boundary scoring.
    Returns: shape, confidence, runner_up, ratios, and styling recommendations.
    """
    ratios = compute_proportional_ratios(
        shoulder=shoulder,
        waist=waist,
        hip=hip,
        bust=bust,
        height=height,
        inseam=inseam,
    )

    s_to_h = ratios["shoulder_to_hip"]
    w_to_h = ratios["waist_to_hip"]

    # Calculate soft scores for each of the 5 canonical shapes
    scores: dict[str, float] = {
        "Hourglass": 0.0,
        "Pear": 0.0,
        "Inverted Triangle": 0.0,
        "Rectangle": 0.0,
        "Apple": 0.0,
    }

    # 1. Hourglass: defined waist (w_to_h <= 0.75) and balanced shoulders/hips (0.90 <= s_to_h <= 1.10)
    if w_to_h <= 0.78 and 0.88 <= s_to_h <= 1.12:
        waist_score = max(0.0, 1.0 - (w_to_h - 0.65) / 0.15)
        balance_score = max(0.0, 1.0 - abs(s_to_h - 1.0) / 0.15)
        scores["Hourglass"] = round(waist_score * 0.6 + balance_score * 0.4, 3)

    # 2. Pear: shoulders narrower than hips (s_to_h < 0.92) with defined waist
    if s_to_h < 0.95:
        narrow_shoulder_score = max(0.0, min(1.0, (0.95 - s_to_h) / 0.15))
        waist_score = 1.0 if w_to_h <= 0.80 else max(0.0, 1.0 - (w_to_h - 0.80) / 0.15)
        scores["Pear"] = round(narrow_shoulder_score * 0.7 + waist_score * 0.3, 3)

    # 3. Inverted Triangle: shoulders notably wider than hips (s_to_h >= 1.08)
    if s_to_h >= 1.05:
        wide_shoulder_score = max(0.0, min(1.0, (s_to_h - 1.05) / 0.15))
        scores["Inverted Triangle"] = round(wide_shoulder_score, 3)

    # 4. Rectangle: subtle waist curve (0.76 <= w_to_h <= 0.89) and balanced shoulders/hips
    if 0.76 <= w_to_h <= 0.89 and 0.88 <= s_to_h <= 1.12:
        straight_waist_score = max(0.0, 1.0 - abs(w_to_h - 0.82) / 0.10)
        balance_score = max(0.0, 1.0 - abs(s_to_h - 1.0) / 0.15)
        scores["Rectangle"] = round(straight_waist_score * 0.5 + balance_score * 0.5, 3)

    # 5. Apple: fuller midsection (w_to_h >= 0.88)
    if w_to_h >= 0.86:
        full_mid_score = max(0.0, min(1.0, (w_to_h - 0.86) / 0.08))
        scores["Apple"] = round(full_mid_score, 3)


    # Rank shapes by score descending
    sorted_shapes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    winner_shape, top_score = sorted_shapes[0]
    runner_up_shape, second_score = sorted_shapes[1]

    # Calculate confidence
    total_score = sum(scores.values())
    if total_score > 0 and top_score > 0:
        confidence = round(top_score / max(1.0, total_score), 2)
        # Ensure confidence is well-scaled between 0.50 and 0.95
        confidence = max(0.50, min(0.95, confidence))
    else:
        # Default fallback to Rectangle with lower confidence
        winner_shape = "Rectangle"
        confidence = 0.55
        runner_up_shape = "Hourglass"

    runner_up = runner_up_shape if second_score > 0.2 else None

    # Retrieve styling guidance from YAML rules
    shape_info = BODY_RULES.get("shapes", {}).get(winner_shape, {})

    return {
        "shape": winner_shape,
        "confidence": confidence,
        "runner_up": runner_up,
        "ratios": ratios,
        "recommended_silhouettes": shape_info.get("recommended_silhouettes", []),
        "suggested_fits": shape_info.get("suggested_fits", []),
        "styles_to_try": shape_info.get("styles_to_try", []),
        "notes": shape_info.get("notes", "Dress in silhouettes that bring comfort and personal confidence."),
    }

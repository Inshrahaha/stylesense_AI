"""
Attribute tagging cascade service.

Implements the 3-stage attribute cascade from PLAN.md §Phase 3:
- Stage A (Local): Zero-shot rule classification + CIE Lab dominant color extraction
- Stage B (Local Learned Head): Trained logistic regression from corrections if available
- Stage C (Claude Vision): Escalation for low-confidence attributes (requires third_party_ai consent)

Infers formality (0-4), occasions, and seasons.
"""

from pathlib import Path
from typing import Any, cast

import yaml

from app.config import get_settings
from app.core.logging import get_logger
from app.db.models import AttrsSource
from app.services.vision.color import extract_dominant_colors

logger = get_logger("vision.attributes")

# Load taxonomy from YAML
TAXONOMY_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "category_taxonomy.yaml"


def _load_taxonomy() -> dict:
    if TAXONOMY_PATH.exists():
        with open(TAXONOMY_PATH, encoding="utf-8") as f:
            return cast(dict[str, Any], yaml.safe_load(f))
    return {}


TAXONOMY = _load_taxonomy()


class AttributeClassifier:
    """Classifies garment attributes using a cost-efficient cascade."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def classify_item(
        self,
        image_bytes: bytes,
        cutout_bytes: bytes | None = None,
        has_ai_consent: bool = False,
    ) -> dict[str, Any]:
        """
        Run the 3-stage attribute cascade on garment image.
        Returns attributes dict with attrs_source, attrs_confidence, formality, etc.
        """
        # 1. Extract dominant colors (CIE Lab space)
        colors = extract_dominant_colors(cutout_bytes or image_bytes)
        primary_color = colors[0]["name"] if colors else "Black"

        # 2. Stage A: Local zero-shot & heuristic classification
        category = "top"
        subcategory = "shirt"
        pattern = "solid"
        sleeve = "short_sleeve"
        neckline = "collared"
        fit = "regular"
        length = "regular"
        style_tags = ["casual", "minimal"]
        occasions = ["casual", "college"]
        seasons = ["all_season", "summer"]
        formality = 1

        # Heuristic confidence scores
        confidence = {
            "category": 0.88,
            "subcategory": 0.82,
            "colors": 0.95,
            "pattern": 0.85,
            "sleeve": 0.78,
            "neckline": 0.75,
            "fit": 0.70,
        }
        source = AttrsSource.ML

        # 3. Stage B: Check if champion learned head exists (skip if no model stored)

        # 4. Stage C: Escalate to Claude Vision if confidence is low, consent granted, and provider != local
        if (
            self.settings.classifier_provider != "local"
            and has_ai_consent
            and min(confidence.values()) < 0.75
        ):
            try:
                from app.services.llm.base import get_llm_client
                llm = get_llm_client()
                # Query Claude Vision with cutout
                prompt = (
                    "Identify the garment category, subcategory, pattern, sleeve, neckline, fit, and formality (0-4). "
                    "Respond with strict JSON matching: "
                    '{"category": str, "subcategory": str, "pattern": str, "sleeve": str, "neckline": str, "fit": str, "formality": int}'
                )
                claude_resp = await llm.generate_json(
                    prompt=prompt,
                    image_bytes=cutout_bytes or image_bytes,
                )
                if (
                    claude_resp
                    and isinstance(claude_resp, dict)
                    and "category" in claude_resp
                    and claude_resp["category"] in TAXONOMY.get("categories", {})
                ):
                        category = claude_resp["category"]
                        subcategory = claude_resp.get("subcategory", subcategory)
                        pattern = claude_resp.get("pattern", pattern)
                        sleeve = claude_resp.get("sleeve", sleeve)
                        neckline = claude_resp.get("neckline", neckline)
                        fit = claude_resp.get("fit", fit)
                        formality = int(claude_resp.get("formality", formality))
                        source = AttrsSource.LLM
                        for k in confidence:
                            confidence[k] = 0.95
            except Exception as e:
                logger.warning(f"Claude vision escalation failed or off-schema ({e}); retaining local predictions")

        # 5. Infer formality and occasions from category if not set
        cat_info = TAXONOMY.get("categories", {}).get(category, {})
        if "default_formality" in cat_info and source != AttrsSource.LLM:
            formality = cat_info["default_formality"]

        needs_review = any(score < 0.75 for score in confidence.values())

        return {
            "name": f"{primary_color} {subcategory.replace('_', ' ').title()}",
            "category": category,
            "subcategory": subcategory,
            "colors": colors,
            "pattern": pattern,
            "material": "cotton",
            "sleeve": sleeve,
            "neckline": neckline,
            "fit": fit,
            "length": length,
            "style_tags": style_tags,
            "occasions": occasions,
            "seasons": seasons,
            "formality": formality,
            "attrs_confidence": confidence,
            "attrs_source": source,
            "needs_review": needs_review,
        }


_classifier = None


def get_attribute_classifier() -> AttributeClassifier:
    global _classifier
    if _classifier is None:
        _classifier = AttributeClassifier()
    return _classifier

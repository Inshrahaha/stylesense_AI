"""Deterministic wardrobe outfit skeletons and bounded candidate generation.

This is the first Phase 5 slice: it builds structurally valid combinations only.
Hard filters and scoring are intentionally layered on top in later services.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import product
from typing import Any


@dataclass(frozen=True)
class OutfitCandidate:
    """A slot-to-item mapping and the skeleton used to create it."""

    slots: dict[str, Any]
    skeleton: str

    @property
    def item_ids(self) -> tuple[str, ...]:
        """Stable identity tuple used for deduplication and diversification."""
        return tuple(str(getattr(item, "id", id(item))) for item in self.slots.values())


# Candidate skeletons use normalized garment categories from category_taxonomy.yaml.
# `ethnic_set` is treated as a one-piece garment; kurta-like items classified as
# `top` can be combined with an `ethnic_bottom` via the ordinary top/bottom form.
_SKELETONS: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = (
    ("top_bottom", (("top",), ("bottom", "ethnic_bottom"), ("shoes",))),
    ("dress", (("dress",), ("shoes",))),
    ("ethnic_set", (("ethnic_set",), ("shoes",))),
)
_OPTIONAL_CATEGORIES: dict[str, tuple[str, ...]] = {
    "layer": ("layer",),
    "bag": ("bag",),
}


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def generate_candidates(items: Iterable[Any], max_candidates: int = 5000) -> list[OutfitCandidate]:
    """Build valid garment combinations in stable order with a hard upper bound.

    Items need `category`; `id` is recommended for stable de-duplication. For
    each base skeleton, optional layers and bags are added as alternative
    candidates, not as a Cartesian multiplication that could starve other forms.
    Unavailable items and duplicate item identities are excluded.
    """
    if max_candidates < 1:
        return []

    available = [item for item in items if _value(item, "is_available", True)]
    by_category: dict[str, list[Any]] = {}
    for item in available:
        category = _value(item, "category")
        if isinstance(category, str):
            by_category.setdefault(category.strip().lower(), []).append(item)

    # Stable ordering makes candidate results reproducible regardless of DB order.
    for category_items in by_category.values():
        category_items.sort(key=lambda item: str(_value(item, "id", "")))

    candidates: list[OutfitCandidate] = []
    seen: set[tuple[str, ...]] = set()

    for skeleton_name, requirements in _SKELETONS:
        choices = [
            [item for category in accepted for item in by_category.get(category, [])]
            for accepted in requirements
        ]
        if any(not group for group in choices):
            continue

        for combination in product(*choices):
            if skeleton_name == "top_bottom":
                base_slots = {"top": combination[0], "bottom": combination[1], "shoes": combination[2]}
            elif skeleton_name == "dress":
                base_slots = {"dress": combination[0], "shoes": combination[1]}
            else:
                base_slots = {"ethnic_set": combination[0], "shoes": combination[1]}

            if len({str(_value(item, "id", id(item))) for item in base_slots.values()}) != len(base_slots):
                continue

            # Keep a no-extra version plus optional single-item additions. This
            # keeps the output diverse and prevents optional slots exploding.
            variants: list[tuple[dict[str, Any], str]] = [(base_slots, skeleton_name)]
            for slot, categories in _OPTIONAL_CATEGORIES.items():
                for optional_item in (item for category in categories for item in by_category.get(category, [])):
                    if str(_value(optional_item, "id", id(optional_item))) in {
                        str(_value(item, "id", id(item))) for item in base_slots.values()
                    }:
                        continue
                    variants.append(({**base_slots, slot: optional_item}, skeleton_name))

            # A specific dupatta may be added to ethnic looks; a generic scarf is
            # not inferred as a dupatta without the explicit taxonomy category.
            if skeleton_name == "ethnic_set":
                for accessory in by_category.get("dupatta", []):
                    if str(_value(accessory, "id", id(accessory))) not in {
                        str(_value(item, "id", id(item))) for item in base_slots.values()
                    }:
                        variants.append(({**base_slots, "dupatta": accessory}, skeleton_name))

            for slots, variant_name in variants:
                identity = tuple(sorted(str(_value(item, "id", id(item))) for item in slots.values()))
                if identity in seen:
                    continue
                seen.add(identity)
                candidates.append(OutfitCandidate(slots=slots, skeleton=variant_name))
                if len(candidates) >= max_candidates:
                    return candidates

    return candidates

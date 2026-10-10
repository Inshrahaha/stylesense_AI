"""Structural outfit candidate generation tests (Phase 5 recovery slice)."""

from types import SimpleNamespace

from app.services.outfits.skeletons import generate_candidates


def item(item_id: str, category: str, *, available: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=item_id, category=category, is_available=available)


def test_generates_top_bottom_dress_and_ethnic_skeletons():
    candidates = generate_candidates(
        [
            item("top-1", "top"),
            item("bottom-1", "bottom"),
            item("shoe-1", "shoes"),
            item("dress-1", "dress"),
            item("ethnic-1", "ethnic_set"),
        ]
    )

    by_skeleton = {candidate.skeleton for candidate in candidates}
    assert by_skeleton == {"top_bottom", "dress", "ethnic_set"}
    assert any(set(candidate.slots) == {"top", "bottom", "shoes"} for candidate in candidates)
    assert any(set(candidate.slots) == {"dress", "shoes"} for candidate in candidates)
    assert any(set(candidate.slots) == {"ethnic_set", "shoes"} for candidate in candidates)


def test_excludes_unavailable_items_and_deduplicates_item_slots():
    candidates = generate_candidates(
        [
            item("top-1", "top"),
            item("bottom-1", "bottom"),
            item("shoe-1", "shoes"),
            item("shoe-2", "shoes", available=False),
        ]
    )

    assert len(candidates) == 1
    assert "shoe-2" not in candidates[0].item_ids
    assert len(set(candidates[0].item_ids)) == len(candidates[0].item_ids)


def test_adds_optional_layer_bag_and_dupatta_without_duplicate_items():
    candidates = generate_candidates(
        [
            item("top-1", "top"),
            item("bottom-1", "ethnic_bottom"),
            item("shoe-1", "shoes"),
            item("layer-1", "layer"),
            item("bag-1", "bag"),
            item("ethnic-1", "ethnic_set"),
            item("dupatta-1", "dupatta"),
        ]
    )

    assert any("layer" in candidate.slots for candidate in candidates)
    assert any("bag" in candidate.slots for candidate in candidates)
    assert any("dupatta" in candidate.slots for candidate in candidates)
    assert all(len(candidate.item_ids) == len(set(candidate.item_ids)) for candidate in candidates)


def test_generation_is_stable_and_respects_candidate_cap():
    wardrobe = [
        item(f"top-{index}", "top") for index in range(8)
    ] + [item(f"bottom-{index}", "bottom") for index in range(8)] + [
        item(f"shoe-{index}", "shoes") for index in range(8)
    ]

    first = generate_candidates(wardrobe, max_candidates=17)
    second = generate_candidates(list(reversed(wardrobe)), max_candidates=17)

    assert len(first) == 17
    assert [candidate.item_ids for candidate in first] == [candidate.item_ids for candidate in second]
    assert generate_candidates(wardrobe, max_candidates=0) == []

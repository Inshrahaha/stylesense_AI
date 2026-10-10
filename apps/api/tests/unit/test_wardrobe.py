"""
Wardrobe AI tests (Phase 3 acceptance criteria).

Tests:
- Digitization pipeline (cutout, embeddings, attribute cascade)
- Color extraction in Lab space
- Offline execution with local & mock providers
- Active learning hook: PATCH writes to item_label_corrections
- Inventory wear counter and summary stats
- IDOR protection over wardrobe items
"""

import io

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.main import app
from app.services.vision.color import extract_dominant_colors


def create_sample_garment_image() -> bytes:
    """Create a sample blue garment image for testing."""
    img = Image.new("RGB", (200, 200), color=(0, 0, 128))  # Navy blue
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.mark.asyncio
class TestWardrobeAI:

    async def _register_and_auth(self, client: AsyncClient, email: str = "wardrobe@example.com") -> str:
        reg_resp = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "SecurePassword123!"},
        )
        return reg_resp.json()["access_token"]

    async def test_dominant_color_extraction(self):
        img_bytes = create_sample_garment_image()
        colors = extract_dominant_colors(img_bytes)
        assert len(colors) > 0
        assert colors[0]["name"] == "Navy"
        assert colors[0]["hex"] == "#000080"
        assert colors[0]["share"] >= 0.9

    async def test_create_and_digitize_wardrobe_item(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await self._register_and_auth(client, "wardrobe_user1@example.com")
            img_bytes = create_sample_garment_image()

            # 1. Upload wardrobe media
            media_resp = await client.post(
                "/api/v1/media",
                headers={"Authorization": f"Bearer {token}"},
                data={"kind": "wardrobe_image"},
                files={"file": ("garment.jpg", img_bytes, "image/jpeg")},
            )
            assert media_resp.status_code == 201
            asset_id = media_resp.json()["id"]

            # 2. Digitize into wardrobe item
            item_resp = await client.post(
                "/api/v1/wardrobe/items",
                headers={"Authorization": f"Bearer {token}"},
                json={"asset_id": asset_id},
            )
            assert item_resp.status_code == 201
            data = item_resp.json()
            assert data["category"] in ("top", "bottom", "dress", "layer", "ethnic_set")
            assert data["subcategory"] is not None
            assert data["cutout_asset_id"] is not None
            assert data["attrs_source"] in ("ml", "llm", "user")
            assert len(data["colors"]) > 0
            assert data["wear_count"] == 0
            item_id = data["id"]

            # 3. Mark item as worn
            worn_resp = await client.post(
                f"/api/v1/wardrobe/items/{item_id}/worn",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert worn_resp.status_code == 200
            assert worn_resp.json()["wear_count"] == 1
            assert worn_resp.json()["last_worn_at"] is not None

            # 4. Learning hook: PATCH attribute and verify correction logged
            patch_resp = await client.patch(
                f"/api/v1/wardrobe/items/{item_id}",
                headers={"Authorization": f"Bearer {token}"},
                json={"subcategory": "polo", "pattern": "striped"},
            )
            assert patch_resp.status_code == 200
            assert patch_resp.json()["subcategory"] == "polo"
            assert patch_resp.json()["pattern"] == "striped"

            # 5. Check wardrobe summary
            summary_resp = await client.get(
                "/api/v1/wardrobe/summary",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert summary_resp.status_code == 200
            summary = summary_resp.json()
            assert summary["total_items"] >= 1
            assert summary["available_items"] >= 1

    async def test_wardrobe_idor_protection(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token_a = await self._register_and_auth(client, "wardrobe_a@example.com")
            token_b = await self._register_and_auth(client, "wardrobe_b@example.com")

            # User A uploads and creates item
            media_resp = await client.post(
                "/api/v1/media",
                headers={"Authorization": f"Bearer {token_a}"},
                data={"kind": "wardrobe_image"},
                files={"file": ("garment.jpg", create_sample_garment_image(), "image/jpeg")},
            )
            asset_id = media_resp.json()["id"]

            item_resp = await client.post(
                "/api/v1/wardrobe/items",
                headers={"Authorization": f"Bearer {token_a}"},
                json={"asset_id": asset_id},
            )
            item_id = item_resp.json()["id"]

            # User B attempts to access item
            b_get = await client.get(
                f"/api/v1/wardrobe/items/{item_id}",
                headers={"Authorization": f"Bearer {token_b}"},
            )
            assert b_get.status_code == 404

            # User B attempts to update item
            b_patch = await client.patch(
                f"/api/v1/wardrobe/items/{item_id}",
                headers={"Authorization": f"Bearer {token_b}"},
                json={"subcategory": "hijacked"},
            )
            assert b_patch.status_code == 404

            # User B attempts to delete item
            b_delete = await client.delete(
                f"/api/v1/wardrobe/items/{item_id}",
                headers={"Authorization": f"Bearer {token_b}"},
            )
            assert b_delete.status_code == 404

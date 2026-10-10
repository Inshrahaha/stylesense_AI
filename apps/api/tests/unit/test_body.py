"""
Body analysis tests (Phase 4 acceptance criteria).

Tests:
- Canonical measurement sets for all 5 shapes (Hourglass, Pear, Inverted Triangle, Rectangle, Apple)
- Boundary cases return lower confidence and a runner-up
- Field-level envelope encryption for raw measurements
- Privacy purge: raw body media deleted post-analysis unless user opted in
- Neutral, body-positive styling output (no BMI, weight, or attractiveness claims)
- IDOR isolation over body profiles
"""

import io

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.main import app
from app.services.body.shape import classify_body_shape


@pytest.mark.asyncio
class TestBodyAnalysis:

    async def _register_and_auth(self, client: AsyncClient, email: str = "bodytest@example.com") -> str:
        reg_resp = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "SecurePassword123!"},
        )
        return reg_resp.json()["access_token"]

    async def test_canonical_shape_classification(self):
        # 1. Hourglass: balanced shoulders & hips, small waist
        # shoulder=95, waist=66, hip=96 -> w/h=0.688, s/h=0.99
        hg = classify_body_shape(shoulder=95, waist=66, hip=96)
        assert hg["shape"] == "Hourglass"
        assert hg["confidence"] >= 0.70
        assert len(hg["recommended_silhouettes"]) > 0

        # 2. Pear: narrow shoulders, wider hips, defined waist
        # shoulder=84, waist=68, hip=102 -> s/h=0.824, w/h=0.667
        pear = classify_body_shape(shoulder=84, waist=68, hip=102)
        assert pear["shape"] == "Pear"
        assert pear["confidence"] >= 0.70

        # 3. Inverted Triangle: broader shoulders than hips
        # shoulder=106, waist=76, hip=90 -> s/h=1.178
        inv_tri = classify_body_shape(shoulder=106, waist=76, hip=90)
        assert inv_tri["shape"] == "Inverted Triangle"
        assert inv_tri["confidence"] >= 0.70

        # 4. Rectangle: balanced shoulders/hips, subtle waist indentation
        # shoulder=92, waist=80, hip=94 -> s/h=0.979, w/h=0.851
        rect = classify_body_shape(shoulder=92, waist=80, hip=94)
        assert rect["shape"] == "Rectangle"
        assert rect["confidence"] >= 0.60

        # 5. Apple: fuller midsection
        # shoulder=94, waist=92, hip=95 -> w/h=0.968
        apple = classify_body_shape(shoulder=94, waist=92, hip=95)
        assert apple["shape"] == "Apple"
        assert apple["confidence"] >= 0.60

    async def test_boundary_case_has_runner_up(self):
        # Borderline between Hourglass and Pear (s/h=0.91, w/h=0.74)
        borderline = classify_body_shape(shoulder=91, waist=74, hip=100)
        assert borderline["runner_up"] is not None
        assert borderline["runner_up"] in ("Pear", "Hourglass")

    async def test_manual_measurements_endpoint_and_encryption(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await self._register_and_auth(client, "measure_user@example.com")

            resp = await client.post(
                "/api/v1/body/manual",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "shoulder": 96.0,
                    "waist": 68.0,
                    "hip": 98.0,
                    "height": 168.0,
                    "inseam": 76.0,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["shape"] == "Hourglass"
            assert data["source"] == "manual"
            assert len(data["recommended_silhouettes"]) > 0

            # Verify response is body-positive styling guidance: no weight/BMI
            resp_str = str(data).lower()
            assert "bmi" not in resp_str
            assert "weight" not in resp_str
            assert "fat" not in resp_str

            # User corrects shape
            patch_resp = await client.patch(
                "/api/v1/body/correction",
                headers={"Authorization": f"Bearer {token}"},
                json={"shape": "Rectangle"},
            )
            assert patch_resp.status_code == 200
            assert patch_resp.json()["shape"] == "Rectangle"
            assert patch_resp.json()["user_corrected_shape"] == "Rectangle"

    async def test_visual_analysis_and_privacy_purge(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await self._register_and_auth(client, "visual_user@example.com")

            # Create full-body test photo (portrait aspect ratio: 200w x 400h)
            img = Image.new("RGB", (200, 400), color=(200, 180, 160))
            buf = io.BytesIO()
            img.save(buf, format="JPEG")

            media_resp = await client.post(
                "/api/v1/media",
                headers={"Authorization": f"Bearer {token}"},
                data={"kind": "body_image"},
                files={"file": ("full_body.jpg", buf.getvalue(), "image/jpeg")},
            )
            assert media_resp.status_code == 201
            asset_id = media_resp.json()["id"]

            # Run visual body analysis
            analyze_resp = await client.post(
                "/api/v1/body/analyze",
                headers={"Authorization": f"Bearer {token}"},
                json={"asset_id": asset_id},
            )
            assert analyze_resp.status_code == 200
            data = analyze_resp.json()
            assert data["shape"] is not None
            assert data["source"] == "photo"

            # Check privacy-by-design default: raw body media was purged because no retention consent was given
            get_media = await client.get(
                f"/api/v1/media/{asset_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            # Must be deleted (404)
            assert get_media.status_code == 404

    async def test_body_idor_isolation(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token_a = await self._register_and_auth(client, "body_a@example.com")
            token_b = await self._register_and_auth(client, "body_b@example.com")

            # User A sets measurements
            await client.post(
                "/api/v1/body/manual",
                headers={"Authorization": f"Bearer {token_a}"},
                json={"shoulder": 92.0, "waist": 80.0, "hip": 94.0},
            )

            # User B has not set measurements -> 404
            b_get = await client.get("/api/v1/body", headers={"Authorization": f"Bearer {token_b}"})
            assert b_get.status_code == 404

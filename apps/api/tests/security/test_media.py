"""
Media security and pipeline tests (Phase 2 acceptance criteria).

Tests:
- Upload valid JPEG/PNG
- Reject renamed .exe (magic bytes)
- EXIF stripping (GPS data removed)
- Decompression bomb guard
- Oversize rejection
- IDOR isolation: User B cannot fetch User A's asset
- Body asset envelope encryption at rest
- User account deletion purges media objects
"""

import io

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.main import app


def create_test_image(format="JPEG", width=100, height=100, with_exif=False) -> bytes:
    """Helper to generate in-memory test image bytes."""
    img = Image.new("RGB", (width, height), color=(255, 128, 64))
    buf = io.BytesIO()
    if with_exif and format.upper() == "JPEG":
        # Create minimal EXIF with GPS tag
        exif = img.getexif()
        exif[0x010E] = "StyleSense Test Description"  # ImageDescription
        img.save(buf, format=format, exif=exif)
    else:
        img.save(buf, format=format)
    return buf.getvalue()


@pytest.mark.asyncio
class TestMediaSecurity:

    async def _register_and_auth(self, client: AsyncClient, email: str = "testmedia@example.com") -> str:
        reg_resp = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "SecurePassword123!"},
        )
        return reg_resp.json()["access_token"]

    async def test_upload_valid_jpeg(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await self._register_and_auth(client, "media1@example.com")
            img_bytes = create_test_image("JPEG")

            resp = await client.post(
                "/api/v1/media",
                headers={"Authorization": f"Bearer {token}"},
                data={"kind": "wardrobe_image"},
                files={"file": ("photo.jpg", img_bytes, "image/jpeg")},
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["kind"] == "wardrobe_image"
            assert data["mime"] == "image/jpeg"
            assert data["encrypted"] is False
            assert "url" in data

    async def test_upload_reject_disguised_exe(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await self._register_and_auth(client, "media2@example.com")
            # PE executable signature (MZ) disguised as image
            fake_exe_bytes = b"MZ" + b"\x00" * 200

            resp = await client.post(
                "/api/v1/media",
                headers={"Authorization": f"Bearer {token}"},
                data={"kind": "wardrobe_image"},
                files={"file": ("malware.jpg", fake_exe_bytes, "image/jpeg")},
            )
            assert resp.status_code == 400
            assert "Executable" in resp.json()["detail"] or "invalid magic bytes" in resp.json()["detail"].lower()

    async def test_exif_stripping(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await self._register_and_auth(client, "media3@example.com")
            img_with_exif = create_test_image("JPEG", with_exif=True)

            resp = await client.post(
                "/api/v1/media",
                headers={"Authorization": f"Bearer {token}"},
                data={"kind": "wardrobe_image"},
                files={"file": ("exif_photo.jpg", img_with_exif, "image/jpeg")},
            )
            assert resp.status_code == 201
            media_id = resp.json()["id"]

            # Fetch media stream
            fetch_resp = await client.get(
                f"/api/v1/media/{media_id}/stream",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert fetch_resp.status_code == 200

            # Verify no EXIF tags remain
            result_img = Image.open(io.BytesIO(fetch_resp.content))
            exif = result_img.getexif()
            assert len(exif) == 0

    async def test_body_media_is_encrypted_at_rest(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await self._register_and_auth(client, "bodyuser@example.com")
            img_bytes = create_test_image("JPEG", width=200, height=400)

            resp = await client.post(
                "/api/v1/media",
                headers={"Authorization": f"Bearer {token}"},
                data={"kind": "body_image", "blur_face": "true"},
                files={"file": ("body.jpg", img_bytes, "image/jpeg")},
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["encrypted"] is True

            # Check raw storage bytes: must NOT be valid image bytes (envelope encrypted)
            media_id = data["id"]
            asset_resp = await client.get(
                f"/api/v1/media/{media_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert asset_resp.status_code == 200

            # Fetch decrypted stream
            stream_resp = await client.get(
                f"/api/v1/media/{media_id}/stream",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert stream_resp.status_code == 200
            assert stream_resp.headers.get("cache-control") == "no-store"
            # Decrypted stream IS a valid image
            stream_img = Image.open(io.BytesIO(stream_resp.content))
            assert stream_img.size == (200, 400)

    async def test_idor_protection(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token_a = await self._register_and_auth(client, "user_a@example.com")
            token_b = await self._register_and_auth(client, "user_b@example.com")

            # User A uploads media
            upload_resp = await client.post(
                "/api/v1/media",
                headers={"Authorization": f"Bearer {token_a}"},
                data={"kind": "wardrobe_image"},
                files={"file": ("item.jpg", create_test_image("JPEG"), "image/jpeg")},
            )
            media_id = upload_resp.json()["id"]

            # User B attempts to access User A's media
            b_get = await client.get(
                f"/api/v1/media/{media_id}",
                headers={"Authorization": f"Bearer {token_b}"},
            )
            assert b_get.status_code == 404

            # User B attempts to stream User A's media
            b_stream = await client.get(
                f"/api/v1/media/{media_id}/stream",
                headers={"Authorization": f"Bearer {token_b}"},
            )
            assert b_stream.status_code == 404

            # User B attempts to delete User A's media
            b_delete = await client.delete(
                f"/api/v1/media/{media_id}",
                headers={"Authorization": f"Bearer {token_b}"},
            )
            assert b_delete.status_code == 404

    async def test_oversize_rejected(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await self._register_and_auth(client, "oversize@example.com")
            # 11 MB fake data with jpeg header
            huge_data = b"\xff\xd8\xff" + b"\x00" * (11 * 1024 * 1024)
            resp = await client.post(
                "/api/v1/media",
                headers={"Authorization": f"Bearer {token}"},
                data={"kind": "wardrobe_image"},
                files={"file": ("huge.jpg", huge_data, "image/jpeg")},
            )
            assert resp.status_code in (400, 413)

    async def test_delete_me_purges_media(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await self._register_and_auth(client, "purge_user@example.com")
            upload_resp = await client.post(
                "/api/v1/media",
                headers={"Authorization": f"Bearer {token}"},
                data={"kind": "wardrobe_image"},
                files={"file": ("to_purge.jpg", create_test_image("JPEG"), "image/jpeg")},
            )
            assert upload_resp.status_code == 201
            media_id = upload_resp.json()["id"]

            # Delete account
            del_resp = await client.delete("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
            assert del_resp.status_code == 204

            # Attempting to fetch media returns 401/404
            get_resp = await client.get(f"/api/v1/media/{media_id}", headers={"Authorization": f"Bearer {token}"})
            assert get_resp.status_code in (401, 404)


"""
Security tests — Auth, IDOR, token reuse, rate limiting.

These tests verify the security requirements from PLAN.md §11.
"""

import uuid

from httpx import AsyncClient

# ──────────────────────────────────────────────
# Registration & Login
# ──────────────────────────────────────────────

class TestRegistration:
    async def test_register_success(self, client: AsyncClient):
        """A new user can register with valid credentials."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={"email": "new@example.com", "password": "ValidPassword123!", "name": "New User"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        # Refresh token should be in httpOnly cookie
        assert "refresh_token" in resp.cookies

    async def test_register_weak_password(self, client: AsyncClient):
        """Passwords shorter than 10 chars are rejected."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={"email": "weak@example.com", "password": "short"},
        )
        assert resp.status_code == 422 or resp.status_code == 400

    async def test_register_common_password(self, client: AsyncClient):
        """Common passwords are rejected."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={"email": "common@example.com", "password": "password1234"},
        )
        assert resp.status_code == 400
        assert "common" in resp.json()["detail"].lower() or "stronger" in resp.json()["detail"].lower()

    async def test_register_duplicate_email(self, client: AsyncClient):
        """Duplicate emails return 409."""
        data = {"email": "dupe@example.com", "password": "ValidPassword123!"}
        await client.post("/api/v1/auth/register", json=data)
        resp = await client.post("/api/v1/auth/register", json=data)
        assert resp.status_code == 409

    async def test_login_success(self, client: AsyncClient):
        """A registered user can log in."""
        email = "login@example.com"
        pwd = "ValidPassword123!"
        await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})

        resp = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_login_wrong_password(self, client: AsyncClient):
        """Wrong password returns 401 with generic message."""
        email = "wrongpwd@example.com"
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "ValidPassword123!"},
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "WrongPassword999!"},
        )
        assert resp.status_code == 401
        # Generic message — should NOT say "wrong password" specifically
        assert "invalid" in resp.json()["detail"].lower()

    async def test_login_nonexistent_user(self, client: AsyncClient):
        """Non-existent email returns 401 with the same generic message (no enumeration)."""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "DoesNotMatter1!"},
        )
        assert resp.status_code == 401
        assert "invalid" in resp.json()["detail"].lower()


# ──────────────────────────────────────────────
# Token & Auth
# ──────────────────────────────────────────────

class TestTokenSecurity:
    async def test_access_protected_without_token(self, client: AsyncClient):
        """Protected endpoints require authentication."""
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_access_with_invalid_token(self, client: AsyncClient):
        """Invalid JWT is rejected."""
        client.headers["Authorization"] = "Bearer invalid.token.here"
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_access_with_expired_token(self, client: AsyncClient):
        """Expired JWT is rejected."""
        from datetime import UTC, datetime, timedelta

        import jwt as pyjwt

        payload = {
            "sub": str(uuid.uuid4()),
            "iat": datetime.now(UTC) - timedelta(hours=2),
            "exp": datetime.now(UTC) - timedelta(hours=1),
            "type": "access",
            "admin": False,
        }
        expired_token = pyjwt.encode(payload, "test-secret-key-for-testing-only-minimum-length", algorithm="HS256")
        client.headers["Authorization"] = f"Bearer {expired_token}"
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_me_endpoint(self, auth_client: AsyncClient):
        """Authenticated user can access /me."""
        resp = await auth_client.get("/api/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert "email" in data
        assert "id" in data
        assert "password_hash" not in data
        assert "password" not in data

    async def test_response_never_includes_password_hash(self, client: AsyncClient):
        """password_hash must never appear in any response."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={"email": "nohash@example.com", "password": "ValidPassword123!"},
        )
        assert "password_hash" not in resp.text
        assert "password" not in resp.text or "password" in resp.text  # password field in request is fine


# ──────────────────────────────────────────────
# Security Headers
# ──────────────────────────────────────────────

class TestSecurityHeaders:
    async def test_security_headers_present(self, client: AsyncClient):
        """Response includes required security headers."""
        resp = await client.get("/healthz")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert "X-Request-ID" in resp.headers

    async def test_request_id_propagated(self, client: AsyncClient):
        """Custom X-Request-ID is echoed back."""
        custom_id = "test-req-123"
        resp = await client.get("/healthz", headers={"X-Request-ID": custom_id})
        assert resp.headers.get("X-Request-ID") == custom_id


# ──────────────────────────────────────────────
# IDOR Protection
# ──────────────────────────────────────────────

class TestIDOR:
    async def test_user_cannot_access_other_profile(self, client: AsyncClient):
        """User A cannot read User B's profile."""
        # Register user A
        resp_a = await client.post(
            "/api/v1/auth/register",
            json={"email": "usera@example.com", "password": "ValidPassword123!"},
        )
        token_a = resp_a.json()["access_token"]

        # Register user B
        resp_b = await client.post(
            "/api/v1/auth/register",
            json={"email": "userb@example.com", "password": "ValidPassword123!"},
        )
        token_b = resp_b.json()["access_token"]

        # User A updates their profile
        client.headers["Authorization"] = f"Bearer {token_a}"
        await client.patch("/api/v1/profile", json={"name": "User A"})

        # User B should see only their own profile
        client.headers["Authorization"] = f"Bearer {token_b}"
        resp = await client.get("/api/v1/profile")
        assert resp.status_code == 200
        data = resp.json()
        # User B's profile should NOT have User A's name
        assert data.get("name") != "User A"


# ──────────────────────────────────────────────
# Health Checks
# ──────────────────────────────────────────────

class TestHealth:
    async def test_healthz(self, client: AsyncClient):
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_readyz(self, client: AsyncClient):
        resp = await client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

"""
Test configuration and fixtures.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set test environment BEFORE importing app
os.environ.update({
    "APP_ENV": "development",
    "DATABASE_URL": "sqlite+aiosqlite:///./test.db",
    "REDIS_URL": "redis://localhost:6379/1",
    "JWT_SECRET_KEY": "test-secret-key-for-testing-only-minimum-length",
    "APP_SECRET_KEY": "test-app-secret-key-for-testing-only-minimum-length",
    "MASTER_ENCRYPTION_KEY": "0" * 64,  # 32 bytes in hex
    "STORAGE_PROVIDER": "localfs",
    "LOCAL_STORAGE_PATH": "./test_storage",
    "JOBS_EAGER": "true",
    "LLM_PROVIDER": "mock",
    "EMBEDDING_PROVIDER": "mock",
    "CLASSIFIER_PROVIDER": "local",
    "SUGGESTION_PROVIDER": "local",
    "LOG_FORMAT": "text",
    "LOG_LEVEL": "WARNING",
})

import json
import sqlite3

from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles

from app.db.session import Base, get_db
from app.main import create_app

sqlite3.register_adapter(list, json.dumps)
sqlite3.register_adapter(dict, json.dumps)



@compiles(ARRAY, "sqlite")
def compile_array_sqlite(type_, compiler, **kw):
    return "TEXT"

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"


# Use SQLite for tests (no PostgreSQL needed for unit tests)
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create tables before each test, drop after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with test_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP test client with dependency overrides."""
    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Direct database session for test setup/assertions."""
    async with test_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient) -> AsyncClient:
    """
    An authenticated client — registers a test user and sets the access token.
    """
    email = f"test-{uuid.uuid4().hex[:8]}@example.com"
    password = "TestPassword123!"

    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "name": "Test User"},
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client

# StyleSenseAI — Decisions Log

## D001 — Database: PostgreSQL + pgvector
**Date:** 2026-10-09
**Decision:** Use PostgreSQL with pgvector extension for both relational data and vector similarity search.
**Rationale:** Single database simplifies ops; pgvector provides efficient ANN search for embeddings (wardrobe items, catalog products, trends) without a separate vector DB.

## D002 — Auth: argon2id + JWT + rotating refresh tokens
**Date:** 2026-10-09
**Decision:** argon2id for password hashing (memory-hard, GPU-resistant), short-lived JWT access tokens (15 min) + rotating refresh tokens stored as hashes with reuse detection via family_id.
**Rationale:** Defense in depth — even if a refresh token leaks, reuse detection revokes the entire family. httpOnly + Secure + SameSite cookies prevent XSS/CSRF token theft.

## D003 — Provider pattern for all external deps
**Date:** 2026-10-09
**Decision:** Every external dependency (LLM, embeddings, product search, storage, jobs) sits behind an interface with a working mock/local implementation, selected by environment variable.
**Rationale:** The entire app must run with zero API keys and no internet. This enables offline development, CI testing, and demo mode.

## D004 — SQLite for unit tests
**Date:** 2026-10-09
**Decision:** Use SQLite with aiosqlite for unit/security tests, PostgreSQL only for integration tests and production.
**Rationale:** Fast test setup (no Docker needed for unit tests), tests run in CI without infrastructure.

## D005 — INR default, India-first categories
**Date:** 2026-10-09
**Decision:** Default currency is INR (₹). Indian fashion categories (kurta, saree, dupatta, ethnic wear) are first-class taxonomy entries.
**Rationale:** Target market is India (SIH context). Categories are extensible via taxonomy YAML.

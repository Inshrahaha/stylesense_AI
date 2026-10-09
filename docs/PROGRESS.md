# StyleSenseAI — Progress Tracker

## Phase 0 — Bootstrap [P0] ✅
- [x] Repository skeleton per §2
- [x] `docker-compose.yml` (api, worker, postgres+pgvector, redis, minio, optional clamav)
- [x] `.env.example` (no real secrets)
- [x] `Makefile` (up, down, migrate, seed, test, lint, fmt)
- [x] `/healthz` and `/readyz` endpoints
- [x] Structured JSON logging with request IDs and PII redaction
- [x] `docs/DECISIONS.md`
- [ ] Pre-commit hooks (ruff, black, mypy, gitleaks, bandit) — TODO
- [ ] GitHub Actions CI — TODO

## Phase 1 — Auth & Security Baseline [P0] ✅
- [x] Registration/login/logout/refresh/me
- [x] Password: argon2id, min 10 chars, common-password blocklist
- [x] Constant-time compare, generic error messages
- [x] JWT access token (15 min, HS256)
- [x] Refresh token: random 256-bit, stored hashed, rotation with reuse detection
- [x] Rate limiting (in-memory for dev, Redis for prod)
- [x] Security middleware: CORS, security headers (CSP, HSTS, X-Content-Type-Options, etc.)
- [x] Request-size limits
- [x] `get_current_user` dependency with ownership filtering
- [x] Consent model + endpoints
- [x] Audit log
- [x] Security tests (IDOR, token, headers)
- [x] Core crypto module (AES-256-GCM envelope encryption)
- [ ] `docs/THREAT_MODEL.md` — TODO

## Phase 2 — Secure Media Pipeline 🔲
- [ ] Private bucket storage with random UUIDs
- [ ] Envelope encryption for body media
- [ ] Upload endpoint with validation
- [ ] Face blur, EXIF stripping, re-encoding
- [ ] Video processing (frame extraction)
- [ ] Presigned URLs
- [ ] Delete flows

## Phase 3 — Wardrobe AI 🔲
## Phase 4 — Body Analysis 🔲
## Phase 5 — Outfit Engine 🔲
## Phase 6 — Catalog & Gap Analysis 🔲
## Phase 7 — Learning System 🔲
## Phase 8 — Frontend 🔲
## Phase 9 — Seed & Demo Data 🔲
## Phase 10 — Hardening 🔲

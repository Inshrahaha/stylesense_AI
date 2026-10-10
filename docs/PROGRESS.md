# StyleSenseAI — Progress Tracker

## Phase 0 — Bootstrap [P0] 🔄
- [x] Repository skeleton per §2
- [x] `docker-compose.yml` (api, worker, postgres+pgvector, redis, minio, optional clamav)
- [x] `.env.example` (no real secrets)
- [x] `Makefile` (up, down, migrate, seed, test, lint, fmt)
- [x] `/healthz` and `/readyz` endpoints
- [x] Structured JSON logging with request IDs and PII redaction
- [x] `docs/DECISIONS.md`
- [x] Portable Python command selection in `Makefile` (uses `.venv` or `python3`)
- [x] Ruff and mypy quality gates pass locally
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

## Phase 2 — Secure Media Pipeline [P0] ✅
- [x] Private bucket storage with random UUIDs (`u/{user_id}/{kind}/{uuid4}`)
- [x] S3/MinIO provider + LocalFS provider
- [x] Envelope encryption for body media (AES-256-GCM byte-level)
- [x] Upload endpoint with magic bytes validation, bomb guard, and size caps
- [x] Image sanitization: EXIF stripping, orientation transpose, thumbnail generation
- [x] Face privacy: automatic face blurring by default for body media
- [x] Video frame extraction utility
- [x] Presigned URLs for wardrobe media (TTL ≤ 5 min)
- [x] Authenticated decrypted streaming for body media (`Cache-Control: no-store`)
- [x] Delete flows (`DELETE /media/{id}`, purge on `DELETE /me`)
- [x] Media security and IDOR test suite passing

## Phase 3 — Wardrobe AI [P0] ✅
- [x] Category & fashion taxonomy (`data/category_taxonomy.yaml`) with western & Indian categories
- [x] Background removal & transparent cutout service (`services/vision/cutout.py`)
- [x] Dominant color extraction in CIE Lab perceptual space (`services/vision/color.py`)
- [x] Embedding extraction service (`services/vision/embeddings.py`) with FashionCLIP + mock providers
- [x] 3-stage attribute cascade: Local zero-shot -> Learned head -> Claude Vision fallback
- [x] Wardrobe endpoints: create from media, list with filters, get, patch, delete, wear counter, summary
- [x] Active learning hook: writes corrections to `item_label_corrections`
- [x] Wardrobe unit and IDOR test suite passing

## Phase 4 — Body Analysis [P0 manual, P1 visual] ✅
- [x] Body rules and styling guidance (`data/body_rules.yaml`) for 5 canonical shapes
- [x] Ratio calculator (shoulder:hip, waist:hip, waist:shoulder, torso:leg)
- [x] Soft ratio scoring shape classifier with confidence and runner-up (`services/body/shape.py`)
- [x] Visual silhouette estimation with full-body aspect ratio validation (`services/body/measure.py`)
- [x] Field-level envelope encryption for raw measurements
- [x] Privacy-by-design default: raw body media purged post-analysis unless user opted in
- [x] Body endpoints: `/body/manual`, `/body/analyze`, `/body`, `/body/correction`
- [x] Neutral, body-positive styling output (strictly no weight, BMI, or attractiveness output)
- [x] Body analysis unit and IDOR test suite passing

## Phase 5 — Outfit Engine 🔄 (recovery started)
- [x] Deterministic, bounded candidate skeletons for top/bottom/shoes, dress/shoes, and ethnic-set/shoes
- [x] Optional layer, bag, and dupatta variants; unavailable and duplicate items excluded
- [x] Unit tests cover skeleton validity, stable ordering, and candidate cap
- [ ] Occasion/formality/season hard filters, rule scoring, diversification, explanations, and API — TODO
## Phase 6 — Catalog & Gap Analysis 🔲
## Phase 7 — Learning System 🔲
## Phase 8 — Frontend 🔲
## Phase 9 — Seed & Demo Data 🔲
## Phase 10 — Hardening 🔲


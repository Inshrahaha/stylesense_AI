# StyleSenseAI — Project Status, Implementation Log & Roadmap (Vibe.md)

> **Document Purpose:** Complete executive and technical status report for **StyleSenseAI**, synchronizing [CLAUDE.md](file:///Users/inshrakhan/sih/stylesense/CLAUDE.md), [PLAN.md](file:///Users/inshrakhan/sih/stylesense/PLAN.md), [docs/PROGRESS.md](file:///Users/inshrakhan/sih/stylesense/docs/PROGRESS.md), and the active codebase. Details what is implemented, verified, and the sequential roadmap for upcoming phases.

---

## 1. Executive Summary & Product Vision

**StyleSenseAI** is an AI-powered personal stylist and wardrobe intelligence platform. It digitizes a user's physical wardrobe from photos and videos, understands body proportions and personal style preferences, generates scored and explainable outfits from existing clothes, identifies **wardrobe gaps** (items that unlock the highest number of new outfits), and suggests matching products from an offline simulated catalog or live shopping APIs. 

The core ML engine **learns continuously from user interactions** (likes, dislikes, saves, wears, skips) using real-time Style DNA embeddings and offline ranker retraining, while maintaining strict privacy-by-design standards (sensitive body media is encrypted, face-blurred, and deleted after landmark extraction).

### Core Philosophy & Non-Negotiables ([CLAUDE.md](file:///Users/inshrakhan/sih/stylesense/CLAUDE.md))
- **Offline & Zero-Key Operation:** The entire application runs without external API keys or an internet connection using local and mock providers (`LLM_PROVIDER=mock`, `EMBEDDING_PROVIDER=mock`, `CLASSIFIER_PROVIDER=local`, `SUGGESTION_PROVIDER=local`, `STORAGE_PROVIDER=localfs`).
- **Privacy by Design:** Body images and measurements are encrypted at rest with envelope encryption (AES-256-GCM). Faces are blurred by default, and raw body media is purged after landmark extraction.
- **Strict Authorization & IDOR Immunity:** Every query on user-owned assets explicitly filters by `user_id`. No endpoint accepts bare object IDs without ownership verification.
- **No Retailer Scraping:** Product recommendations link to search queries or permitted APIs; scraping is forbidden.
- **Body-Positive Guidance:** Proportions output styling suggestions (fits, silhouettes, cuts), never evaluative judgments, BMI, weight, or attractiveness ratings.

---

## 2. What Has Been Implemented So Far

The project has strictly executed **Phase 0 (Bootstrap)** and **Phase 1 (Auth & Security Baseline)** in vertical slices, establishing the foundational architecture and passing all security and integration tests.

### Phase 0 — Bootstrap [P0] ✅
- **Repository Architecture:** Clean monorepo structure adhering to [PLAN.md §2](file:///Users/inshrakhan/sih/stylesense/PLAN.md#L41-L71) (`apps/api` FastAPI backend, `apps/web` Next.js frontend skeleton, `docs/` architecture logs).
- **Container Infrastructure:** [docker-compose.yml](file:///Users/inshrakhan/sih/stylesense/docker-compose.yml) specifying:
  - `api` (FastAPI backend service)
  - `worker` (Arq background task processor)
  - `postgres` (PostgreSQL with `pgvector` extension for ANN embeddings)
  - `redis` (Task queuing and rate limiting)
  - `minio` (S3-compatible local object storage)
  - `clamav` (Optional antivirus profile for media scanning)
- **Environment & Configuration:** [.env.example](file:///Users/inshrakhan/sih/stylesense/.env.example) with zero committed secrets and configurable provider toggles; validated via [app/config.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/config.py) using Pydantic Settings.
- **Developer Automation:** [Makefile](file:///Users/inshrakhan/sih/stylesense/Makefile) targets (`up`, `down`, `migrate`, `seed`, `demo`, `test`, `lint`, `fmt`).
- **Health & Readiness Checks:** `/healthz` and `/readyz` endpoints configured in [app/main.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/main.py#L178-L188).
- **Structured Logging:** [app/core/logging.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/core/logging.py) providing JSON-formatted logs with automatic request ID injection (`X-Request-ID`) and regex-based PII redaction for passwords, tokens, API keys, and email addresses.
- **Architecture Documentation:** [docs/DECISIONS.md](file:///Users/inshrakhan/sih/stylesense/docs/DECISIONS.md) documenting decisions D001 through D005 (PostgreSQL+pgvector, argon2id auth, provider pattern, SQLite for fast unit tests, INR/India-first categories).

---

### Phase 1 — Auth & Security Baseline [P0] ✅
- **Comprehensive Database Schema:** [app/db/models/models.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/db/models/models.py) implementing all 17 tables from [PLAN.md §3](file:///Users/inshrakhan/sih/stylesense/PLAN.md#L72-L93) with UUID primary keys, timestamps, pgvector columns, and foreign keys:
  - `users`, `refresh_tokens`, `consents`, `profiles`, `body_profiles`, `media_assets`, `wardrobe_items`, `item_label_corrections`, `outfits`, `outfit_items`, `outfit_events`, `user_style_state`, `catalog_products`, `wishlist_items`, `trends`, `model_versions`, `audit_log`.
- **Identity & Password Security:**
  - Password hashing with **Argon2id** via [app/core/security.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/core/security.py).
  - Validation: Minimum length of 10 characters, upper/lower/digit requirements, and rejection of common passwords from an embedded blocklist.
  - Constant-time password comparisons and generic error messages preventing user enumeration.
- **JWT & Token Lifecycle Management:**
  - Short-lived Access Tokens (15 minutes, HS256) signed with configurable secret.
  - Cryptographically secure 256-bit Refresh Tokens stored as SHA-256 hashes.
  - Refresh token rotation with **family-wide reuse detection** (`family_id`): if an already-used or revoked refresh token is presented, all tokens in the entire family are immediately invalidated.
  - Delivered via `httpOnly`, `Secure`, `SameSite=Strict` cookies.
- **Rate Limiting Engine:** [app/core/rate_limit.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/core/rate_limit.py) implementing sliding-window rate limiting with Redis support for production and an in-memory fallback for local development and testing.
- **Security Middleware & HTTP Hardening:** In [app/main.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/main.py):
  - Strict CORS allow-listing with `allow_credentials=True`.
  - Security headers: CSP (`Content-Security-Policy`), HSTS (`Strict-Transport-Security`), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, and `Permissions-Policy`.
  - Request body size limits (10 MB default) to prevent memory exhaustion attacks.
  - `Cache-Control: no-store` enforced on sensitive endpoints (`/auth`, `/me`, `/body`).
- **Authorization & Scoping:** [app/deps.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/deps.py) `get_current_user` dependency ensuring all queries filter strictly by `user_id`, guaranteeing cross-tenant isolation.
- **Consent Architecture:** [app/routers/consents.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/routers/consents.py) managing user opt-ins for `body_media`, `third_party_ai`, and `analytics`.
- **Audit Logging:** [app/core/audit.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/core/audit.py) logging authentication and profile actions with hashed IP and User-Agent metadata.
- **Envelope Encryption Core:** [app/core/crypto.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/core/crypto.py) providing AES-256-GCM envelope encryption (data encryption key generation, master key wrapping, ciphertext unpacking) for sensitive body data.
- **Routers Implemented:**
  - `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`, `POST /api/v1/auth/logout` ([app/routers/auth.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/routers/auth.py))
  - `GET /api/v1/me`, `PATCH /api/v1/me/password` ([app/routers/me.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/routers/me.py))
  - `GET /api/v1/profile`, `PATCH /api/v1/profile` ([app/routers/profile.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/routers/profile.py))
  - `GET /api/v1/consents`, `POST /api/v1/consents` ([app/routers/consents.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/routers/consents.py))
- **Provider Interfaces:**
  - Base storage interface ([app/services/storage/base.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/services/storage/base.py)) with presigned URLs and envelope encryption support.
  - Base LLM client interface ([app/services/llm/base.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/services/llm/base.py)) for structured JSON generation and vision input.

### Verified Test Suite
Running `pytest` in `apps/api` validates 17 automated tests passing in 0.85s ([apps/api/tests/security/test_auth.py](file:///Users/inshrakhan/sih/stylesense/apps/api/tests/security/test_auth.py)):
- Registration success, weak password rejection, common password rejection, duplicate email prevention.
- Login authentication, wrong password handling, nonexistent user handling.
- Token security (unauthenticated rejection, invalid token rejection, expired token rejection, `me` endpoint verification, exclusion of password hashes).
- Security headers and request ID propagation.
- **IDOR Protection:** Cross-tenant access rejection (User A cannot view User B's profile).
- Health probes (`/healthz`, `/readyz`).

---

## 3. Implementation Status Matrix

| Component / Layer | Status | Key Deliverables & Notes |
|---|:---:|---|
| **Phase 0: Bootstrap** | **100% Complete** | Docker Compose, Makefile, logging, PII redaction, configs, health endpoints. |
| **Phase 1: Auth & Security** | **100% Complete** | Argon2id, JWT+Refresh rotation, security middleware, IDOR defenses, models. |
| **Phase 2: Secure Media** | **Pending** | Bucket storage, AES-256-GCM body encryption, EXIF scrub, face blur, video extraction. |
| **Phase 3: Wardrobe AI** | **Pending** | `rembg` cutouts, FashionCLIP embeddings, attribute cascade (local + Claude). |
| **Phase 4: Body Analysis** | **Pending** | Manual measurements (P0 rules) + MediaPipe landmark extraction (P1). |
| **Phase 5: Outfit Engine v1** | **Pending** | Skeletons, color harmony, body fit rules, MMR diversification, explanations. |
| **Phase 6: Catalog & Gaps** | **Pending** | Local catalog with pgvector ANN, deep links, counterfactual gap analysis. |
| **Phase 7: Learning System** | **Pending** | Event logs, Style DNA EMA, Logistic/LightGBM ranker, synthetic bootstrap. |
| **Phase 8: Frontend** | **Pending** | Next.js App Router, Tailwind, accessible components, full user journey. |
| **Phase 9: Seed & Demo** | **Pending** | `seed_demo.py` script for instant showcase with demo user & wardrobe. |
| **Phase 10: Hardening** | **Pending** | Bandit/gitleaks audits, docs (Threat Model, ML Card, Privacy), CI workflows. |

---

## 4. Next Phases: Detailed Roadmap & Deliverables

To complete the project according to [PLAN.md](file:///Users/inshrakhan/sih/stylesense/PLAN.md), the remaining phases must be executed in sequential vertical slices:

### Phase 2 — Secure Media Pipeline [P0]
1. **Storage Drivers (`app/services/storage/`):**
   - Implement `S3Storage` (MinIO/AWS S3) and `LocalFSStorage` implementing `StorageProvider`.
   - Structured object key naming: `u/{user_id}/{kind}/{uuid4}`.
2. **Media Ingestion & Validation (`app/services/media/validate.py`):**
   - Validate magic bytes (reject polyglots and disguised executables).
   - Enforce dimensions (≤ 6000px), size (≤ 10MB image, ≤ 100MB body video, ≤ 200MB wardrobe video).
   - Protect against decompression bombs via Pillow `MAX_IMAGE_PIXELS`.
3. **Sanitization & Privacy Processing (`app/services/media/sanitize.py`):**
   - Strip all EXIF / GPS metadata, correct orientation, generate standard web thumbnails.
   - For body media: Apply automatic face detection and face blurring.
   - Encrypt body media bytes with user-specific keys (`app/core/crypto.py`).
4. **Video Processing (`app/services/media/video.py`):**
   - ffmpeg frame extraction (~1 fps, max 30 frames).
   - Pose confidence scoring to select optimal frontal frames and take median ratios.
5. **API & Endpoints (`app/routers/media.py`):**
   - `POST /api/v1/media`: Streaming file upload returning `media_id` in `pending` status.
   - `GET /api/v1/media/{id}`: Poll status or obtain presigned download URLs (TTL ≤ 5 min).
   - `DELETE /api/v1/media/{id}`: Purge media and database record.
   - `DELETE /api/v1/me`: Complete purge of all user assets and encrypted data.

---

### Phase 3 — Wardrobe AI (Clothes Digitization) [P0]
1. **Garment Cutout:** Background removal via `rembg` on uploaded clothing photos, saving clean cutouts as derived assets.
2. **Vector Embeddings:** Compute fashion embeddings using FashionCLIP (`open_clip`) in [app/services/vision/embeddings.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/services/vision/embeddings.py) and store in `wardrobe_items.embedding`.
3. **Three-Stage Attribute Cascade:**
   - *Stage A (Local):* Zero-shot CLIP classification against `data/category_taxonomy.yaml` (category, pattern, neckline, sleeve, fit, occasion) + k-means dominant Lab color extraction.
   - *Stage B (Local Learned Head):* Logistic regression model on embeddings from accumulated user corrections.
   - *Stage C (Claude Vision):* Escalate low-confidence attributes to Claude Vision (only when `third_party_ai` consent is granted and `CLASSIFIER_PROVIDER != local`), validated against strict JSON schemas.
4. **Endpoints (`app/routers/wardrobe.py`):**
   - `POST /api/v1/wardrobe/items` (create from media asset).
   - `GET /api/v1/wardrobe/items` (filtered by category, color, formality, search).
   - `PATCH /api/v1/wardrobe/items/{id}` (logs user corrections to `item_label_corrections` for active learning).
   - `POST /api/v1/wardrobe/items/{id}/worn` (increments wear count).
   - `GET /api/v1/wardrobe/summary` (garment category statistics).

---

### Phase 4 — Body Analysis [P0 Manual, P1 Photo/Video]
1. **Manual Measurement Engine (P0):**
   - Process user inputs: shoulder, bust/chest, waist, hip, inseam, height.
   - Compute ratios: shoulder:hip, waist:hip, waist:shoulder, torso:leg.
   - Soft-rule classifier ([app/services/body/shape.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/services/body/shape.py)) evaluating canonical shapes against `data/body_rules.yaml` (Hourglass, Pear, Rectangle, Inverted Triangle, Apple).
   - Returns shape, confidence, runner-up, recommended silhouettes, and fit advice.
   - Store measurements encrypted (`body_profiles.measurements_enc`).
2. **Visual Pose & Landmark Pipeline (P1):**
   - MediaPipe Pose landmark extraction (shoulders, hips, knees, ankles) combined with person segmentation masks.
   - Automatic deletion of raw body photos/videos post-analysis by default.
3. **Endpoints (`app/routers/body.py`):**
   - `POST /api/v1/body/manual`: Input measurements.
   - `POST /api/v1/body/analyze`: Run visual analysis on uploaded media.
   - `GET /api/v1/body`: Retrieve shape styling guidance.
   - `PATCH /api/v1/body/correction`: Store user overrides (`user_corrected_shape`) for model calibration.

---

### Phase 5 — Outfit Engine v1 (Scored & Explainable) [P0]
1. **Garment Skeletons (`app/services/outfits/skeletons.py`):**
   - Define valid combinations: `top + bottom + shoes (+ layer) (+ bag)`, `dress + shoes`, and India-first `kurta/ethnic_set + bottom + dupatta + shoes`.
2. **Hard Constraints & Filtering:**
   - Availability check, occasion formality band compatibility, seasonal appropriateness, duplicate slot prevention.
3. **Multi-Factor Rule Scoring (`app/services/outfits/rules.py`):**
   - `body_fit` (silhouette harmony from body rules).
   - `color_harmony` ([app/services/outfits/color.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/services/outfits/color.py): complementary, analogous, monochromatic, neutral balancing in Lab/HCL color space).
   - `style_match` (user Style DNA match).
   - `occasion_match`, `season_match`, `layering_bonus`, `novelty` (penalize recently worn).
4. **Diversification & Variations:**
   - Top-N diversification via Maximal Marginal Relevance (MMR).
   - One-click variations: swap top, swap bottom, more formal, more casual, add one new catalog item.
5. **Grounded Explanations (`app/services/outfits/explain.py`):**
   - Template-based explanations highlighting top contributing score components ("Complements your pear silhouette", "Analogous earth tones").
6. **Endpoints (`app/routers/outfits.py`):**
   - `POST /api/v1/outfits/generate`, `POST /api/v1/outfits/{id}/variation`, `POST /api/v1/outfits/{id}/save`.

---

### Phase 6 — Catalog, Suggestions & Gap Analysis [P0 Local, P1 Live]
1. **Local Catalog Provider (`app/services/catalog/`):**
   - Seeded with ~200 diverse items (`catalog_seed.json`) in INR (₹) covering Indian and western styles.
   - Vector ANN search via `pgvector` indexed on catalog embeddings.
   - Non-scraping outbound deep-links to retailer searches (Myntra, Ajio, Amazon.in).
2. **Live Shopping Provider (P1):**
   - Permitted shopping API with 3-second timeout, rate limits, and automatic fallback to local catalog.
3. **Counterfactual Wardrobe Gap Analysis (`app/services/catalog/gaps.py`):**
   - Simulate virtual archetypes (e.g., "beige linen trousers", "white sneakers", "black kurta").
   - Compute how many new valid outfits are unlocked for the user's top occasions.
   - Rank gaps by utility: "Black trousers unlocks 4 college, 2 semi-formal outfits".
4. **Endpoints:** `GET /api/v1/gaps`, `GET /api/v1/suggestions`, `GET /api/v1/trends`, `POST /api/v1/wishlist`.

---

### Phase 7 — The Continuous Learning System (ML Core) [P0/P1]
1. **Event Ingestion:** Append-only logging of user interactions: `impression`, `like`, `dislike`, `save`, `skip`, `wear`, `buy_click` ([app/routers/outfits.py](file:///Users/inshrakhan/sih/stylesense/apps/api/app/routers/outfits.py)).
2. **Online Personalization (Style DNA):**
   - Instant EMA updates on `user_style_state.style_vector`:
     $$\text{style\_vector} \leftarrow (1-\eta)\cdot\text{style\_vector} + \eta\cdot\text{sign}\cdot\text{mean}(\text{item\_embeddings})$$
   - Real-time updates to style tag affinities (minimal, streetwear, ethnic, etc.).
3. **Learned Ranker:**
   - Cold start: Blended score $\alpha \cdot \text{rule\_score} + (1-\alpha) \cdot \text{model\_score}$.
   - Small event volume: Scikit-learn Logistic Regression.
   - Large event volume: LightGBM LambdaRank with Inverse Propensity Scoring (IPS) to eliminate position bias.
4. **Model Registry & Retraining (`train.py`, `evaluate.py`):**
   - Champion/Challenger evaluation on holdout NDCG@5 and per-body-shape slice metrics.
   - Promotion gating: Regressions on demographic/shape slices prevent deployment.
   - Synthetic bootstrap script (`scripts/bootstrap_synthetic.py`) using LLM-as-judge offline ratings.

---

### Phase 8 — Frontend Web Application [P0]
1. **Tech Stack:** Next.js (App Router), TypeScript strict mode, Tailwind CSS, shadcn/ui, TanStack Query.
2. **Client Architecture:** Strongly typed API client generated from FastAPI OpenAPI specification.
3. **Screens & Flows:**
   - Landing, Registration & Login.
   - Granular Consent Modal (body media, third-party AI, analytics).
   - Style Profile Stepper (occasions, colors, budget in ₹).
   - Body Analysis Screen (interactive silhouette adjustment & manual measurement entry).
   - Wardrobe Gallery (drag-and-drop photo/video uploads, category filters, review badges).
   - Outfit Recommendation Canvas (outfit cards, "Why this works", interactive like/dislike/save, variation toggles).
   - Wardrobe Gaps & Shop Hub (visual gap unlock counter, deep-link product cards).
   - Style DNA Dashboard (visual affinity bars).
   - Privacy & Account Center (export data zip, delete body media, delete account).

---

### Phase 9 — Seed & Demo Data [P0]
- Execute `scripts/seed_demo.py` creating:
  - Demo user (`demo@stylesense.ai`).
  - Pre-analyzed Pear shape body profile.
  - 25-item curated wardrobe with placeholder cutouts and vectors.
  - 200 catalog products and current fashion trends.
  - 50 pre-seeded user interactions ensuring Style DNA is visibly trained on first run.
- Single command execution: `make demo`.

---

### Phase 10 — Hardening, Compliance & Release [P0]
- Security scans: Bandit, pip-audit, npm audit, gitleaks validation.
- Resilience checks: Circuit breakers on LLM and external search APIs.
- Documentation completion:
  - `docs/THREAT_MODEL.md` (STRIDE-lite model).
  - `docs/PRIVACY.md` (data retention and encryption policies).
  - `docs/ML_CARD.md` (model limitations, fairness across skin tones, lighting, and body shapes).
  - `docs/API.md` (OpenAPI reference).

---

## 5. Immediate Next Steps for Implementation

1. **Implement Phase 2 Storage Service:** Create `app/services/storage/s3.py` (MinIO/S3) and `app/services/storage/localfs.py` implementing `StorageProvider`.
2. **Implement Media Validation & Upload Router:** Build `app/services/media/validate.py`, `app/services/media/sanitize.py`, and `app/routers/media.py` for streamed image/video ingestion.
3. **Set Up Background Worker:** Configure Arq worker tasks in `app/workers/tasks.py` for asynchronous media sanitization, thumbnail generation, and face blurring.
4. **Maintain Progress Checklists:** Keep [docs/PROGRESS.md](file:///Users/inshrakhan/sih/stylesense/docs/PROGRESS.md) and [docs/DECISIONS.md](file:///Users/inshrakhan/sih/stylesense/docs/DECISIONS.md) updated as each vertical slice is completed.

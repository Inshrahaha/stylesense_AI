# StyleSenseAI — End-to-End Build Plan (for Claude Code)

> **How to use this file:** Put it in the repo root as `PLAN.md` (next to `CLAUDE.md`). Execute phase by phase, in order. Each phase has **Deliverables** and **Acceptance criteria**; do not move on until the acceptance criteria pass. Commit at the end of every phase. Priorities: **[P0]** must ship, **[P1]** ship if time allows, **[P2]** stub the interface only.
>
> Time budget: ~2 days with heavy AI assistance. Day 1 = Phases 0–7 (backend, DB, media, ML). Day 2 = Phases 8–10 (frontend, learning loop polish, hardening). If time runs short, cut P1/P2 items, never the security items.

---

## 0. Product in one paragraph

StyleSenseAI takes a user's style preferences and body proportions, digitizes their wardrobe from photos/video, generates outfits from what they already own (scored for body proportions, occasion, color, style, trend), explains each recommendation, finds **wardrobe gaps** (items that would unlock the most new outfits), and suggests matching products from the web — or from a **local simulated catalog** when live web search is unavailable. The recommender **learns from user feedback** (likes, dislikes, saves, wears) and improves over time.

Source PRD: `StyleSenseAI_Product_Requirements.docx` (FR-01…FR-17, MVP scope §26).

## 1. Fixed decisions (do not re-ask; change only with a note in `docs/DECISIONS.md`)

| Area | Decision |
|---|---|
| Backend | Python 3.11+, **FastAPI**, SQLAlchemy 2 + Alembic, Pydantic v2 |
| DB | **PostgreSQL + pgvector** (embeddings, ANN search) |
| Jobs | **Arq** (Redis) for background work; `JOBS_EAGER=true` runs inline in tests/dev |
| Object storage | **S3 API**. Local dev = **MinIO** in docker-compose. Also a `LocalFSStorage` driver for tests. Buckets are **private**. |
| Frontend | **Next.js (App Router) + TypeScript + Tailwind + shadcn/ui + TanStack Query**, mobile-first |
| Auth | Email+password, **argon2id**, short-lived JWT access token + rotating refresh token (httpOnly cookie) |
| ML libs | PyTorch (CPU), `open_clip` (FashionCLIP / similar fashion CLIP weights), MediaPipe (pose + segmentation + face detection), `rembg` (cutouts), scikit-learn + LightGBM (ranker), Pillow, ffmpeg |
| LLM | Anthropic Claude via a thin `LLMClient` interface (vision + structured JSON output). Model name from env `ANTHROPIC_MODEL`. Always has a `mock` implementation. |
| Infra | `docker compose up` brings up api, worker, postgres, redis, minio, (optional) clamav; web runs via `npm run dev` or compose |
| Currency/locale | INR (₹) default; India-relevant categories (kurta, saree, dupatta, ethnic wear) are first-class |

**Provider pattern everywhere.** Every external dependency sits behind an interface with a working offline implementation, selected by env var. The whole app must run end-to-end with **zero API keys** and **no internet** (after dependencies/models are installed):

```
LLM_PROVIDER=claude|mock
CLASSIFIER_PROVIDER=local|claude|auto      # auto = local first, escalate low-confidence to claude
EMBEDDING_PROVIDER=fashionclip|mock        # mock = deterministic hash vectors (CI)
SUGGESTION_PROVIDER=local|live|auto        # auto = try live (3s timeout) → fall back to local
STORAGE_PROVIDER=s3|localfs
JOBS_EAGER=true|false
```

## 2. Repository layout

```
stylesense/
  CLAUDE.md  PLAN.md  README.md  docker-compose.yml  .env.example  Makefile
  docs/        DECISIONS.md  THREAT_MODEL.md  PRIVACY.md  ML_CARD.md  API.md
  apps/
    api/
      app/
        main.py  config.py  deps.py
        core/        security.py  crypto.py  rate_limit.py  logging.py  audit.py
        db/          models/  session.py  migrations/ (alembic)
        routers/     auth.py profile.py body.py media.py wardrobe.py outfits.py
                     gaps.py suggestions.py wishlist.py trends.py me.py admin.py
        services/
          storage/       base.py s3.py localfs.py
          media/         validate.py sanitize.py video.py scan.py
          llm/           base.py claude.py mock.py
          vision/        embeddings.py zero_shot.py cutout.py attributes.py
          body/          pose.py measure.py shape.py
          outfits/       skeletons.py rules.py color.py features.py generator.py variations.py explain.py
          learning/      events.py style_dna.py ranker.py bandit.py train.py evaluate.py registry.py synthetic.py
          catalog/       providers/{base,local,live}.py index.py gaps.py seed.py
          trends/        service.py
        workers/     tasks.py (arq)
      tests/         unit/ integration/ security/ ml/
      data/          catalog_seed.json  trends_seed.json  body_rules.yaml  color_rules.yaml  category_taxonomy.yaml
      scripts/       seed_demo.py  train_ranker.py  bootstrap_synthetic.py  eval_ranker.py
    web/             (Next.js app)
```

## 3. Data model (Alembic migrations; UUID PKs; `created_at/updated_at` everywhere)

- `users` (email citext unique, password_hash, is_active, deleted_at)
- `refresh_tokens` (user_id, **token_hash**, family_id, expires_at, revoked_at, replaced_by, ua_hash, ip_hash)
- `consents` (user_id, kind ∈ `body_media | third_party_ai | analytics`, granted, version, at)
- `profiles` (user_id PK, name, age_range, height_cm, preferred_categories[], fav_colors[], styles[], budget_min/max, occasions[], region, currency)
- `body_profiles` (user_id, **measurements_enc** bytea, shape, shape_confidence, ratios jsonb, source ∈ manual|photo|video, user_corrected_shape, model_version)
- `media_assets` (user_id, kind ∈ body_image|body_video|wardrobe_image|wardrobe_video|derived, bucket, object_key (random uuid), sha256, mime, bytes, width, height, duration_s, encrypted bool, status ∈ pending|processing|ready|rejected, reject_reason, deleted_at)
- `wardrobe_items` (user_id, asset_id, cutout_asset_id, name, category, subcategory, colors jsonb[{name,hex,share}], pattern, material, sleeve, neckline, fit, length, style_tags[], occasions[], seasons[], formality 0–4, **embedding vector(D)**, attrs_confidence jsonb, attrs_source ∈ ml|llm|user, is_available, wear_count, last_worn_at)
- `item_label_corrections` (item_id, field, predicted, corrected) ← **training data for attribute head**
- `outfits` (user_id, occasion, context jsonb, score_rules, score_model, score_final, ranker_version_id, policy ∈ exploit|explore|rules, propensity, features jsonb, explanation jsonb, saved bool)
- `outfit_items` (outfit_id, slot ∈ top|bottom|dress|layer|shoes|bag|accessory|ethnic_set, wardrobe_item_id NULL, product_id NULL)
- `outfit_events` (user_id, outfit_id, type ∈ impression|like|dislike|save|skip|wear|variation|buy_click, position, policy, propensity, ts) ← **append-only learning log**
- `user_style_state` (user_id, style_dna jsonb, style_vector vector(D), n_events)
- `catalog_products` (source, external_id, title, brand, category, colors, pattern, fit, style_tags[], occasions[], formality, price, currency, image_url, product_url, in_stock, **embedding vector(D)**, trend_tags[])
- `wishlist_items` (user_id, product_id NULL, outfit_id NULL)
- `trends` (name, score 0–100, tags[], embedding, valid_from, valid_to)
- `model_versions` (kind ∈ ranker|attr_head|body_shape, version, artifact_key, metrics jsonb, status ∈ shadow|champion|retired, n_train, trained_at)
- `audit_log` (user_id, action, ip_hash, meta jsonb, ts)

Indexes: HNSW/IVFFlat on embeddings; `(user_id, …)` on every user-owned table; `outfit_events(user_id, ts)`.

---

## PHASE 0 — Bootstrap  [P0]

**Deliverables:** repo skeleton per §2; `docker-compose.yml` (api, worker, postgres+pgvector, redis, minio, optional clamav profile); `.env.example` (no real secrets); `Makefile` (`make up|down|migrate|seed|test|lint|fmt`); pre-commit (ruff, black, mypy, **gitleaks**, **bandit**); GitHub Actions CI (lint, tests, `pip-audit`, `npm audit`); `/healthz` and `/readyz`; structured JSON logging with request IDs and **PII redaction**; `docs/DECISIONS.md`.

**Acceptance:** `make up && make migrate && curl localhost:8000/healthz` returns OK; CI config valid; `make test` runs (even if empty).

## PHASE 1 — Auth & security baseline  [P0]

**Deliverables**
- Registration/login/logout/refresh/`me`. Password: **argon2id**, min length 10, check against a small common-password list. Constant-time compare, generic error messages (no user enumeration).
- Access token JWT (15 min, `HS256` or `EdDSA`, secret from env, `kid` for rotation). **Refresh token**: random 256-bit, stored **hashed**, httpOnly + Secure + SameSite=Strict cookie, **rotation with reuse detection** (reuse ⇒ revoke the whole `family_id`).
- Rate limiting (Redis): per-IP and per-account on auth endpoints (e.g., 5/min login, exponential backoff + temporary lockout), and per-user on upload and LLM-backed endpoints.
- Security middleware: strict CORS allow-list, security headers (CSP, HSTS, X-Content-Type-Options, Referrer-Policy, frame-ancestors none), request-size limits, trusted hosts, CSRF protection for cookie-authenticated endpoints (custom header + SameSite).
- **Authorization:** one `get_current_user` dependency; every repository/query function takes `user_id` and filters on it. No endpoint accepts a bare object id without an ownership check. Admin routes behind a role.
- Consent model + endpoints. Audit log for login, logout, password change, data export, deletion.
- `docs/THREAT_MODEL.md` (STRIDE-lite: assets = body media, wardrobe media, PII; threats = IDOR, upload abuse, token theft, prompt injection, LLM cost abuse, data leakage to 3rd parties; mitigations map to tests).

**Acceptance (automated tests in `tests/security/`):** login brute-force gets throttled; refresh-token reuse revokes family; user A cannot read/modify/delete any of user B's profile/items/outfits/media (**IDOR suite over every router**); responses never include `password_hash`; security headers present; JWT with bad signature/expired/`alg=none` rejected.

## PHASE 2 — Secure media pipeline (photos + video)  [P0]

**Storage**
- Private bucket(s); object keys = `u/{user_id}/{kind}/{uuid4}` (never user-supplied names). Server-side encryption enabled (MinIO SSE / S3 SSE-KMS).
- **Application-level envelope encryption for `body_image`/`body_video`/body-derived assets** (AES-256-GCM, per-user data key wrapped by a master key from env/KMS; `core/crypto.py`). Wardrobe images use SSE only.
- Delivery: wardrobe/thumbnails via **presigned GET (TTL ≤ 5 min)**; body media only through an authenticated API stream that decrypts, with `Cache-Control: no-store`. **[P2]** presigned direct-to-storage upload (conditions on size/type) as an optimization.

**Upload endpoint (`POST /media`)** — streamed, size-capped, per-user quota & rate limit:
- Limits (configurable): image ≤ 10 MB and ≤ 6000 px/side; body video ≤ 60 s / 100 MB; wardrobe video ≤ 120 s / 200 MB; allowed MIME: jpeg/png/webp/heic (convert), mp4/mov/webm.
- Validate by **magic bytes** (not the extension or declared Content-Type); reject polyglots; Pillow `MAX_IMAGE_PIXELS` guard against decompression bombs; `ffprobe` validation for video (codec, duration, resolution).
- **Sanitize:** re-encode every image (strips EXIF/GPS/metadata), fix orientation, generate thumbnail; re-mux/transcode video to a safe profile with metadata stripped.
- Optional ClamAV scan (compose profile `scan`); if enabled, files stay `pending` until clean.
- **Face privacy:** for body media, detect and **blur the face by default** before storage (user can opt out). **Privacy-by-design default: after pose/landmark extraction, delete the raw body image/video and keep only derived measurements** unless the user opts in to keep it.
- State machine `pending → processing → ready | rejected`, processed by Arq worker; client polls `GET /media/{id}` or uses SSE.

**Video processing (worker)**
- Extract frames (≈1 fps, max 30) with ffmpeg. Body video: score frames by pose confidence/frontal-ness, use the best N frames and **take the median of ratios** (more robust than a single photo). Wardrobe video: extract frames → detect garments → de-duplicate with embedding similarity → produce *candidate items for the user to confirm*.

**Deletion:** `DELETE /media/{id}` removes the object + derived assets + DB row (soft-delete then purge job). `DELETE /me` purges **all** objects, DB rows, vectors, events, and revokes tokens; export via `GET /me/export` (JSON + signed zip of media).

**Acceptance:** tests upload: valid jpeg/png/mp4 ✔; renamed `.exe` ✘; image with GPS EXIF comes out with no EXIF; 50k×50k PNG bomb ✘; oversize ✘; user B cannot fetch user A's asset (even with the URL); `DELETE /me` leaves zero objects under `u/{user_id}/`; body asset bytes in the bucket are not a valid image (i.e., encrypted).

## PHASE 3 — Wardrobe AI (digitize clothes)  [P0]

**Pipeline per wardrobe image (worker):**
1. Cutout with `rembg` → store cutout as derived asset (nice UI, cleaner embeddings).
2. **Embedding** with fashion-CLIP (`services/vision/embeddings.py`, `vector(D)`).
3. **Attribute cascade (cost-efficient ML):**
   - *Stage A — local:* zero-shot CLIP text-prompt classification against `category_taxonomy.yaml` (categories, patterns, sleeves, necklines, fits, lengths, occasions, seasons) + dominant-color extraction (k-means in Lab → named colors with hex + share). Each attribute gets a **confidence**.
   - *Stage B — local learned head:* per-attribute logistic regression on the embedding, trained from `item_label_corrections` + LLM labels (loaded if a champion `attr_head` exists; otherwise skipped).
   - *Stage C — Claude vision (only for attributes below threshold, and only if `third_party_ai` consent is granted and `CLASSIFIER_PROVIDER` ≠ local):* send the **cutout** (not the raw photo) with a strict JSON schema; validate output against the taxonomy enum (reject anything off-schema; treat model output as untrusted). Cache by image `sha256`.
4. Persist attributes with `attrs_source` and `attrs_confidence`. Items with low confidence get `needs_review=true` in the UI.
5. Infer `formality` (0 lounge … 4 formal) and default `occasions`/`seasons` from category + attributes via `category_taxonomy.yaml` rules.

**API:** `POST /wardrobe/items` (from media id) → 202 + item id; `GET /wardrobe/items` (filters: category, color, occasion, search, availability; pagination); `GET/PATCH/DELETE /wardrobe/items/{id}`; `POST /wardrobe/items/{id}/worn`; `POST /wardrobe/video/{media_id}/candidates` → confirm flow; `GET /wardrobe/summary` (counts per category).
**Learning hook:** every `PATCH` that changes an ML-predicted field writes `item_label_corrections`.

**Acceptance:** with `CLASSIFIER_PROVIDER=local` and `EMBEDDING_PROVIDER=mock` the full flow works offline; with real FashionCLIP, a held-out set of ~30 demo images (in `tests/ml/fixtures`) reaches a documented accuracy in `docs/ML_CARD.md`; off-schema LLM output is rejected (test with a fake adversarial response, including an injected instruction inside the image text); corrections are logged.

## PHASE 4 — Body analysis  [P0 manual path, P1 photo/video path]

**Manual path (P0):** user enters shoulder, bust/chest, waist, hip (cm) + height + inseam/leg length (optional). `shape.py` computes ratios (shoulder:hip, waist:hip, waist:shoulder, torso:leg) and classifies with **soft rules from `body_rules.yaml`** (Hourglass, Pear, Rectangle, Inverted Triangle, Apple) returning shape + confidence + runner-up. Measurements encrypted at rest (`measurements_enc`).

**Photo/video path (P1):** MediaPipe Pose → landmarks (shoulders, hips, knees, ankles) + person segmentation mask → measure silhouette widths at shoulder/waist/hip rows → convert to ratios (use the user's height for scale; ratios are scale-free). Require a full-body, front-facing, well-lit frame; return clear user-facing errors ("full body not visible"). Fuse with manual numbers if present (manual wins). Always show the result as **editable styling guidance**, not a judgment (PRD §7); log user shape corrections (`user_corrected_shape`) for later calibration.

**Output contract (matches PRD §7):** `{shape, confidence, ratios, recommended_silhouettes[], suggested_fits[], styles_to_try[], notes}` generated from `body_rules.yaml` (deterministic; LLM not required). Language must be neutral and body-positive; no attractiveness claims; no weight/BMI output.

**Acceptance:** unit tests for each shape on canonical measurement sets; boundary cases return lower confidence and a runner-up; photo path returns a validation error on cropped/side/multi-person images; raw body media deleted after analysis unless the user opted to keep it; ML card documents known limits (clothing, pose, camera angle).

## PHASE 5 — Outfit engine v1 (rules, explainable)  [P0]

Implements PRD §10, §11, §15, §16, §24 as a **candidate generator + scorer** so the ML ranker (Phase 7) can plug in later.

1. **Skeletons** (`skeletons.py`): `top+bottom+shoes(+layer)(+bag)`, `dress+shoes(+layer)(+bag)`, `kurta/ethnic_set+bottom+dupatta?+shoes`. Slot rules in YAML.
2. **Hard filters:** item available; formality within the occasion's range (`occasion → formality band`); season/weather tag match; no duplicates.
3. **Rule score** components (each 0–1, each logged for explanations and as ML features): `body_fit` (silhouette/fit/length/rise vs `body_rules.yaml`), `color_harmony` (neutrals, analogous, complementary, ≤3 dominant colors, pattern clash penalty — `color.py` in Lab/HCL space), `style_match` (profile styles + Style DNA vs item `style_tags`), `occasion_match`, `season_match`, `layering` bonus, `trend`, `novelty` (penalize recently worn/recently shown), `budget` (for new items).
   `rule_score = Σ wᵢ·componentᵢ` with weights in config (PRD §24).
4. **Diversification** (MMR or greedy: don't show three outfits that differ by one sock) → top-N.
5. **Variations** (`variations.py`, PRD §16): change top / change bottom / more casual / trendier / more traditional / budget-friendly / **use only my wardrobe** / **add one new item** — implemented as constraint or weight changes + re-rank (deterministic).
6. **Add-one-new-item:** when the wardrobe cannot produce ≥ N good outfits for an occasion, call the suggestion engine (Phase 6) for the best slot to fill and return outfits mixing owned + catalog items (`outfit_items.product_id`).
7. **Explanations** (`explain.py`): reasons built from the **top contributing features** (rule components now; model contributions later). Template text first; optional LLM polish that may only rephrase the provided facts (grounded; if the LLM output mentions anything not in the facts, discard it and use the template).

**API:** `POST /outfits/generate {occasion[], style_overrides?, use_only_wardrobe?, add_new_item?, n}`; `POST /outfits/{id}/variation {type}`; `POST /outfits/{id}/events {type}`; `POST /outfits/{id}/save`; `GET /outfits/saved`.

**Acceptance:** for the demo user (pear shape, 25-item wardrobe) "College + Casual" returns ≥3 distinct valid outfits in < 1 s (candidate generation capped, e.g., 5k combos pre-filtered); every outfit has ≥3 factual reasons; "use only wardrobe" never returns catalog items; property tests: no outfit has two bottoms, no formal shoes with lounge wear; deterministic given a seed.

## PHASE 6 — Catalog, web suggestion engine, gap analysis  [P0 local, P1 live]

**Provider interface** (`catalog/providers/base.py`):
```python
class ProductProvider(Protocol):
    async def search(self, spec: ItemSpec, budget: Budget | None, limit: int) -> list[Product]: ...
```
- **`LocalCatalogProvider` (P0):** seeded `catalog_seed.json` (generate ~200 realistic items in ₹ covering all taxonomy categories, Indian + western; fields per `catalog_products`). Embeddings computed at seed time. Retrieval = **pgvector ANN** on (text embedding of `ItemSpec` or image embedding of a wardrobe item) → filter (budget, category, size, color) → re-rank by `similarity × wardrobe_compat × (1+learned affinity)`. `product_url` = **deep link to a retailer search page** built from the title (Myntra/Ajio/Amazon.in) — works, and involves no scraping. Placeholder images generated for seeds.
- **`LiveSearchProvider` (P1):** a licensed shopping-search API (e.g., SerpAPI/Serper-type or a retailer/affiliate API — configurable base URL & key). **Do not scrape retailer sites.** Normalize results to `Product`; cache for 24 h; per-user rate limit and cost cap.
- **`auto`:** try live with a 3 s timeout, circuit breaker; on failure/no key → local. Always return `source` ∈ `local|live` so the UI can label it honestly ("Demo catalog" vs "Live results").
- **Similar-to-item:** `GET /suggestions/similar?item_id=` → products visually/semantically similar to a wardrobe item.

**Gap analysis (PRD §13–14) — counterfactual, reuses the Phase 5 engine:**
1. Define *archetypes* (e.g., "neutral straight-fit trousers", "lightweight overshirt", "white sneakers", "black kurta set") from `category_taxonomy.yaml`.
2. For each archetype, temporarily add a **virtual item** to the user's wardrobe, run the generator for the user's top occasions, and count the **new valid outfits** (score ≥ threshold) it creates, by occasion.
3. Rank archetypes by `new_outfits × suitability` (body fit, style, budget). Return "Black straight-fit trousers — creates 4 college, 2 casual, 2 semi-formal outfits" + products from the provider.

**Trends (P1):** `trends_seed.json` (name, score, tags, embedding) + `trend_suitability = f(cos(trend, style_vector), body_fit, #wardrobe pairings)`. Refresh job is a pluggable interface (P2 for real sources; permitted sources only).

**API:** `GET /gaps`, `GET /suggestions?occasion=&slot=&budget=`, `GET /suggestions/similar`, `GET /trends`, `POST /wishlist`, `GET /wishlist`, `DELETE /wishlist/{id}`.

**Acceptance:** with no keys/network, `/suggestions` returns ranked local products with budget respected and honest `source:"local"`; killing the live provider (timeout) falls back in < 4 s; gap analysis on the demo wardrobe returns ≥3 archetypes with outfit counts that reproduce when run twice; counts are verified by an independent brute-force test on a tiny wardrobe.

## PHASE 7 — The learning system (this is the ML core)  [P0 simple loop, P1 full]

Goal: recommendations measurably improve with feedback, safely, with offline evaluation and rollback.

**7.1 Event logging (P0).** Every outfit shown logs `impression` (position, policy, propensity, ranker version). User actions log `like|dislike|save|skip|wear|variation|buy_click`. Append-only. Wear events also update `wear_count/last_worn_at`.

**7.2 Online personalization (P0) — Style DNA.** On each event, update `user_style_state` with an exponential moving average:
`style_vector ← (1−η)·style_vector + η·sign·mean(item_embeddings)` and tag-affinity counters (minimal, streetwear, traditional, …). Positive: like(+1), save(+1.5), wear(+2). Negative: dislike(−1), skip(−0.3). `style_dna` is the normalized tag affinities shown in the UI (PRD §18). It feeds `style_match` and the ranker immediately — no retraining needed for the first visible learning.

**7.3 Learned ranker (P0 baseline, P1 LightGBM).**
- Features per (user, request, candidate outfit): all rule components, `cos(style_vector, outfit_embedding)`, outfit-level color stats, #items, has_layer, contains_new_item, wear recency, user aggregates (n_events, like-rate), body-shape one-hot, occasion one-hot.
- Labels: positive = like/save/wear (wear strongest), negative = dislike/skip, impression-without-action = weak negative; **inverse-propensity weights** from logged propensities to reduce position/exploration bias.
- Models: **logistic regression** (scikit-learn) when events < ~300; **LightGBM LambdaRank grouped by request** when more. Global model with user features (works for new users) + optional per-user bias term.
- **Cold start:** `final = α·rule_score + (1−α)·model_score`, with `α = max(0.2, 1 − n_events/N0)`; brand-new users get the pure rule score.
- **Synthetic bootstrap (`synthetic.py`):** generate several thousand synthetic (wardrobe, body shape, occasion) cases → candidates via the engine → have the **LLM act as a "stylist judge"** (structured 1–5 ratings + short reason, batched, cached; in `mock` mode use rule score + noise) → train `ranker v0` with these weighted low (e.g., 0.3×). Real feedback gradually dominates. Mark synthetic provenance in `model_versions.metrics`.

**7.4 Exploration (P0 simple).** Of every N outfits shown, reserve 1 slot for **epsilon-greedy / Thompson-sampling exploration** (ε decays with user events); log `policy=explore` and its propensity. Never explore into hard-filter violations.

**7.5 Retraining & model registry (P1).** `train.py` + Arq cron (nightly) and on-threshold trigger (every +K new events): build dataset from `outfit_events`, time-based train/validation split, train challenger, evaluate **NDCG@5, AUC, and per-body-shape slice metrics**, store artifact in object storage + `model_versions` row. **Champion/challenger:** promote only if the challenger beats the champion on holdout NDCG@5 by a margin and no slice regresses > tolerance; otherwise keep it as `shadow` (still scored and logged, not served). One-command rollback (`admin` endpoint/script). Same machinery trains the **attribute head** (from `item_label_corrections` + LLM labels).

**7.6 Explainability.** For LightGBM use feature contributions (e.g., TreeSHAP via `pred_contrib`) → top-3 positive contributions rendered as reasons ("matches the minimal looks you've liked"). Fall back to rule-component reasons.

**7.7 Admin/metrics (P1).** `GET /admin/ml/metrics`: events/day, like-rate, save-rate, acceptance@3, NDCG over time, model versions, drift (feature means vs training). Implements PRD §27 recommendation-quality metrics.

**Acceptance:** `scripts/bootstrap_synthetic.py && scripts/train_ranker.py && scripts/eval_ranker.py` run offline in mock mode and print metrics; **simulation test** (`tests/ml/test_learning_curve.py`): a simulated user with a hidden preference (e.g., likes minimal neutrals, dislikes loud patterns) gives feedback over 200 rounds → like-rate in rounds 150–200 is significantly higher than rounds 0–50 and the ranker beats the rule-only baseline on held-out NDCG@5; challenger-gating test (a deliberately bad challenger is **not** promoted); Style DNA shifts toward the simulated preference within ~20 events; exploration slot never violates hard filters.

---

## PHASE 8 — Frontend  [P0]

Mobile-first, accessible (WCAG AA), friendly to users with no fashion knowledge (PRD §21). Typed API client generated from the OpenAPI schema.

**Screens:** Landing → Register/Login → **Consent** (separate toggles: body media, third-party AI, analytics; clear plain-language text) → **Style profile** (stepper) → **Body** (manual measurements; optional photo/video capture via `getUserMedia`/`MediaRecorder` with live guidance overlay "stand back, full body visible") with result card (shape, ratios, recommended silhouettes) and **"Not right? Adjust"** → **Wardrobe** (grid, filters, search, upload photo/video, processing state, review-needed badges, edit/delete, mark worn/unavailable, category counts) → **Create outfits** (occasion chips + "only my wardrobe / add one new item", outfit cards with item thumbnails, **"Why this works"**, 👍/👎, save, variations menu) → **Gaps & Shop** (gap cards with "unlocks N outfits", product cards with price, source badge **Demo catalog / Live**, wishlist, outbound link) → **Trends** → **Saved looks & wishlist** → **Style DNA** (bars) → **Settings/Privacy** (export data, delete media, delete account, consent management).

**Rules:** no tokens in `localStorage` (access token in memory; refresh via httpOnly cookie); sanitize all rendered text (no `dangerouslySetInnerHTML`); CSP-compatible; skeleton loaders; optimistic UI for like/save; offline-friendly error states (AI/search failures degrade gracefully with the local fallback and a clear label).

**Acceptance:** Playwright smoke test of the full journey (register → consent → profile → body → upload 5 wardrobe images → generate "College + Casual" → like/save → view gaps → see products → delete account); Lighthouse a11y ≥ 90 on main screens; no secrets/tokens in storage.

## PHASE 9 — Seed & demo data  [P0]

`scripts/seed_demo.py` creates: demo user, profile, body profile (pear), a 25-item wardrobe (generated cutout-style placeholder images + attributes + embeddings), 200-product catalog, trends, and ~50 synthetic feedback events so Style DNA and the ranker show learning on first load. Idempotent. A `make demo` target runs migrate → seed → bootstrap ranker.

## PHASE 10 — Hardening, docs, release readiness  [P0]

- **Security review pass:** run bandit, pip-audit, npm audit, gitleaks; fix highs; confirm no secrets in repo/images; non-root containers; minimal images; MinIO/DB/Redis not exposed publicly in prod compose; `.env.example` only.
- **LLM safety:** prompt-injection tests (image with embedded text instructions, product titles with instructions); outputs validated against schemas/enums; per-user daily LLM budget and global kill-switch (`LLM_PROVIDER=mock`).
- **Resilience:** timeouts + retries + circuit breakers on LLM/live search; worker failures put media in `rejected` with a user-readable reason; graceful degradation verified by tests with providers killed.
- **Privacy:** `docs/PRIVACY.md` (what is stored, where, retention, third-party processing, how to delete); verified delete/export flows.
- **Docs:** `README.md` quickstart (≤5 commands), `docs/API.md` (from OpenAPI), `docs/ML_CARD.md` (data, models, metrics, limitations, bias/fairness notes — body-shape estimation caveats, skin-tone/lighting effects on color detection, cultural coverage), `docs/THREAT_MODEL.md` updated.
- **Final:** full test suite green; `make demo` works from a clean clone.

---

## 11. Security requirements summary (checklist — every item needs a test or a doc reference)

- [ ] argon2id passwords; no user enumeration; login/refresh rate limits + lockout
- [ ] Short-lived JWT; refresh rotation with reuse detection; httpOnly+Secure+SameSite cookies; CSRF defense
- [ ] Ownership check on every query (IDOR suite covers all routers)
- [ ] Uploads: magic-byte validation, size/dimension/duration limits, bomb protection, re-encode, EXIF stripped, optional AV scan
- [ ] Private buckets, random keys, SSE at rest, **envelope encryption for body media**, presigned URLs ≤ 5 min, body media never via public URL
- [ ] Face blur + raw-body-media deletion by default
- [ ] Field-level encryption for body measurements
- [ ] Consent gates for body media, third-party AI, analytics; only **cutouts of wardrobe items** (never body media) may go to an external LLM, and only with consent
- [ ] All external/LLM output treated as untrusted & schema-validated
- [ ] Secrets only from env/secret manager; gitleaks in pre-commit and CI; dependency audits in CI
- [ ] Security headers, strict CORS, request size limits, trusted hosts
- [ ] Audit log; PII-redacted logs; IP/UA stored hashed
- [ ] Data export + full account/media deletion with purge job
- [ ] Per-user quotas and LLM/search cost caps

## 12. ML requirements summary

| Component | Method | Learns from |
|---|---|---|
| Wardrobe embeddings | Fashion-CLIP image embeddings | pretrained |
| Attribute tagging | Zero-shot CLIP → learned head → Claude vision (cascade by confidence) | user corrections + LLM labels |
| Body proportions | MediaPipe pose + segmentation → ratios → soft-rule shape classifier (+confidence) | user shape corrections (calibration) |
| Outfit ranking | Rule score blended with logistic regression → LightGBM LambdaRank, IPS-weighted | likes/saves/wears/dislikes/skips |
| Personalization | Style-vector EMA + tag affinities (Style DNA) | every event, instantly |
| Exploration | ε-greedy / Thompson sampling slot with logged propensity | — |
| Cold start | LLM-as-stylist-judge synthetic labels (low weight) | synthetic data |
| Product retrieval | pgvector ANN on text/image embeddings + learned re-rank | clicks/saves/wishlist |
| Gap analysis | Counterfactual outfit counting via the generator | — |
| Safety of learning | Champion/challenger, holdout NDCG@5, slice metrics, rollback | — |

## 13. Definition of done

1. `git clone` → `make demo` → full journey works with **no API keys**.
2. With an Anthropic key and live-search key set, classification escalation and live suggestions work, with automatic fallback when they fail.
3. All acceptance criteria above pass in CI; the security checklist is complete.
4. Learning-curve simulation shows improvement; model registry shows champion/challenger metrics.
5. README, ML card, privacy doc, and threat model are written.

## 14. Out of scope (stub interfaces only)

Virtual try-on, chatbot assistant, weather/calendar planning, retailer partnerships, social sharing, smart mirror, resale — keep the architecture ready (events, embeddings, providers) but don't build them.

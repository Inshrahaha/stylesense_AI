# CLAUDE.md — StyleSenseAI working rules

Read `PLAN.md` first. It is the single source of truth for scope, architecture, data model, phases and acceptance criteria. If something is ambiguous, pick the most reasonable option, record it in `docs/DECISIONS.md`, and continue — do not stop to ask unless an action is destructive or irreversible.

## How to work
- Execute `PLAN.md` phase by phase, in order. Finish a phase's acceptance criteria (tests passing) before starting the next. Commit after each phase with a clear message.
- Build in **vertical slices** (model → service → router → test), not layer by layer.
- Keep a running checklist in `docs/PROGRESS.md` (phase, status, what's left, known issues).
- If time is short, cut **[P1]/[P2]** items first. Never cut security items or tests for them.

## Non-negotiables
- **Everything must run offline with no API keys** via the mock/local providers (`LLM_PROVIDER=mock`, `EMBEDDING_PROVIDER=mock`, `CLASSIFIER_PROVIDER=local`, `SUGGESTION_PROVIDER=local`, `STORAGE_PROVIDER=localfs` for tests). Real providers are opt-in via env.
- **Never** commit secrets. Only `.env.example` with placeholders. Run gitleaks/bandit before each commit.
- **Never** scrape retailer websites. Live product data only via licensed/permitted APIs; otherwise use the local catalog.
- **Every query on user-owned data filters by `user_id`.** Add/maintain the IDOR test suite for every new router.
- Body images/videos are the most sensitive data: encrypted, face-blurred, raw deleted after analysis by default, **never sent to external services**.
- Treat all LLM/model/external output as untrusted: validate against schemas/enums; never execute or render it unsanitized.
- No tokens in browser `localStorage`. No `dangerouslySetInnerHTML`.
- Body-shape output is *styling guidance*, never a judgment. Neutral, body-positive language; no BMI/weight/attractiveness output.

## Code standards
- Python: type hints, ruff + black + mypy clean, Pydantic v2 schemas for all I/O, async where the framework benefits, no business logic in routers (put it in `services/`).
- Config only via `config.py` (pydantic-settings) from env. No hard-coded URLs/keys/model names.
- Alembic migration for every schema change; migrations must apply cleanly on an empty DB.
- Tests: pytest. Unit for pure logic (color, shape, scoring), integration for routers, `tests/security/` for auth/IDOR/upload abuse, `tests/ml/` for learning-curve and gating. Deterministic seeds.
- Frontend: TypeScript strict, API client generated from OpenAPI, accessible components, mobile-first.

## Commands (create these in Phase 0)
`make up | down | migrate | seed | demo | test | lint | fmt`

## Definition of done (summary)
`git clone` → `make demo` → full journey works with no keys; all acceptance criteria green; security checklist in PLAN.md §11 complete; learning-curve simulation shows improvement.

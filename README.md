# StyleSenseAI

> AI-powered personal styling and wardrobe management — built for SIH

StyleSenseAI takes your style preferences and body proportions, digitizes your wardrobe from photos/video, generates outfits from what you already own, finds wardrobe gaps, and suggests matching products. The recommender learns from your feedback and improves over time.

## Quick Start (≤5 commands)

```bash
# 1. Clone and enter
git clone <repo-url> && cd stylesense

# 2. Copy environment config
cp .env.example .env

# 3. Start infrastructure (PostgreSQL, Redis, MinIO)
make up

# 4. Install Python dependencies
make install

# 5. Run the API server
make dev
```

API is at `http://localhost:8000` — Docs at `http://localhost:8000/docs`

### Full Demo (with seed data)

```bash
make demo
# Starts infra → runs migrations → seeds demo data → API ready
```

## Architecture

| Component | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2, Pydantic v2 |
| Database | PostgreSQL + pgvector |
| Cache/Jobs | Redis + Arq |
| Storage | S3 API (MinIO local, S3 production) |
| Frontend | Next.js (App Router) + TypeScript + Tailwind + shadcn/ui |
| Auth | argon2id + JWT + rotating refresh tokens |
| ML | FashionCLIP, MediaPipe, LightGBM, scikit-learn |
| LLM | Claude (with mock provider for offline) |

## Key Principles

- **Offline-first:** Everything runs with zero API keys via mock/local providers
- **Privacy-by-design:** Body media encrypted, face-blurred, measurements encrypted at rest
- **Provider pattern:** Every external dependency has an offline implementation
- **Learning loop:** Recommendations improve with user feedback (Style DNA + ML ranker)
- **India-first:** INR default, ethnic wear categories are first-class

## Project Structure

```
stylesense/
  apps/
    api/           → FastAPI backend + ML services
    web/           → Next.js frontend
  docs/            → Technical documentation
  docker-compose.yml
  Makefile
```

## Make Commands

| Command | Description |
|---|---|
| `make up` | Start PostgreSQL, Redis, MinIO |
| `make down` | Stop infrastructure |
| `make dev` | Run API server with hot reload |
| `make migrate` | Run database migrations |
| `make test` | Run all tests |
| `make test-security` | Run security test suite |
| `make lint` | Run linters (ruff + mypy) |
| `make fmt` | Format code (ruff + black) |
| `make demo` | Full setup with demo data |

## Documentation

- [Build Plan](PLAN.md) — Phase-by-phase implementation plan
- [Decisions](docs/DECISIONS.md) — Architectural decisions with rationale
- [Progress](docs/PROGRESS.md) — Current implementation status

## License

Proprietary — SIH Project

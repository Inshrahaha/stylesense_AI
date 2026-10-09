# StyleSenseAI — Makefile
# Usage: make <target>

.PHONY: up down migrate seed demo test lint fmt install dev

# ── Infrastructure ──

up:
	docker compose up -d postgres redis minio
	@echo "Waiting for services to be healthy..."
	@sleep 3
	@echo "Infrastructure ready."

up-all:
	docker compose up -d
	@echo "All services started."

down:
	docker compose down

down-clean:
	docker compose down -v

# ── Database ──

migrate:
	cd apps/api && alembic upgrade head

migrate-new:
	cd apps/api && alembic revision --autogenerate -m "$(msg)"

# ── Application ──

install:
	cd apps/api && pip install -e ".[dev]"

dev:
	cd apps/api && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

worker:
	cd apps/api && arq app.workers.tasks.WorkerSettings

# ── Data ──

seed:
	cd apps/api && python -m scripts.seed_demo

demo: up migrate seed
	@echo "Demo environment ready! API at http://localhost:8000"

# ── Quality ──

test:
	cd apps/api && python -m pytest tests/ -v --tb=short

test-cov:
	cd apps/api && python -m pytest tests/ --cov=app --cov-report=term-missing

test-security:
	cd apps/api && python -m pytest tests/security/ -v

test-ml:
	cd apps/api && python -m pytest tests/ml/ -v

lint:
	cd apps/api && ruff check .
	cd apps/api && mypy app/ --ignore-missing-imports

fmt:
	cd apps/api && ruff check --fix .
	cd apps/api && black .

audit:
	cd apps/api && pip-audit
	cd apps/api && bandit -r app/ -c pyproject.toml || true

# ── Web (frontend) ──

web-install:
	cd apps/web && npm install

web-dev:
	cd apps/web && npm run dev

web-build:
	cd apps/web && npm run build

# StyleSenseAI — Makefile
# Usage: make <target>

.PHONY: up down migrate seed demo test lint fmt install dev

# Prefer the project virtual environment when present, while remaining usable
# on systems (including macOS) that expose Python as `python3`, not `python`.
PYTHON ?= $(if $(wildcard .venv/bin/python),$(CURDIR)/.venv/bin/python,python3)

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
	cd apps/api && $(PYTHON) -m alembic upgrade head

migrate-new:
	cd apps/api && $(PYTHON) -m alembic revision --autogenerate -m "$(msg)"

# ── Application ──

install:
	python3 -m venv .venv
	cd apps/api && ../../.venv/bin/python -m pip install -e ".[dev]"

dev:
	cd apps/api && $(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

worker:
	cd apps/api && $(PYTHON) -m arq app.workers.tasks.WorkerSettings

# ── Data ──

seed:
	cd apps/api && $(PYTHON) -m scripts.seed_demo

demo: up migrate seed
	@echo "Demo environment ready! API at http://localhost:8000"

# ── Quality ──

test:
	cd apps/api && $(PYTHON) -m pytest tests/ -v --tb=short

test-cov:
	cd apps/api && $(PYTHON) -m pytest tests/ --cov=app --cov-report=term-missing

test-security:
	cd apps/api && $(PYTHON) -m pytest tests/security/ -v

test-ml:
	cd apps/api && $(PYTHON) -m pytest tests/ml/ -v

lint:
	cd apps/api && $(PYTHON) -m ruff check .
	cd apps/api && $(PYTHON) -m mypy app/ --ignore-missing-imports

fmt:
	cd apps/api && $(PYTHON) -m ruff check --fix .
	cd apps/api && $(PYTHON) -m black .

audit:
	cd apps/api && $(PYTHON) -m pip_audit
	cd apps/api && $(PYTHON) -m bandit -r app/ -c pyproject.toml || true

# ── Web (frontend) ──

web-install:
	cd apps/web && npm install

web-dev:
	cd apps/web && npm run dev

web-build:
	cd apps/web && npm run build

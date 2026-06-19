SHELL := /bin/sh

.DEFAULT_GOAL := help

COMPOSE ?= docker compose
PYTEST ?= uv run --extra dev pytest
PYTEST_ARGS ?= -q
SERVICE ?= api
APP_SERVICE ?= api
DATABASE_URL ?= postgresql+psycopg://primmo:primmo@localhost:5432/primmo
TEST_DATABASE_URL ?= postgresql+psycopg://primmo:primmo@localhost:5432/primmo_test
COVERAGE_HTML_DIR ?= htmlcov

FRONT_URL ?= http://127.0.0.1:8080
API_URL ?= http://127.0.0.1:8000
ADMIN_URL ?= http://127.0.0.1:8001
MINIO_URL ?= http://127.0.0.1:9001
METABASE_URL ?= http://127.0.0.1:3000
METABASE_EMAIL ?= admin@primmo.local
METABASE_PASSWORD ?= PrimmoAdmin2026!
FLOWER_URL ?= http://127.0.0.1:5555

.PHONY: \
	help \
	bootstrap \
	up \
	down \
	clean \
	logs \
	ps \
	links \
	test \
	test-db \
	test-unit \
	test-integration \
	coverage \
	migrate \
	migrate-local \
	seed \
	seed-local \
	metabase-bootstrap

help:
	@printf "\n\033[1mPrimmo technical test\033[0m\n"
	@printf "FastAPI + Celery + PostgreSQL + Redis + MinIO\n\n"
	@printf "\033[1mStart here\033[0m\n"
	@printf "  make bootstrap          Start Docker, run migrations, seed demo data\n"
	@printf "  make links              Print local URLs for the demo\n\n"
	@printf "\033[1mDocker\033[0m\n"
	@printf "  make up                 Build and run all services\n"
	@printf "  make down               Stop and remove local services\n"
	@printf "  make clean              Stop services and delete local Docker volumes\n"
	@printf "  make logs SERVICE=api   Follow logs for one service\n"
	@printf "  make ps                 Show service status\n\n"
	@printf "\033[1mDatabase\033[0m\n"
	@printf "  make migrate            Run Alembic migrations inside Docker\n"
	@printf "  make seed               Insert demo organizations and users inside Docker\n"
	@printf "  make migrate-local      Run Alembic from host with DATABASE_URL\n"
	@printf "  make seed-local         Seed from host with DATABASE_URL\n\n"
	@printf "\033[1mObservability\033[0m\n"
	@printf "  make metabase-bootstrap Configure local Metabase demo dashboards\n\n"
	@printf "\033[1mTests\033[0m\n"
	@printf "  make test-db            Create the local test database if missing\n"
	@printf "  make test               Run all Python tests\n"
	@printf "  make test-unit          Run unit tests\n"
	@printf "  make test-integration   Run integration tests\n"
	@printf "  make coverage           Run tests with coverage report\n\n"

bootstrap:
	$(COMPOSE) up --build -d
	$(MAKE) migrate
	$(MAKE) seed
	$(MAKE) metabase-bootstrap
	@$(MAKE) --no-print-directory links

up:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

clean:
	$(COMPOSE) down --volumes --remove-orphans

logs:
	$(COMPOSE) logs -f $(SERVICE)

ps:
	$(COMPOSE) ps

links:
	@printf "\n\033[1mLocal URLs\033[0m\n"
	@printf "  Front demo:  %s\n" "$(FRONT_URL)"
	@printf "  API:         %s\n" "$(API_URL)"
	@printf "  Swagger:     %s/docs\n" "$(API_URL)"
	@printf "  OpenAPI:     %s/openapi.json\n" "$(API_URL)"
	@printf "  Flask admin: %s\n" "$(ADMIN_URL)"
	@printf "  Metabase:    %s\n" "$(METABASE_URL)"
	@printf "               login: %s / %s\n" "$(METABASE_EMAIL)" "$(METABASE_PASSWORD)"
	@printf "  Flower:      %s\n" "$(FLOWER_URL)"
	@printf "  MinIO:       %s\n" "$(MINIO_URL)"

test: test-db
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(PYTEST) $(PYTEST_ARGS)

test-db:
	$(COMPOSE) exec -T postgres sh -c 'createdb -U primmo primmo_test 2>/dev/null || true'

test-unit:
	$(PYTEST) $(PYTEST_ARGS) -m "not integration"

test-integration: test-db
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(PYTEST) $(PYTEST_ARGS) -m "integration"

coverage: test-db
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(PYTEST) $(PYTEST_ARGS) --cov=app --cov-report=term-missing:skip-covered --cov-report=html:$(COVERAGE_HTML_DIR)
	@printf "\nCoverage HTML: %s/index.html\n" "$(COVERAGE_HTML_DIR)"

migrate:
	$(COMPOSE) exec -T $(APP_SERVICE) alembic upgrade head

migrate-local:
	DATABASE_URL=$(DATABASE_URL) uv run alembic upgrade head

seed:
	$(COMPOSE) exec -T $(APP_SERVICE) python -m app.db.seed

seed-local:
	DATABASE_URL=$(DATABASE_URL) uv run python -m app.db.seed

metabase-bootstrap:
	METABASE_URL=$(METABASE_URL) uv run python scripts/bootstrap_metabase.py

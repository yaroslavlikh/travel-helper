.DEFAULT_GOAL := help

# `python3 -m uv` also works when a user-level pip installation is not on PATH.
UV ?= python3 -m uv
APP ?= app.main:app
HOST ?= 127.0.0.1
PORT ?= 8000

.PHONY: help bootstrap run dev app-migrate app-db-check langgraph-setup places-up places-down places-migrate places-check places-bootstrap-catalog places-import-istanbul places-import-all places-import-descriptions places-eval-istanbul format format-check lint typecheck test test-unit test-integration docs-check check clean

help: ## Show available development commands
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Install locked application and development dependencies
	$(UV) sync --all-groups --frozen

run: ## Run the application without autoreload
	$(UV) run uvicorn $(APP) --host $(HOST) --port $(PORT)

dev: ## Run the application with autoreload
	$(UV) run uvicorn $(APP) --host $(HOST) --port $(PORT) --reload

app-migrate: ## Apply additive PostgreSQL migrations for application state
	$(UV) run python scripts/migrate_app.py

app-db-check: ## Verify application tables and LangGraph checkpoint readiness
	$(UV) run python scripts/check_app_database.py

langgraph-setup: ## Create or upgrade LangGraph PostgreSQL checkpoint tables
	$(UV) run python scripts/setup_langgraph_postgres.py

places-up: ## Start local PostgreSQL with PostGIS and pgvector
	docker compose up --build -d places-db

places-down: ## Stop the local places database
	docker compose down

places-migrate: ## Apply the places PostgreSQL migrations
	$(UV) run python scripts/migrate_places.py

places-check: ## Verify places PostgreSQL schema, extensions and foreign keys
	$(UV) run python scripts/check_places_database.py

places-bootstrap-catalog: ## Seed the draft 60-country canonical identity catalog
	$(UV) run python scripts/bootstrap_global_catalog.py

places-import-istanbul: ## Fetch and import the bounded Istanbul OSM places scope
	$(UV) run python scripts/import_istanbul_places.py --fetch

places-import-all: ## Fetch and import each bounded destination OSM scope
	$(UV) run python scripts/import_all_places.py --fetch

places-import-descriptions: ## Import a reviewed POI description manifest (DESCRIPTIONS_INPUT=path)
	@test -n "$(DESCRIPTIONS_INPUT)" || (echo "Set DESCRIPTIONS_INPUT=path/to/manifest.json" && exit 2)
	$(UV) run python scripts/import_place_descriptions.py --input "$(DESCRIPTIONS_INPUT)"

places-eval-istanbul: ## Evaluate 30 fixed Istanbul retrieval queries against local storage
	$(UV) run python scripts/evaluate_istanbul_places.py

format: ## Apply code formatting and safe import fixes
	$(UV) run ruff format app tests scripts
	$(UV) run ruff check app tests scripts --fix

format-check: ## Check formatting without changing files
	$(UV) run ruff format --check app tests scripts

lint: ## Run static linting without autofix
	$(UV) run ruff check app tests scripts

typecheck: ## Run strict type checks for application code
	$(UV) run mypy app

test: ## Run the complete network-independent test suite
	$(UV) run pytest

test-unit: ## Run only fast unit tests
	$(UV) run pytest tests/unit

test-integration: ## Run integration tests with mocked or in-process I/O
	$(UV) run pytest tests/integration

docs-check: ## Validate Markdown local links and whitespace
	$(UV) run python scripts/check_docs.py

check: format-check lint typecheck test docs-check ## Run all non-mutating quality gates

clean: ## Remove generated local artifacts only
	rm -rf .coverage .mypy_cache .pytest_cache .ruff_cache htmlcov

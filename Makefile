.DEFAULT_GOAL := help

# `python3 -m uv` also works when a user-level pip installation is not on PATH.
UV ?= python3 -m uv
APP ?= app.main:app
HOST ?= 127.0.0.1
PORT ?= 8000

.PHONY: help bootstrap run dev format format-check lint typecheck test test-unit test-integration docs-check check clean

help: ## Show available development commands
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Install locked application and development dependencies
	$(UV) sync --all-groups --frozen

run: ## Run the application without autoreload
	$(UV) run uvicorn $(APP) --host $(HOST) --port $(PORT)

dev: ## Run the application with autoreload
	$(UV) run uvicorn $(APP) --host $(HOST) --port $(PORT) --reload

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

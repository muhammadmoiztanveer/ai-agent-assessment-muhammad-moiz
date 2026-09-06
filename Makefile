# =============================================================================
# Agentic Search Intelligence System — developer task runner
# =============================================================================
# Single-command run:  make install && make run
# =============================================================================

VENV        := .venv
PY          := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip
PYTEST      := $(VENV)/bin/pytest
RUFF        := $(VENV)/bin/ruff
BLACK       := $(VENV)/bin/black
MYPY        := $(VENV)/bin/mypy

FRONTEND_DIR := frontend

.DEFAULT_GOAL := help

.PHONY: help install run test lint format typecheck check clean \
        install-frontend run-frontend build-frontend

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ----------------------------- Backend --------------------------------------
install: ## Create venv and install the package with dev extras
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

run: ## Start the API server (python -m app)
	$(PY) -m app

test: ## Run the test suite
	$(PYTEST)

lint: ## Lint with ruff
	$(RUFF) check app tests

format: ## Auto-format with black and fix lint issues
	$(BLACK) app tests
	$(RUFF) check --fix app tests

typecheck: ## Static type-check with mypy
	$(MYPY) app

check: lint typecheck test ## Run lint + typecheck + tests

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache *.egg-info build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

# ----------------------------- Frontend -------------------------------------
install-frontend: ## Install frontend dependencies
	cd $(FRONTEND_DIR) && npm install

run-frontend: ## Start the frontend dev server (Vite)
	cd $(FRONTEND_DIR) && npm run dev

build-frontend: ## Build the frontend for production
	cd $(FRONTEND_DIR) && npm run build

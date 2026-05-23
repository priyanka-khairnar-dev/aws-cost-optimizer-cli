# Developer convenience targets. Run `make help` for the list.
.PHONY: help install dev test lint format typecheck check build clean verify-wheel release-check

PYTHON := python
VENV := .venv
BIN := $(VENV)/bin
WHEEL := dist/aws_cost_audit-0.1.0-py3-none-any.whl

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install:  ## Install runtime dependencies into the active environment
	pip install -e .

dev:  ## Install runtime + dev dependencies (linters, test tools, type stubs)
	pip install -e ".[dev]"

test:  ## Run the test suite
	pytest -v

lint:  ## Run ruff linter
	ruff check src tests

format:  ## Auto-format with ruff
	ruff format src tests

format-check:  ## Check formatting without modifying files (used by CI)
	ruff format --check src tests

typecheck:  ## Run mypy strict type checking
	mypy src

check: lint format-check typecheck test  ## Run all CI checks locally

build:  ## Build wheel + sdist into dist/
	rm -rf dist/ build/ src/*.egg-info
	pip install --quiet build
	python -m build

verify-wheel: build  ## Build wheel and install it in a clean venv to verify
	rm -rf /tmp/verify-venv
	python -m venv /tmp/verify-venv
	/tmp/verify-venv/bin/pip install --quiet $(WHEEL)
	/tmp/verify-venv/bin/cost-optimizer version
	@echo ""
	@echo "Wheel installed and verified at /tmp/verify-venv"

release-check: check verify-wheel  ## Full pre-release verification
	@echo ""
	@echo "All checks pass. Ready to tag and release."

clean:  ## Remove build artifacts and caches
	rm -rf dist/ build/ src/*.egg-info
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

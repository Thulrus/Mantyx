.PHONY: help install dev setup check-env run test format lint clean migrate db-upgrade db-downgrade pre-commit

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install production dependencies
	pip install -e .

dev:  ## Install development dependencies
	pip install -e ".[dev]"
	pre-commit install

setup:  ## Full development environment setup
	./scripts/setup-dev.sh

check-env:  ## Check development environment health
	./scripts/check-env.sh

run:  ## Run the Mantyx server
	python -m mantyx

test:  ## Run tests
	pytest -v

test-cov:  ## Run tests with coverage
	pytest --cov=mantyx --cov-report=html --cov-report=term

format:  ## Format code with black and isort
	black src/ tests/ examples/
	isort src/ tests/ examples/

lint:  ## Run linters
	ruff check src/ tests/
	mypy src/

pre-commit:  ## Run pre-commit hooks on all files
	pre-commit run --all-files

clean:  ## Clean up temporary files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/ .pytest_cache/ .coverage htmlcov/

migrate:  ## Create a new database migration
	@read -p "Enter migration message: " msg; \
	alembic revision --autogenerate -m "$$msg"

db-upgrade:  ## Upgrade database to latest version
	alembic upgrade head

db-downgrade:  ## Downgrade database by one version
	alembic downgrade -1

db-reset:  ## Reset database (WARNING: destroys all data)
	@echo "WARNING: This will delete all data. Press Ctrl+C to cancel."
	@sleep 5
	rm -f dev_data/data/mantyx.db
	alembic upgrade head

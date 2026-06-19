.PHONY: install test run clean lint format pre-commit docker-build docker-run help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install Python dependencies
	pip install -r requirements.txt

test: ## Run all tests with coverage
	python -m pytest tests/ -v --cov=src --cov-report=term-missing --cov-report=html

test-unit: ## Run unit tests only
	python -m pytest tests/ -v -m "not integration" --cov=src

test-integration: ## Run integration tests (requires Docker)
	python -m pytest tests/ -v -m integration

run: ## Run the crawler locally
	python run.py

clean: ## Clean cache and build artifacts
	rm -rf .pytest_cache __pycache__ */__pycache__ */*/__pycache__
	rm -rf htmlcov .coverage
	rm -rf output/* checkpoints/* cookies/*

lint: ## Run linters
	python -m pip install -q ruff
	python -m ruff check src/ tests/
	python -m ruff format --check src/ tests/

format: ## Auto-format code
	python -m ruff check --fix src/ tests/
	python -m ruff format src/ tests/

pre-commit: ## Install pre-commit hooks
	pre-commit install

docker-build: ## Build Docker images
	docker compose build

docker-run: ## Run full stack with Docker
	docker compose up --build

docker-logs: ## Follow crawler logs
	docker compose logs -f ifood-crawler

docker-clean: ## Remove all containers and volumes
	docker compose down -v

report: ## Generate execution report from checkpoint
	python -c "from src.adapters.persistence import SqlitePersistence; \
		from pathlib import Path; \
		p = SqlitePersistence(Path('/app/checkpoints/checkpoint.db')); \
		s = p.get_stats(); \
		print(f'Total: {s[\"total\"]}, OK: {s[\"success\"]}, Fail: {s[\"errors\"]}')"

.PHONY: help install test lint clean start stop health generate-data

# Ensure poetry is in PATH
export PATH := $(HOME)/.local/bin:$(PATH)

# Default target
.DEFAULT_GOAL := help

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install Python dependencies using Poetry
	poetry install --with dev,test

install-hooks: ## Install pre-commit hooks
	poetry run pre-commit install
	poetry run detect-secrets scan --baseline .secrets.baseline

test: ## Run test suite with coverage
	poetry run pytest

test-unit: ## Run unit tests only
	poetry run pytest tests/unit/

test-integration: ## Run integration tests only
	poetry run pytest tests/integration/

test-contract: ## Run contract tests only
	poetry run pytest tests/contract/

test-coverage: ## Generate HTML coverage report
	poetry run pytest --cov=src --cov-report=html
	@echo "Coverage report: htmlcov/index.html"

lint: ## Run linters (ruff, black, mypy)
	poetry run ruff check .
	poetry run black --check .
	poetry run mypy src/

lint-fix: ## Run linters with auto-fix
	poetry run ruff check --fix .
	poetry run black .

security: ## Run security scans (bandit, safety)
	poetry run bandit -r src/
	poetry run safety check

format: ## Format code with black
	poetry run black .

clean: ## Clean build artifacts and caches
	rm -rf build/ dist/ *.egg-info/
	rm -rf .pytest_cache/ .mypy_cache/ .ruff_cache/
	rm -rf htmlcov/ .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete

start: ## Start all services with Docker Compose
	docker compose up -d
	@echo "Waiting for services to be healthy..."
	@sleep 10
	@$(MAKE) health

stop: ## Stop all services
	docker compose down --volumes --remove-orphans

restart: ## Restart all services
	docker compose restart

logs: ## Follow Docker Compose logs
	docker compose logs -f

logs-app: ## Follow application logs only
	docker compose logs -f api

health: ## Check health of all services
	@echo "Checking service health..."
	@docker compose ps
	@echo "\nCassandra:"
	@bash scripts/health-check-cassandra.sh
	@echo "\nVault:"
	@bash scripts/health-check-vault.sh
	@echo "\nPostgreSQL:"
	@docker compose exec -T postgres pg_isready || echo "PostgreSQL not ready"
	@echo "\nKafka Connect:"
	@bash scripts/health-check-kafka-connect.sh

generate-data: ## Generate test data
	poetry run python scripts/generate_test_data.py --count 10000

deploy-connectors: ## Deploy Kafka Connect connectors
	bash docker/connectors/deploy-connectors.sh

setup-local: ## One-command local environment setup
	bash scripts/setup_local_env.sh

build: ## Build Docker images
	docker compose build

ps: ## Show running containers
	docker compose ps

shell-cassandra: ## Open Cassandra CQL shell
	docker compose exec cassandra cqlsh

shell-postgres: ## Open PostgreSQL shell
	docker compose exec postgres psql -U cdc_user -d warehouse

shell-kafka: ## Open Kafka console
	docker compose exec kafka kafka-console-consumer --bootstrap-server localhost:9092 --topic cdc-events-users --from-beginning

metrics: ## Open Prometheus metrics
	@echo "Prometheus: http://localhost:9090"
	@echo "Grafana: http://localhost:3000 (admin/admin)"
	@echo "Jaeger: http://localhost:16686"

benchmark: ## Run performance benchmarks with Locust
	poetry run locust -f scripts/benchmark.py --headless --users 100 --spawn-rate 10 --run-time 5m --html benchmark-report.html

benchmark-interactive: ## Run performance benchmarks with Locust UI
	poetry run locust -f scripts/benchmark.py

helm-lint: ## Lint Helm charts
	helm lint helm/

helm-template: ## Render Helm templates
	helm template cdc-pipeline helm/ > /tmp/helm-rendered.yaml
	@echo "Rendered templates written to /tmp/helm-rendered.yaml"

helm-validate: ## Validate Helm chart
	$(MAKE) helm-lint
	$(MAKE) helm-template

security-scan: ## Run comprehensive security scans
	$(MAKE) security
	@echo "\nScanning for secrets..."
	poetry run detect-secrets scan

type-check: ## Run mypy type checking
	poetry run mypy src --strict --show-error-codes

pre-commit: ## Run pre-commit hooks manually
	poetry run pre-commit run --all-files

all: clean install install-hooks lint test ## Run all checks and tests

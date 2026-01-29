.PHONY: help dev test test-unit test-e2e docker-build docker-up docker-down docker-logs clean install lint

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Local Development ───────────────────────────────────────────────

install: ## Install dependencies in venv
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

dev: ## Run dev mode (all nodes in-process, needs Neo4j)
	docker compose up neo4j -d
	.venv/bin/python main.py

dev-store: ## Run just the store+llm node locally
	.venv/bin/python run_node.py --capabilities store,llm --port 9000

dev-inference: ## Run an inference node locally (bootstrap to localhost:9000)
	.venv/bin/python run_node.py --capabilities inference --port 9001 --bootstrap http://localhost:9000

dev-validator: ## Run a validator node locally (bootstrap to localhost:9000)
	.venv/bin/python run_node.py --capabilities validation --port 9002 --bootstrap http://localhost:9000

dev-cli: ## Run a CLI node locally (bootstrap to localhost:9000)
	.venv/bin/python run_node.py --capabilities cli --port 9003 --bootstrap http://localhost:9000

# ── Testing ─────────────────────────────────────────────────────────

test: ## Run all tests that don't need Neo4j or API key
	.venv/bin/python -m pytest tests/ -v -m "not llm" --ignore=tests/test_store.py --ignore=tests/test_interfaces.py --ignore=tests/test_integration.py

test-unit: ## Run P2P and prompt unit tests (no external deps)
	.venv/bin/python -m pytest tests/test_p2p.py tests/test_prompts.py -v

test-store: ## Run store tests (needs Neo4j)
	.venv/bin/python -m pytest tests/test_store.py -v

test-all: ## Run all tests (needs Neo4j + API key)
	.venv/bin/python -m pytest tests/ -v

test-e2e: ## Run end-to-end tests in Docker (full stack)
	docker compose -f docker-compose.yml -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from test-runner
	docker compose -f docker-compose.yml -f docker-compose.test.yml down -v

# ── Docker ──────────────────────────────────────────────────────────

docker-build: ## Build all Docker images
	docker compose build

docker-up: ## Start the full stack (neo4j + store + inference + validator)
	docker compose up --build -d

docker-down: ## Stop all containers
	docker compose down

docker-logs: ## Tail logs from all containers
	docker compose logs -f

docker-scale-inference: ## Scale inference nodes (usage: make docker-scale-inference N=3)
	docker compose up --scale inference-node=$${N:-3} -d

# ── Cleanup ─────────────────────────────────────────────────────────

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache build dist

clean-docker: ## Remove all Docker volumes and images
	docker compose down -v --rmi all

.PHONY: help dev test test-all test-unit docker-build docker-up docker-down docker-logs clean install lint

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Local Development ───────────────────────────────────────────────

install: ## Install dependencies in venv
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

dev: ## Run full stack in Docker (Neo4j + store/LLM + inference + validator + CLI)
	@docker compose down --remove-orphans 2>/dev/null || true
	docker compose up --build -d
	@echo "Waiting for store node..."
	@until docker compose exec store-node python -c "import urllib.request; urllib.request.urlopen('http://localhost:9000/p2p/health')" 2>/dev/null; do sleep 2; done
	@trap 'docker compose down --remove-orphans' EXIT; \
	docker compose run --rm --no-deps --build cli-node

dev-store: ## Run just the store+llm node locally
	.venv/bin/python run_node.py --capabilities store,llm --port 9000

dev-inference: ## Run an inference node locally (bootstrap to localhost:9000)
	.venv/bin/python run_node.py --capabilities inference --port 9001 --bootstrap http://localhost:9000

dev-validator: ## Run a validator node locally (bootstrap to localhost:9000)
	.venv/bin/python run_node.py --capabilities validation --port 9002 --bootstrap http://localhost:9000

dev-cli: ## Run a CLI node locally (bootstrap to localhost:9000)
	.venv/bin/python run_node.py --capabilities cli --port 9003 --bootstrap http://localhost:9000

# ── Debug ──────────────────────────────────────────────────────────

debug-agents: ## Run full stack with DEBUG logging for agents, LLM, and prompts
	@docker compose down --remove-orphans 2>/dev/null || true
	docker compose up --build -d
	@echo "Waiting for store node..."
	@until docker compose exec store-node python -c "import urllib.request; urllib.request.urlopen('http://localhost:9000/p2p/health')" 2>/dev/null; do sleep 2; done
	@trap 'docker compose down --remove-orphans' EXIT; \
	LOG_CONFIG=logging.debug-agents.json docker compose run --rm --no-deps --build cli-node

# ── Testing ─────────────────────────────────────────────────────────
#
# Tests auto-skip based on what's available:
#   - No Neo4j → store/interface/integration tests skipped
#   - No ANTHROPIC_API_KEY → LLM tests skipped
#   - Just run `make test` and it does the right thing

test: ## Run all tests (auto-skips if Neo4j or API key missing)
	.venv/bin/python -m pytest tests/ -v

test-all: ## Start Neo4j, then run all tests (still needs API key for LLM tests)
	docker compose up neo4j -d
	@echo "Waiting for Neo4j..."
	@for i in $$(seq 1 30); do \
		docker compose exec neo4j cypher-shell -u neo4j -p memory-system "RETURN 1" >/dev/null 2>&1 && break; \
		sleep 2; \
	done
	.venv/bin/python -m pytest tests/ -v

test-unit: ## Run only unit tests (no Neo4j, no API key needed)
	.venv/bin/python -m pytest tests/test_p2p.py tests/test_prompts.py -v

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

# ────────────────────────────────────────────────────────────────────────────
# Makefile — Convenience targets for the p2p-mesh project.
#
# All Docker operations use infra/docker-compose.yml (project root is the
# build context). Run make targets from the project root.
#
# Usage:
#   make build                          # Build all Docker images
#   make up                             # Start the API server
#   make down                           # Stop all services
#   make test                           # Run the test suite
#   make phase1-native PROMPT="a vase"  # Run Phase 1 natively (macOS MPS)
#   make pipeline-mac  PROMPT="a vase"  # Full pipeline on Mac
#   make pipeline-gpu  PROMPT="a vase"  # Full pipeline with NVIDIA GPU
# ────────────────────────────────────────────────────────────────────────────

COMPOSE_FILE := infra/docker-compose.yml
COMPOSE_GPU  := infra/docker-compose.gpu.yml

.PHONY: build up down logs phase1-native pipeline-mac pipeline-gpu test test-slow health start-native

# ── Docker ────────────────────────────────────────────────────────────────────

# Build all Docker images
build:
	docker compose -f $(COMPOSE_FILE) build

# Start the API server (foreground)
up:
	docker compose -f $(COMPOSE_FILE) up api-server

# Start the API server natively on the host (required for MPS acceleration on Mac)
start-native:
	@echo "Starting API server natively on host to enable MPS acceleration..."
	@echo "Make sure you have installed the requirements: pip install -r requirements.txt"
	HOST_PROJECT_ROOT=$(PWD) COMPOSE_PROJECT_NAME=p2p-mesh-poc-docker python -m uvicorn server.app:app --host 0.0.0.0 --port 8000

# Stop all services
down:
	docker compose -f $(COMPOSE_FILE) down

# Tail logs for the API server
logs:
	docker compose -f $(COMPOSE_FILE) logs -f api-server

# ── Pipeline runs ─────────────────────────────────────────────────────────────

# Run Phase 1 natively on macOS (MPS accelerated, ~30s)
phase1-native:
	@if [ -z "$(PROMPT)" ]; then echo "Usage: make phase1-native PROMPT='a ceramic vase'"; exit 1; fi
	bash infra/scripts/run_phase1_native.sh "$(PROMPT)"

# Full pipeline on macOS: Phase 1 native (MPS) + Phases 2–5 in Docker
pipeline-mac:
	@if [ -z "$(PROMPT)" ]; then echo "Usage: make pipeline-mac PROMPT='a ceramic vase'"; exit 1; fi
	bash infra/scripts/run_phase1_native.sh "$(PROMPT)"
	docker compose -f $(COMPOSE_FILE) run --rm pipeline-runner \
		python pythonsrc/pipeline.py "$(PROMPT)" \
		--skip-visualizer --blueprint data/inputs/blueprint.png \
		--print --start-print

# Full pipeline with NVIDIA GPU (Linux / Windows with NVIDIA Container Toolkit)
pipeline-gpu:
	@if [ -z "$(PROMPT)" ]; then echo "Usage: make pipeline-gpu PROMPT='a ceramic vase'"; exit 1; fi
	docker compose -f $(COMPOSE_FILE) -f $(COMPOSE_GPU) \
		run --rm pipeline-runner \
		python pythonsrc/pipeline.py "$(PROMPT)" --print --start-print

# ── Testing ───────────────────────────────────────────────────────────────────

# Run default test suite (unit + mocked integration, no real printer)
test:
	python -m pytest tests/ -v

# Run slow tests (requires real/simulated printers)
test-slow:
	python -m pytest tests/ -v -m "slow and real_printer"

# ── Utilities ─────────────────────────────────────────────────────────────────

# Check API server health (requires running server)
health:
	curl -s http://localhost:8000/health | python3 -m json.tool

# Create data directories (first-time setup)
init:
	mkdir -p data/inputs data/outputs
	@echo "Runtime data directories created: data/inputs/ data/outputs/"

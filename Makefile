VENV ?= .venv
PYTHON ?= $(VENV)/bin/python
MODELS_DIR ?= $(CURDIR)/models
EVAL_DIR ?= $(CURDIR)/bench/data

.DEFAULT_GOAL := help
.PHONY: help install install-dev models bench bench-asr bench-meetings bench-data test lint format typecheck check clean docker-api docker-worker docker-models helm-lint

help:
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Create the virtualenv and install the runtime extras
	uv venv --python 3.11 $(VENV)
	uv pip install --python $(PYTHON) -e ".[api,asr-onnx,diarization,delivery,metrics,observability]"

install-dev: install ## Also install development and capture dependencies
	uv pip install --python $(PYTHON) -e ".[dev,capture]"
	$(PYTHON) -m playwright install --with-deps chromium

models: ## Fetch and verify the model bundle into $(MODELS_DIR)
	deploy/docker/fetch-models.sh deploy/docker/models.manifest deploy/docker/models.NOTICE $(MODELS_DIR)
	@echo "set HANSARD_RUNTIME__MODELS_DIR=$(MODELS_DIR)"

bench-data: ## Fetch the evaluation corpora
	$(PYTHON) -m hansard.evaluation.prepare --output $(EVAL_DIR)

bench-asr: ## Benchmark speech recognition in French and English
	$(PYTHON) -m hansard.evaluation.run asr --output bench/results/asr_bilingual.json

bench-meetings: ## Benchmark meeting transcription with speaker attribution
	$(PYTHON) -m hansard.evaluation.run meetings --output bench/results/synthetic_meetings.json

bench: bench-asr bench-meetings ## Run every benchmark

test: ## Run the test suite
	$(PYTHON) -m pytest tests -q

test-fast: ## Run the test suite, skipping slow tests
	$(PYTHON) -m pytest tests -q -m "not slow"

lint: ## Check formatting and lint rules
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff format --check src tests

format: ## Apply formatting
	$(PYTHON) -m ruff format src tests
	$(PYTHON) -m ruff check --fix src tests

typecheck: ## Run the type checker
	$(PYTHON) -m mypy src/hansard

check: lint typecheck test ## Everything CI runs

docker-api: ## Build the API image
	docker build -f deploy/docker/Dockerfile.api -t hansard-api:dev .

docker-worker: ## Build the CPU worker image
	docker build -f deploy/docker/Dockerfile.worker -t hansard-worker:dev .

docker-models: ## Build the OCI model artifact
	docker build -f deploy/docker/Dockerfile.models -t hansard-models:dev deploy/docker

helm-lint: ## Validate the Helm chart against every posture
	deploy/helm/hansard/hack/validate.sh

clean: ## Remove build and cache artefacts
	rm -rf build dist .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# Hansard image build / mirror / sign entrypoint.
#
#   make -C deploy/docker images                 # api + worker
#   make -C deploy/docker models                 # download weights ONCE, build artifacts
#   make -C deploy/docker push REGISTRY=harbor.internal/hansard
#   make -C deploy/docker digests                # emit deploy/helm/hansard/images.txt
#
# Every target is run from the repository root as build context.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

ROOT      := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
CHART     := $(ROOT)/deploy/helm/hansard
DOCKERDIR := $(ROOT)/deploy/docker
DIST      := $(ROOT)/dist

REGISTRY  ?= ghcr.io/haswell119
VERSION   ?= $(shell awk -F'"' '/^version =/{print $$2; exit}' $(ROOT)/pyproject.toml)
VCS_REF   ?= $(shell git -C $(ROOT) rev-parse --short HEAD 2>/dev/null || echo unknown)
BUILD_DATE?= $(shell date -u +%Y-%m-%dT%H:%M:%SZ)
PLATFORMS ?= linux/amd64

# Air-gapped builds: point these at internal mirrors.
PIP_INDEX_URL       ?= https://pypi.org/simple
PIP_EXTRA_INDEX_URL ?=
HF_ENDPOINT         ?= https://huggingface.co
GITHUB_MIRROR       ?= https://github.com

# Corporate TLS-inspecting proxy: point this at its CA and every build stage
# that talks HTTPS trusts it, without ever disabling verification.
comma               := ,
BUILD_CA_BUNDLE     ?=
CA_SECRET           := $(if $(BUILD_CA_BUNDLE),--secret id=ca_bundle$(comma)src=$(BUILD_CA_BUNDLE),)

# Packages the project's extras do not declare. Empty by design: sherpa-onnx
# now ships in pyproject's `diarization` extra, so nothing extra is needed.
# Kept as a knob for pinning or patching a dependency without editing
# pyproject.toml. `hansard doctor` inside the built image confirms the result.
EXTRA_PIP_PACKAGES ?=

# Browser capture bot. Owned by src/hansard/adapters/capture/docker/ - built
# here only so that one command produces a complete, mirrorable image set.
BOT_DOCKERFILE ?= $(ROOT)/src/hansard/adapters/capture/docker/Dockerfile

API_IMAGE        := $(REGISTRY)/hansard-api:$(VERSION)
WORKER_IMAGE     := $(REGISTRY)/hansard-worker:$(VERSION)
WORKER_GPU_IMAGE := $(REGISTRY)/hansard-worker-gpu:$(VERSION)
BOT_IMAGE        := $(REGISTRY)/hansard-bot:$(VERSION)
MODELS_IMAGE     := $(REGISTRY)/hansard-models:$(VERSION)
MODELS_INIT_IMAGE:= $(REGISTRY)/hansard-models-init:$(VERSION)
MODELS_ARTIFACT  := $(REGISTRY)/hansard-models-artifact:$(VERSION)

BUILD_ARGS := $(CA_SECRET) \
  --build-arg VERSION=$(VERSION) \
  --build-arg VCS_REF=$(VCS_REF) \
  --build-arg BUILD_DATE=$(BUILD_DATE) \
  --build-arg PIP_INDEX_URL=$(PIP_INDEX_URL) \
  --build-arg PIP_EXTRA_INDEX_URL=$(PIP_EXTRA_INDEX_URL) \
  --build-arg EXTRA_PIP_PACKAGES="$(EXTRA_PIP_PACKAGES)"

.PHONY: help
help:
	@grep -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

## ---------------------------------------------------------------- app images

.PHONY: api
api: ## Build the orchestrator/API image
	docker build $(BUILD_ARGS) -f $(DOCKERDIR)/Dockerfile.api -t $(API_IMAGE) $(ROOT)

.PHONY: worker
worker: ## Build the CPU worker image
	docker build $(BUILD_ARGS) -f $(DOCKERDIR)/Dockerfile.worker -t $(WORKER_IMAGE) $(ROOT)

.PHONY: worker-gpu
worker-gpu: ## Build the CUDA worker image (large; see CUDA pinning notes)
	docker build $(BUILD_ARGS) -f $(DOCKERDIR)/Dockerfile.worker-gpu -t $(WORKER_GPU_IMAGE) $(ROOT)

.PHONY: bot
bot: ## Build the browser capture bot (Dockerfile owned by the capture adapter)
	@test -f "$(BOT_DOCKERFILE)" \
	  || { echo "missing $(BOT_DOCKERFILE); the capture adapter owns it"; exit 1; }
	docker build $(BUILD_ARGS) -f $(BOT_DOCKERFILE) -t $(BOT_IMAGE) $(ROOT)

.PHONY: images
images: api worker ## Build the images every deployment needs

.PHONY: all-images
all-images: api worker worker-gpu bot models ## Build absolutely everything

## --------------------------------------------------------------- model images
#
# ONE download feeds all three model outputs, and every file is pinned by
# SHA-256 in models.manifest, so `make models` is reproducible and auditable.
# The BuildKit cache makes repeat targets free; nothing here ever runs inside a
# Hansard runtime container.
#
# The bundle serves FRENCH AND ENGLISH from a single multilingual ASR model
# (Parakeet TDT 0.6b v3). There is no per-language bundle to build.

MODELS_BUILD_ARGS := $(CA_SECRET) \
  --build-arg VERSION=$(VERSION) \
  --build-arg VCS_REF=$(VCS_REF) \
  --build-arg BUILD_DATE=$(BUILD_DATE) \
  --build-arg HF_ENDPOINT=$(HF_ENDPOINT) \
  --build-arg GITHUB_MIRROR=$(GITHUB_MIRROR)

.PHONY: models-export
models-export: ## Download+verify weights at build time into dist/models (host dir)
	mkdir -p $(DIST)
	docker buildx build $(MODELS_BUILD_ARGS) $(CA_SECRET) \
	  -f $(DOCKERDIR)/Dockerfile.models --target export \
	  --output type=local,dest=$(DIST)/models $(ROOT)
	@cd $(DIST)/models && sha256sum -c SHA256SUMS
	@du -sh $(DIST)/models

.PHONY: models-init-image
models-init-image: ## Build the busybox copier image (chart default)
	docker build $(MODELS_BUILD_ARGS) $(CA_SECRET) \
	  -f $(DOCKERDIR)/Dockerfile.models --target copier -t $(MODELS_INIT_IMAGE) $(ROOT)

.PHONY: models-scratch-image
models-scratch-image: ## Build the FROM scratch image (Kubernetes image: volume)
	docker build $(MODELS_BUILD_ARGS) $(CA_SECRET) \
	  -f $(DOCKERDIR)/Dockerfile.models --target artifact -t $(MODELS_IMAGE) $(ROOT)

.PHONY: models
models: models-export models-init-image models-scratch-image ## All model outputs

.PHONY: models-oras-push
models-oras-push: models-export ## Publish dist/models as a plain OCI artifact
	@command -v oras >/dev/null || { echo "install oras: https://oras.land"; exit 1; }
	cd $(DIST)/models && oras push $(MODELS_ARTIFACT) \
	  --artifact-type application/vnd.hansard.models.v1+tar \
	  --annotation "org.opencontainers.image.version=$(VERSION)" \
	  --annotation "io.hansard.models.mountpath=/models" \
	  $$(find . -type f | sed 's|^\./||' | sed 's|$$|:application/octet-stream|')

.PHONY: models-verify
models-verify: ## Re-verify dist/models against its own SHA256SUMS
	cd $(DIST)/models && sha256sum -c SHA256SUMS

## ------------------------------------------------------------ push / mirror

.PHONY: push
push: ## Push every locally built image to $(REGISTRY)
	for image in $(API_IMAGE) $(WORKER_IMAGE); do \
	  docker push "$$image"; \
	done

.PHONY: push-all
push-all: ## Push app, bot and model images
	for image in $(API_IMAGE) $(WORKER_IMAGE) $(WORKER_GPU_IMAGE) $(BOT_IMAGE) \
	             $(MODELS_IMAGE) $(MODELS_INIT_IMAGE); do \
	  docker image inspect "$$image" >/dev/null 2>&1 && docker push "$$image" || \
	    echo "skip (not built locally): $$image"; \
	done

.PHONY: digests
digests: ## Print repo@sha256 for every built image (paste into values.yaml)
	for image in $(API_IMAGE) $(WORKER_IMAGE) $(WORKER_GPU_IMAGE) $(BOT_IMAGE) \
	             $(MODELS_IMAGE) $(MODELS_INIT_IMAGE); do \
	  docker image inspect --format '{{index .RepoDigests 0}}' "$$image" 2>/dev/null \
	    || echo "$$image  <not pushed yet>"; \
	done

.PHONY: images-txt
images-txt: ## Regenerate deploy/helm/hansard/images.txt from the chart itself
	$(ROOT)/deploy/helm/hansard/hack/gen-images-txt.sh > $(CHART)/images.txt
	@cat $(CHART)/images.txt

.PHONY: save
save: ## Export a sneakernet tarball of every image for the air gap
	mkdir -p $(DIST)
	docker save -o $(DIST)/hansard-images-$(VERSION).tar \
	  $(API_IMAGE) $(WORKER_IMAGE) $(MODELS_INIT_IMAGE)
	@ls -lh $(DIST)/hansard-images-$(VERSION).tar

.PHONY: mirror
mirror: ## Copy the public image set into an internal registry with skopeo
	@test -n "$(TARGET_REGISTRY)" || { echo "set TARGET_REGISTRY=harbor.internal/hansard"; exit 1; }
	@command -v skopeo >/dev/null || { echo "install skopeo"; exit 1; }
	while read -r ref; do \
	  case "$$ref" in ''|\#*) continue;; esac; \
	  name="$${ref##*/}"; \
	  echo ">> $$ref -> $(TARGET_REGISTRY)/$$name"; \
	  skopeo copy --all "docker://$$ref" "docker://$(TARGET_REGISTRY)/$$name"; \
	done < $(CHART)/images.txt

## ------------------------------------------------------------------- signing

COSIGN_KEY ?= cosign.key

.PHONY: sign
sign: ## Sign pushed images with cosign (keyless by default in CI)
	@command -v cosign >/dev/null || { echo "install cosign"; exit 1; }
	for image in $(API_IMAGE) $(WORKER_IMAGE) $(MODELS_INIT_IMAGE); do \
	  if [ -f "$(COSIGN_KEY)" ]; then \
	    cosign sign --key "$(COSIGN_KEY)" --yes "$$image"; \
	  else \
	    cosign sign --yes "$$image"; \
	  fi; \
	done

.PHONY: verify
verify: ## Verify cosign signatures (air-gapped clusters use --key)
	for image in $(API_IMAGE) $(WORKER_IMAGE) $(MODELS_INIT_IMAGE); do \
	  cosign verify --key "$(COSIGN_KEY).pub" "$$image"; \
	done

.PHONY: sbom
sbom: ## Generate CycloneDX SBOMs next to the images
	mkdir -p $(DIST)/sbom
	@command -v syft >/dev/null || { echo "install syft"; exit 1; }
	for image in $(API_IMAGE) $(WORKER_IMAGE); do \
	  out="$(DIST)/sbom/$$(echo $$image | tr '/:' '__').cdx.json"; \
	  syft "$$image" -o cyclonedx-json > "$$out"; echo "$$out"; \
	done

.PHONY: size
size: ## Report uncompressed image sizes against the 1.5 GB budget
	docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' \
	  | grep -E 'hansard-(api|worker|worker-gpu|bot|models)' || true

.PHONY: clean
clean: ## Remove dist/
	rm -rf $(DIST)

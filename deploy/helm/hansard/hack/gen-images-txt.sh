#!/usr/bin/env bash
# Regenerate deploy/helm/hansard/images.txt from the chart itself, so the
# mirror list can never drift from what the chart actually pulls.
#
#   deploy/helm/hansard/hack/gen-images-txt.sh > deploy/helm/hansard/images.txt
#
# Every value set under ci/ is rendered with every optional CRD declared
# present, so images that appear in only one posture (GPU worker, ORAS init,
# mc, the scratch model artifact behind an ImageVolume) are still captured.
# Registry prefixes and digests from the ci/ files are neutralised: this file
# lists UPSTREAM references, which is what you mirror FROM.
set -euo pipefail

CHART="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

API_VERSIONS=(
  --api-versions monitoring.coreos.com/v1
  --api-versions keda.sh/v1alpha1
  --api-versions cilium.io/v2
  --api-versions external-secrets.io/v1beta1
  --api-versions objectstorage.k8s.io/v1alpha1
  --api-versions snapshot.storage.k8s.io/v1
)

NEUTRALISE=(--set global.imageRegistry= --set global.requireImageDigests=false)
for name in api worker workerGpu bot modelsInit modelsArtifact oras s3cli redis; do
  NEUTRALISE+=(--set "images.${name}.digest=")
done

render() {
  helm template hansard "$CHART" "${API_VERSIONS[@]}" "${NEUTRALISE[@]}" "$@" 2>/dev/null || true
}

collect() {
  # `image:` covers containers and initContainers; `reference:` covers the
  # Kubernetes ImageVolume source used by models.source=image.
  grep -Eo '^[[:space:]]*(- )?(image|reference):[[:space:]]*"?[^"[:space:]]+' \
    | sed -E 's/^[[:space:]]*(- )?(image|reference):[[:space:]]*"?//'
}

{
  render
  render --set asr.compute=both
  render --set models.source=image
  render --set models.source=oras --set models.oras.reference=PLACEHOLDER/hansard-models-artifact:0.1.0
  render --set models.source=s3 --set models.s3.endpoint=https://s3.invalid --set models.s3.bucket=models
  for values in "$CHART"/ci/*-values.yaml; do
    render -f "$values"
  done
} | collect | grep -v '^PLACEHOLDER/' | sort -u > "${TMPDIR:-/tmp}/hansard-images.$$"

cat <<'HEADER'
# Hansard container image manifest.
#
# GENERATED - do not edit by hand.
#   deploy/helm/hansard/hack/gen-images-txt.sh > deploy/helm/hansard/images.txt
#
# Mirror every line into your internal registry before an air-gapped install:
#   make -C deploy/docker mirror TARGET_REGISTRY=harbor.nkp.internal/hansard
# or, with NKP's own tooling:
#   nkp push bundle --bundle hansard-images.tar --to-registry harbor.nkp.internal/hansard
#
# Then set global.imageRegistry to that registry. Tags below are the chart
# defaults; pin by digest in production (make -C deploy/docker digests).
#
# Not every line is needed by every posture:
#   hansard-api, hansard-worker, redis, hansard-models-init  always
#   hansard-worker-gpu        asr.compute=gpu|both
#   hansard-bot               capture.engine=browser
#   hansard-models            models.source=image (ImageVolume)
#   oras                      models.source=oras
#   minio/mc                  models.source=s3
HEADER
cat "${TMPDIR:-/tmp}/hansard-images.$$"
rm -f "${TMPDIR:-/tmp}/hansard-images.$$"

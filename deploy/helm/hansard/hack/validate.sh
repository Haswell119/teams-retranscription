#!/usr/bin/env bash
# Everything CI runs against the chart. No cluster required.
#
#   deploy/helm/hansard/hack/validate.sh
#
# Needs: helm >= 3.14, kubeconform >= 0.6, python3 with PyYAML.
set -euo pipefail

CHART="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

POSTURES=(default airgap nkp-starter restricted gpu)

# Public CRD schemas, so ServiceMonitor / PrometheusRule / CiliumNetworkPolicy /
# ScaledObject are really validated instead of skipped. COSI is alpha and has no
# public schema, hence -ignore-missing-schemas.
CRDS='https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'

ALL_CRDS=(
  --api-versions monitoring.coreos.com/v1
  --api-versions keda.sh/v1alpha1
  --api-versions cilium.io/v2
  --api-versions external-secrets.io/v1beta1
  --api-versions objectstorage.k8s.io/v1alpha1
  --api-versions snapshot.storage.k8s.io/v1
)

echo "== helm lint =="
helm lint "$CHART"
for posture in "${POSTURES[@]}"; do
  helm lint "$CHART" -f "$CHART/ci/${posture}-values.yaml"
done

echo
echo "== helm template + kubeconform, no optional CRDs (the NKP Starter case) =="
for posture in "${POSTURES[@]}"; do
  helm template hansard "$CHART" -f "$CHART/ci/${posture}-values.yaml" \
    --namespace hansard > "$OUT/${posture}.yaml"
  printf '%-14s %3s objects  ' "$posture" "$(grep -c '^kind:' "$OUT/${posture}.yaml")"
  kubeconform -strict -summary -kubernetes-version 1.30.0 \
    -schema-location default -schema-location "$CRDS" -ignore-missing-schemas \
    "$OUT/${posture}.yaml"
done

echo
echo "== helm template + kubeconform, every optional CRD present =="
for posture in "${POSTURES[@]}"; do
  helm template hansard "$CHART" -f "$CHART/ci/${posture}-values.yaml" \
    --namespace hansard "${ALL_CRDS[@]}" > "$OUT/${posture}-full.yaml"
  printf '%-14s %3s objects  ' "$posture" "$(grep -c '^kind:' "$OUT/${posture}-full.yaml")"
  kubeconform -strict -summary -kubernetes-version 1.30.0 \
    -schema-location default -schema-location "$CRDS" -ignore-missing-schemas \
    "$OUT/${posture}-full.yaml"
done

echo
echo "== NKP Starter really gets no Pro-tier objects =="
for kind in ServiceMonitor PrometheusRule ScaledObject CiliumNetworkPolicy ExternalSecret; do
  if grep -q "^kind: ${kind}$" "$OUT/nkp-starter.yaml"; then
    echo "FAIL: ${kind} emitted without its CRD"
    exit 1
  fi
done
echo "PASS: no ServiceMonitor, PrometheusRule, ScaledObject, CiliumNetworkPolicy or ExternalSecret"

echo
echo "== guard rails reject invalid combinations =="
expect_failure() {
  local description="$1"; shift
  if helm template x "$CHART" "$@" >/dev/null 2>&1; then
    echo "FAIL: accepted ${description}"
    exit 1
  fi
  echo "  rejected: ${description}"
}
expect_failure "two secret sources"        --set secrets.existingSecret=foo
expect_failure "a CPU limit"               --set orchestrator.resources.limits.cpu=2
expect_failure "an unknown asr.language"   --set asr.language=klingon
expect_failure "a malformed digest"        --set images.api.digest=sha256:abc
expect_failure "virtual-host S3"           --set storage.backend=s3 --set storage.s3.forcePathStyle=false
expect_failure "a token on the bot SA"     --set serviceAccounts.bot.automountServiceAccountToken=true
expect_failure "external redis with no URL" --set redis.enabled=false
expect_failure "webhooks with no ingress"  --set webhook.enabled=true
expect_failure "proxy egress with no host" --set networkPolicy.egress.mode=proxy
expect_failure "unpinned images when pinning is required" --set global.requireImageDigests=true
expect_failure "browser capture with no bot" --set capture.engine=browser --set bot.enabled=false
expect_failure "oras models with no reference" --set models.source=oras
expect_failure "a clustering threshold above 1"  --set diarization.clusteringThreshold=1.5
expect_failure "an empty embedding model"        --set diarization.embeddingModel=
expect_failure "an unknown diarization engine"   --set diarization.engine=nemo

echo
echo "== Pod Security Standards (restricted) and bot Job invariants =="
python3 "$CHART/hack/check-pod-security.py" "$OUT"/*-full.yaml

echo
echo "== dashboard is valid JSON =="
python3 -c "import json,sys; d=json.load(open('$CHART/dashboards/hansard.json')); print(f\"  {d['title']} ({d['uid']}): {len(d['panels'])} panels\")"

echo
echo "== images.txt is up to date with the chart =="
"$CHART/hack/gen-images-txt.sh" > "$OUT/images.txt"
diff -u "$CHART/images.txt" "$OUT/images.txt" && echo "  in sync"

echo
echo "ALL CHECKS PASSED"

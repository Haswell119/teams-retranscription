#!/usr/bin/env sh
# Build-time model fetcher. Never runs inside a Hansard runtime container:
# it exists so that weights are resolved once, at image build time, and are
# then immutable and auditable.
#
#   fetch-models.sh <manifest> <output-dir>
#
# Honours HF_ENDPOINT so air-gapped builds can point at an internal mirror.
set -eu

MANIFEST="${1:?usage: fetch-models.sh <manifest> <output-dir>}"
OUT="${2:?usage: fetch-models.sh <manifest> <output-dir>}"

mkdir -p "$OUT"

# shellcheck disable=SC2162
grep -v '^[[:space:]]*#' "$MANIFEST" | grep -v '^[[:space:]]*$' | while IFS='|' read TARGET REPO REVISION PATTERNS; do
    echo ">> ${REPO}@${REVISION} -> ${OUT}/${TARGET}"
    HANSARD_TARGET="${OUT}/${TARGET}" \
    HANSARD_REPO="$REPO" \
    HANSARD_REVISION="$REVISION" \
    HANSARD_PATTERNS="$PATTERNS" \
    python - <<'PY'
import os

from huggingface_hub import snapshot_download

snapshot_download(
    repo_id=os.environ["HANSARD_REPO"],
    revision=os.environ["HANSARD_REVISION"],
    local_dir=os.environ["HANSARD_TARGET"],
    allow_patterns=[p for p in os.environ["HANSARD_PATTERNS"].split(",") if p],
    max_workers=4,
)
PY
done

# Strip the HF bookkeeping so the artifact holds nothing but weights + metadata.
find "$OUT" -name '.huggingface' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUT" -name '.cache' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUT" -name '*.lock' -delete 2>/dev/null || true

# Content addressing for the whole artifact. Operators diff this file between
# the internet-side build and the mirrored copy inside the air gap.
( cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 \
    | sort -z \
    | xargs -0 sha256sum > SHA256SUMS )

echo ">> model artifact contents"
( cd "$OUT" && du -sh . && wc -l < SHA256SUMS | xargs echo "files:" )

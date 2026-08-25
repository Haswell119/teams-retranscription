#!/usr/bin/env sh
# Build-time model fetcher. This NEVER runs inside a Hansard runtime container:
# it exists so that weights are resolved once, at image build time, verified
# against pinned SHA-256 digests, and then treated as immutable.
#
#   fetch-models.sh <manifest> <notice-file> <output-dir>
#
# Mirror support for air-gapped builds:
#   HF_ENDPOINT     replaces https://huggingface.co   (default: itself)
#   GITHUB_MIRROR   replaces https://github.com       (default: itself)
set -eu

MANIFEST="${1:?usage: fetch-models.sh <manifest> <notice> <output-dir>}"
NOTICE="${2:?usage: fetch-models.sh <manifest> <notice> <output-dir>}"
OUT="${3:?usage: fetch-models.sh <manifest> <notice> <output-dir>}"

HF_ENDPOINT="${HF_ENDPOINT:-https://huggingface.co}"
GITHUB_MIRROR="${GITHUB_MIRROR:-https://github.com}"

CACHE="$(mktemp -d)"
trap 'rm -rf "$CACHE"' EXIT

mkdir -p "$OUT"

rewrite_url() {
    printf '%s' "$1" \
        | sed -e "s|^https://huggingface\.co|${HF_ENDPOINT}|" \
              -e "s|^https://github\.com|${GITHUB_MIRROR}|"
}

# Download once per URL, so an archive feeding several targets is fetched once.
fetch_verified() {
    url="$1"
    want="$2"
    key="$(printf '%s' "$url" | sha256sum | cut -d' ' -f1)"
    blob="${CACHE}/${key}"
    if [ ! -f "$blob" ]; then
        printf '>> GET %s\n' "$url" >&2
        curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
             --max-time 3600 --output "$blob" "$(rewrite_url "$url")"
    fi
    got="$(sha256sum "$blob" | cut -d' ' -f1)"
    if [ "$got" != "$want" ]; then
        printf 'SHA-256 MISMATCH for %s\n  expected %s\n  actual   %s\n' "$url" "$want" "$got" >&2
        exit 1
    fi
    printf '%s' "$blob"
}

# shellcheck disable=SC2162
grep -v '^[[:space:]]*#' "$MANIFEST" | grep -v '^[[:space:]]*$' \
| while IFS='|' read TARGET URL SHA MEMBER; do
    dest="${OUT}/${TARGET}"
    mkdir -p "$(dirname "$dest")"
    blob="$(fetch_verified "$URL" "$SHA")"
    if [ -n "${MEMBER:-}" ]; then
        work="${CACHE}/x$(printf '%s' "$TARGET" | sha256sum | cut -d' ' -f1)"
        mkdir -p "$work"
        tar -xjf "$blob" -C "$work" "$MEMBER"
        cp "${work}/${MEMBER}" "$dest"
    else
        cp "$blob" "$dest"
    fi
    printf '   %s\n' "$TARGET"
done

cp "$NOTICE" "${OUT}/NOTICE"

# Content addressing for the whole artifact. Operators diff this file between
# the internet-side build and the mirrored copy inside the air gap, and the
# init container re-verifies it at pod start.
( cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 \
    | sort -z \
    | xargs -0 sha256sum > SHA256SUMS )

printf '>> model artifact: %s across %s files\n' \
    "$(du -sh "$OUT" | cut -f1)" "$(wc -l < "${OUT}/SHA256SUMS" | tr -d ' ')"

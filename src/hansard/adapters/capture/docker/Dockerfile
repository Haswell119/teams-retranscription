# Hansard meeting-capture bot pod: headful Chromium under Xvfb, audio via a PulseAudio null sink.
ARG PYTHON_IMAGE=python:3.11-slim-bookworm
FROM ${PYTHON_IMAGE}

ARG PLAYWRIGHT_VERSION=1.62.0
# Lock the browser: `docker build --build-arg CHROMIUM_SHA256=$(sha256sum of the binary printed below)`.
# The build fails when the argument is set and does not match, and records the observed value at
# /opt/hansard/chromium.sha256 so the first build can produce the value to pin.
ARG CHROMIUM_SHA256=""

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DISPLAY=:99 \
    SCREEN_GEOMETRY=1280x720x24 \
    HANSARD_SINK_NAME=hansard_sink \
    HANSARD_TTS_SINK_NAME=hansard_tts \
    HANSARD_VIRTUAL_MIC_NAME=hansard_mic

RUN apt-get update && apt-get install --no-install-recommends -y \
      ca-certificates \
      dbus-x11 \
      ffmpeg \
      fluxbox \
      procps \
      pulseaudio \
      pulseaudio-utils \
      tini \
      x11-utils \
      xauth \
      xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "playwright==${PLAYWRIGHT_VERSION}" \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

RUN set -eu; \
    mkdir -p /opt/hansard; \
    binary="$(find "${PLAYWRIGHT_BROWSERS_PATH}" -type f -name headless_shell -o -type f -name chrome | head -n 1)"; \
    test -n "${binary}"; \
    observed="$(sha256sum "${binary}" | cut -d' ' -f1)"; \
    printf '%s  %s\n' "${observed}" "${binary}" > /opt/hansard/chromium.sha256; \
    echo "chromium binary ${binary} sha256=${observed}"; \
    if [ -n "${CHROMIUM_SHA256}" ] && [ "${CHROMIUM_SHA256}" != "${observed}" ]; then \
      echo "pinned CHROMIUM_SHA256=${CHROMIUM_SHA256} does not match ${observed}" >&2; exit 1; \
    fi

WORKDIR /opt/hansard
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[capture,asr-onnx,delivery]"

COPY src/hansard/adapters/capture/docker/entrypoint.sh /usr/local/bin/hansard-entrypoint
RUN chmod +x /usr/local/bin/hansard-entrypoint \
    && useradd --create-home --shell /usr/sbin/nologin hansard \
    && mkdir -p /var/lib/hansard /run/user/1000 \
    && chown -R hansard:hansard /var/lib/hansard /run/user/1000 /opt/hansard

USER hansard
ENV HOME=/home/hansard \
    XDG_RUNTIME_DIR=/run/user/1000

ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/hansard-entrypoint"]
CMD ["hansard", "worker"]

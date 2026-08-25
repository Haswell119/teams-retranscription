#!/usr/bin/env bash
# Brings up Xvfb -> fluxbox -> PulseAudio -> null sink, then execs the worker as a child so that
# SIGTERM from the orchestrator is forwarded instead of being swallowed by PID 1.
set -euo pipefail

: "${DISPLAY:=:99}"
: "${SCREEN_GEOMETRY:=1280x720x24}"
: "${HANSARD_SINK_NAME:=hansard_sink}"
: "${HANSARD_TTS_SINK_NAME:=hansard_tts}"
: "${HANSARD_VIRTUAL_MIC_NAME:=hansard_mic}"
: "${HANSARD_STARTUP_TIMEOUT:=30}"
: "${XDG_RUNTIME_DIR:=/tmp/hansard-runtime}"
export DISPLAY XDG_RUNTIME_DIR

XVFB_PID=""
FLUXBOX_PID=""
PULSE_PID=""
CHILD_PID=""

log() { printf '[hansard-entrypoint] %s\n' "$*" >&2; }

stop_pid() {
  local pid="$1"
  [ -n "${pid}" ] || return 0
  kill -TERM "${pid}" 2>/dev/null || true
}

cleanup() {
  stop_pid "${PULSE_PID}"
  stop_pid "${FLUXBOX_PID}"
  stop_pid "${XVFB_PID}"
}
trap cleanup EXIT

wait_for() {
  local description="$1"
  shift
  local deadline=$((SECONDS + HANSARD_STARTUP_TIMEOUT))
  until "$@" >/dev/null 2>&1; do
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      log "timed out waiting for ${description}"
      return 1
    fi
    sleep 0.25
  done
  log "${description} is ready"
}

mkdir -p "${XDG_RUNTIME_DIR}"
chmod 700 "${XDG_RUNTIME_DIR}" 2>/dev/null || true

log "starting Xvfb on ${DISPLAY} (${SCREEN_GEOMETRY})"
Xvfb "${DISPLAY}" -screen 0 "${SCREEN_GEOMETRY}" -nolisten tcp -ac >/dev/null 2>&1 &
XVFB_PID=$!
wait_for "the X server" xdpyinfo -display "${DISPLAY}"

log "starting fluxbox"
fluxbox >/dev/null 2>&1 &
FLUXBOX_PID=$!

log "starting pulseaudio"
pulseaudio --exit-idle-time=-1 --disallow-exit --disable-shm=true --log-target=stderr >/dev/null 2>&1 &
PULSE_PID=$!
wait_for "the PulseAudio server" pactl info

if ! pactl list short sinks | cut -f2 | grep -qx "${HANSARD_SINK_NAME}"; then
  pactl load-module module-null-sink \
    "sink_name=${HANSARD_SINK_NAME}" \
    "sink_properties=device.description=MeetingOut" >/dev/null
fi
pactl set-default-sink "${HANSARD_SINK_NAME}"

if ! pactl list short sinks | cut -f2 | grep -qx "${HANSARD_TTS_SINK_NAME}"; then
  pactl load-module module-null-sink \
    "sink_name=${HANSARD_TTS_SINK_NAME}" \
    "sink_properties=device.description=MeetingIn" >/dev/null
fi

if ! pactl list short sources | cut -f2 | grep -qx "${HANSARD_VIRTUAL_MIC_NAME}"; then
  pactl load-module module-remap-source \
    "master=${HANSARD_TTS_SINK_NAME}.monitor" \
    "source_name=${HANSARD_VIRTUAL_MIC_NAME}" >/dev/null
fi
pactl set-default-source "${HANSARD_VIRTUAL_MIC_NAME}"
pactl set-source-mute "${HANSARD_VIRTUAL_MIC_NAME}" 1

wait_for "the meeting monitor source" \
  bash -c "pactl list short sources | cut -f2 | grep -qx '${HANSARD_SINK_NAME}.monitor'"

if [ "$#" -eq 0 ]; then
  log "no command given"
  exit 64
fi

log "starting worker: $*"
"$@" &
CHILD_PID=$!

forward() {
  local signal="$1"
  log "forwarding SIG${signal} to worker ${CHILD_PID}"
  kill -"${signal}" "${CHILD_PID}" 2>/dev/null || true
}
trap 'forward TERM' TERM
trap 'forward INT' INT
trap 'forward HUP' HUP

set +e
status=0
while true; do
  wait "${CHILD_PID}"
  status=$?
  if [ "${status}" -lt 128 ]; then
    break
  fi
  if ! kill -0 "${CHILD_PID}" 2>/dev/null; then
    break
  fi
done
set -e

log "worker exited with status ${status}"
exit "${status}"

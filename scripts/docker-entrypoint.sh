#!/usr/bin/env bash
# Container entrypoint: bring up a virtual display and an audio null sink so the
# headed browser and ffmpeg capture work, then exec the requested command.
set -euo pipefail

DISPLAY_NUM="${DISPLAY_NUM:-99}"
SINK_NAME="${PULSE_SINK_NAME:-meet_sink}"

# --- virtual display --------------------------------------------------
if ! pgrep -x Xvfb >/dev/null 2>&1; then
    echo "[entrypoint] starting Xvfb on :${DISPLAY_NUM}"
    Xvfb ":${DISPLAY_NUM}" -screen 0 1280x720x24 -nolisten tcp &
    sleep 1
fi
export DISPLAY=":${DISPLAY_NUM}"

# --- audio ------------------------------------------------------------
if command -v pulseaudio >/dev/null 2>&1; then
    if ! pgrep -x pulseaudio >/dev/null 2>&1; then
        echo "[entrypoint] starting PulseAudio"
        pulseaudio --start --exit-idle-time=-1 --disallow-exit || true
        sleep 1
    fi
    # A null sink gives ffmpeg a stable "meet_sink.monitor" to record.
    pactl load-module module-null-sink "sink_name=${SINK_NAME}" >/dev/null 2>&1 || true
    pactl set-default-sink "${SINK_NAME}" >/dev/null 2>&1 || true
fi

exec "$@"

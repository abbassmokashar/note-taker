# MeetingBot container.
#
# Runs the CLI, the web UI, and (Phases 3+) the headed Chromium join bot on Xvfb
# with a PulseAudio null sink for audio capture.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LANG=C.UTF-8 \
    TZ=Asia/Beirut \
    DISPLAY=:99 \
    PULSE_SINK_NAME=meet_sink

# System dependencies:
#   python3 / venv      -> runtime
#   ffmpeg              -> audio capture + normalization
#   xvfb                -> virtual display for the headed browser
#   pulseaudio          -> null-sink audio capture
#   fonts-noto*         -> Latin + Arabic (Naskh) rendering for PDFs/UI
#   libpango/cairo      -> WeasyPrint PDF export
#   tini                -> correct signal handling (SIGTERM -> graceful leave)
#   procps              -> pgrep used by the entrypoint
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-pip \
        ffmpeg \
        xvfb \
        pulseaudio \
        pulseaudio-utils \
        procps \
        tini \
        ca-certificates \
        fonts-noto-core \
        fonts-noto-color-emoji \
        fonts-noto-cjk \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi8 \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create an isolated virtualenv and install the package with all extras.
COPY pyproject.toml README.md ./
COPY src ./src
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install ".[all]"
ENV PATH="/opt/venv/bin:$PATH"

# Install Chromium and the system libraries Playwright needs.
RUN playwright install --with-deps chromium

COPY config.example.yaml ./
COPY docs ./docs
COPY scripts ./scripts
RUN chmod +x ./scripts/docker-entrypoint.sh

VOLUME ["/app/data"]

ENTRYPOINT ["/usr/bin/tini", "--", "/app/scripts/docker-entrypoint.sh"]
# Start the calendar scheduler. Run `meetingbot auth calendar` first, otherwise it
# exits with a clear message. Override with: docker compose run --rm meetingbot ...
CMD ["meetingbot", "run"]

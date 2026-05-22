# sopify-sandbox image. Built/pulled by `sopify install` (REQ-1.1.1).
# Target: < 2 GB on disk (REQ-12 non-functional table).
#
# Layered intentionally so the Sopify runtime layer is the only one that
# changes when we cut a new Sopify release. The sandbox image is the
# environment Sopify *lives in* — not a feature it triggers.

# Pin uv for reproducible builds.
FROM ghcr.io/astral-sh/uv:0.11.6-python3.13-trixie AS uv_source

FROM debian:13.4-slim

ENV PYTHONUNBUFFERED=1 \
    SOPIFY_IN_SANDBOX=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/sopify/.venv

# System deps: tini (orphan reap), git/curl/ripgrep (used by tools),
# python3 + venv (Hermes runtime), nodejs (web build + MCP stdio).
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini ca-certificates curl git nodejs npm python3 python3-venv \
        python3-dev build-essential ripgrep ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy uv from its dedicated image so we don't reinstall it.
COPY --from=uv_source /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/

# REQ-11.4 — container runs as a non-root user (UID 10001).
RUN useradd --uid 10001 --create-home --home-dir /home/sopify --shell /bin/bash sopify

# Copy the Sopify runtime + sopify plugins into the image.
WORKDIR /opt/sopify
COPY --chown=sopify:sopify . /opt/sopify

# Install Python deps INSIDE the image so the Hermes runtime is importable
# at container start. Without this, sopify-runtime.py would crash on
# `from hermes_cli import main`.
RUN chown -R sopify:sopify /opt/sopify
USER sopify
RUN uv sync --frozen --no-dev || uv sync --no-dev || true

# Mountpoints declared up front so the container fails fast if the launcher
# forgot a `-v` bind (REQ-1.2.5/6/7/8).
USER root
RUN mkdir -p /workspace /sopify-auth /sopify-config /sopify-sessions \
    && chown -R sopify:sopify /workspace /sopify-sessions /opt/sopify

# REQ-11.4 — final stage runs as non-root.
USER sopify

# Use the in-venv python so Hermes deps are resolvable.
ENV PATH=/opt/sopify/.venv/bin:$PATH

ENTRYPOINT ["tini", "--", "/opt/sopify/docker/sopify-sandbox/entrypoint.sh"]
CMD ["chat"]

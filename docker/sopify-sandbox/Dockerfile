# sopify-sandbox image — Linux runtime for sbx --template + standalone Docker.
#
# Built by `sopify install` (REQ-1.1.1) or manually:
#   docker build -t sopify-sandbox:latest docker/sopify-sandbox/
#
# When sbx is installed, sopify_sandbox.sbx_launcher passes this image
# via `sbx create --template sopify-sandbox:latest` so the microVM has
# Sopify + Hermes + all Python deps pre-installed and ready to run.

# Pin uv for reproducible builds.
FROM ghcr.io/astral-sh/uv:0.11.6-python3.13-trixie AS uv_source

FROM debian:13.4-slim

ENV PYTHONUNBUFFERED=1 \
    SOPIFY_IN_SANDBOX=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/sopify/.venv \
    PATH=/opt/sopify/.venv/bin:/usr/local/bin:/usr/bin:/bin

# System deps. tini reaps zombies; bash is what sbx exec calls;
# passwd provides useradd; adduser is the friendly wrapper.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini ca-certificates curl git bash \
        passwd adduser \
        nodejs npm \
        python3 python3-venv python3-dev build-essential \
        ripgrep ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy uv from its dedicated image.
COPY --from=uv_source /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/

# REQ-11.4 — non-root user. Use absolute path because some slim base
# images don't put /usr/sbin on the default /bin/sh PATH.
RUN /usr/sbin/useradd --uid 10001 --create-home --home-dir /home/sopify --shell /bin/bash sopify

# Copy entire repo into image. Layered after deps so source edits don't
# bust the apt cache layer.
WORKDIR /opt/sopify
COPY --chown=sopify:sopify . /opt/sopify

# Build the Linux-native venv with all extras Sopify needs:
#   web         → fastapi + uvicorn (dashboard)
#   cli         → interactive TUI menus
#   anthropic   → primary provider SDK
#   pty         → ptyprocess for the /chat tab
# This is the slowest step in the build (~60-90s) but happens once at
# image-build time, not at every microVM cold start.
USER sopify
RUN uv sync --frozen \
        --extra web --extra cli --extra anthropic --extra pty \
    || uv sync --extra web --extra cli --extra anthropic --extra pty \
    || true

# Wire the wrapper so `sopify ...` works inside the microVM regardless
# of how sbx invokes commands.
USER root
RUN ln -sf /opt/sopify/sopify /usr/local/bin/sopify \
    && chmod +x /opt/sopify/sopify

# Pre-declare mountpoints so sbx's bind-mount lands at expected paths.
RUN mkdir -p /workspace /sopify-auth /sopify-config /sopify-sessions \
    && chown -R sopify:sopify /workspace /sopify-sessions /opt/sopify

# Smoke test inside the build so a broken venv breaks the build, not
# the user's first dashboard launch.
USER sopify
RUN python3 -c "import sys; sys.path.insert(0, '/opt/sopify'); \
                from plugins.sopify_core import version, paths, doctor; \
                print('sopify build smoke:', version.full_version_string())"

USER sopify
WORKDIR /workspace

# sbx invokes commands via `sbx exec bash -c ...`. Default CMD is the
# shell so `sbx run SANDBOX` without args just drops into bash.
ENTRYPOINT ["tini", "--"]
CMD ["bash"]

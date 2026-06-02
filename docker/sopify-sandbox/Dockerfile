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
        passwd adduser procps \
        nodejs npm \
        python3 python3-venv python3-dev build-essential \
        ripgrep ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Pre-install Claude Code (CLI) globally so the sandbox can run `claude`
# without a runtime npm fetch (network is restricted by ENCM no_proxy, so a
# first-run `npm install -g` could be blocked). Pinned for reproducible
# builds — bump CLAUDE_CODE_VERSION to upgrade. Lives here (root, before the
# repo COPY) so the layer caches and source edits don't bust it. The npm
# global bin lands in /usr/local/bin, already on PATH (see ENV above).
ARG CLAUDE_CODE_VERSION=2.1.159
RUN npm install -g --no-fund --no-audit \
        @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# Copy uv from its dedicated image.
COPY --from=uv_source /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/

# REQ-11.4 — non-root user. Use absolute path because some slim base
# images don't put /usr/sbin on the default /bin/sh PATH.
RUN /usr/sbin/useradd --uid 10001 --create-home --home-dir /home/sopify --shell /bin/bash sopify

# Pre-create + chown /opt/sopify so the sopify user can write into it
# (specifically /opt/sopify/.venv) when uv sync runs as that user later.
# Without this, WORKDIR creates /opt/sopify as root-owned and COPY's
# --chown only affects the COPIED files, not the parent directory.
RUN mkdir -p /opt/sopify && chown sopify:sopify /opt/sopify

# Copy entire repo into image. Layered after deps so source edits don't
# bust the apt cache layer.
WORKDIR /opt/sopify
COPY --chown=sopify:sopify . /opt/sopify

# Build the Linux-native venv with all extras Sopify needs:
#   web         → fastapi + uvicorn (dashboard)
#   cli         → interactive TUI menus
#   anthropic   → primary provider SDK
#   pty         → ptyprocess for the /chat tab
# Slow step (~60-90s) but happens once at build time. We do NOT use
# `|| true` here — a failed uv sync MUST fail the build, otherwise the
# image ships without yaml/fastapi/anthropic and the dashboard dies
# the first time it tries to import them.
USER sopify
RUN uv sync --frozen \
        --extra web --extra cli --extra anthropic --extra pty \
    || uv sync \
        --extra web --extra cli --extra anthropic --extra pty

# Pre-install TUI Node deps so the dashboard chat tab starts instantly.
# Without this, every microVM boot triggers `npm install` (30-90s) the first
# time the user opens /chat, and the WebSocket handshake races against the
# install causing `RuntimeError: WebSocket is not connected` in tui_gateway.
# Build the @hermes/ink local package's dist/ bundle too — main.py's
# _tui_need_npm_install treats a missing @hermes/ink as a reinstall signal.
RUN cd /opt/sopify/ui-tui \
    && npm install --silent --no-fund --no-audit --progress=false \
    && cd /opt/sopify/ui-tui/packages/hermes-ink \
    && npm run build

# Pre-bundle the TUI itself (esbuild → dist/entry.js) so node can run it
# directly without an esbuild step on first launch.
RUN cd /opt/sopify/ui-tui && node scripts/build.mjs

# Wire the wrapper so `sopify ...` works inside the microVM regardless
# of how sbx invokes commands. We write a tiny bash wrapper that
# EXPLICITLY invokes the venv python — a Python-shebang shim resolves
# python3 via PATH lookup, which can land on system /usr/bin/python3
# (no deps) instead of the venv.
USER root
RUN cat > /usr/local/bin/sopify <<'WRAPPER_EOF' \
 && chmod +x /usr/local/bin/sopify
#!/usr/bin/env bash
exec /opt/sopify/.venv/bin/python /opt/sopify/sopify "$@"
WRAPPER_EOF

# CA installer removed 2026-05-24 — the MITM-proxy variant of ENCM is
# archived under archive/2026-05-24-encm-mitm-attempt/. The new ENCM
# Control Plane talks to sandboxd via API, not via a sandbox-side CA.
#
# (Comment trail for the line block that used to live below — kept so
# `git log -S install-sopify-ca.sh` finds this removal in the future.)

# Pre-declare mountpoints so sbx's bind-mount lands at expected paths.
RUN mkdir -p /workspace /sopify-auth /sopify-config /sopify-sessions \
    && chown -R sopify:sopify /workspace /sopify-sessions /opt/sopify

# Smoke test: confirm yaml + fastapi + anthropic SDK ALL import via the
# venv python. If any of these are missing the build fails here, not
# at the user's first dashboard launch.
USER sopify
RUN /opt/sopify/.venv/bin/python -c "import yaml, fastapi, uvicorn, anthropic, ptyprocess, multipart; print('venv smoke ok')"
RUN test -f /opt/sopify/ui-tui/dist/entry.js \
    && test -f /opt/sopify/ui-tui/node_modules/@hermes/ink/package.json \
    && echo "tui bundle ok"
# Confirm the runtime user (sopify) can invoke the globally-installed CLI.
RUN claude --version
RUN /opt/sopify/.venv/bin/python -c "import sys; sys.path.insert(0, '/opt/sopify'); \
                from plugins.sopify_core import version; \
                print('sopify build smoke:', version.full_version_string())"

USER sopify
WORKDIR /workspace

# sbx invokes commands via `sbx exec bash -c ...`. Default CMD is the
# shell so `sbx run SANDBOX` without args just drops into bash.
ENTRYPOINT ["tini", "--"]
CMD ["bash"]

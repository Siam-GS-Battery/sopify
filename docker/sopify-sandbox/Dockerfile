# sopify-sandbox image. Built/pulled by `sopify install` (REQ-1.1.1).
# Target: < 2 GB on disk (REQ-12 non-functional table).
#
# Layered intentionally so the Sopify runtime layer is the only one that
# changes when we cut a new Sopify release. The sandbox image is the
# environment Sopify *lives in* — not a feature it triggers.

FROM debian:13.4-slim

ENV PYTHONUNBUFFERED=1 \
    SOPIFY_IN_SANDBOX=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# tini reaps orphans (MCP/git/bun subprocesses) when we run as PID 1.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini ca-certificates curl git nodejs npm python3 python3-pip ripgrep \
    && rm -rf /var/lib/apt/lists/*

# REQ-11.4 — container runs as a non-root user.
RUN useradd --uid 10001 --create-home --home-dir /home/sopify --shell /bin/bash sopify

# Copy the Sopify runtime + sopify plugins into the image.
WORKDIR /opt/sopify
COPY --chown=sopify:sopify . /opt/sopify

# Mountpoints declared up front so the container fails fast if the launcher
# forgot a `-v` bind (REQ-1.2.5/6/7/8).
RUN mkdir -p /workspace /sopify-auth /sopify-config /sopify-sessions \
    && chown -R sopify:sopify /workspace /sopify-sessions

# REQ-11.4 — drop to non-root.
USER sopify

ENTRYPOINT ["tini", "--", "/opt/sopify/docker/sopify-sandbox/entrypoint.sh"]
CMD ["chat"]

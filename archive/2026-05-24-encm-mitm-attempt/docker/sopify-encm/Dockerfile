# sopify-encm:latest — External Network Control Module.
#
# Built by `sopify install` (REQ-ENCM-M1) or manually:
#   docker build -t sopify-encm:latest -f docker/sopify-encm/Dockerfile .
#
# Runs mitmproxy as the HTTP/HTTPS layer-7 forward proxy + asyncio TCP
# forward for raw-protocol rules (PG/MySQL/Redis — M1.9, in progress).
# Mounts:
#   ~/.sopify/network-policy.json   → /etc/encm/policy.json     (ro)
#   ~/.sopify/encm-ca/              → /etc/encm/ca/             (ro)
#   ~/.sopify/audit-log/            → /var/log/encm/audit/      (rw)

FROM ghcr.io/astral-sh/uv:0.11.6-python3.13-trixie AS uv_source

FROM debian:13.4-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/encm/.venv \
    PATH=/opt/encm/.venv/bin:/usr/local/bin:/usr/bin:/bin

# System deps. Only what mitmproxy + asyncio + the audit writer need.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini ca-certificates curl \
        python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv_source /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/

# Non-root user — ENCM never needs root once bound to its listening ports
# above the privileged range (3128/1883/9001/5432-range).
RUN /usr/sbin/useradd --uid 10002 --create-home --home-dir /home/encm --shell /bin/bash encm

# Pre-create + chown the venv target so uv sync can write as the encm user.
RUN mkdir -p /opt/encm && chown encm:encm /opt/encm

# Copy ONLY the ENCM plugin code + its bare deps — the full sopify repo
# isn't needed here (and we want the image small).
WORKDIR /opt/encm
COPY --chown=encm:encm plugins/sopify_encm/ /opt/encm/sopify_encm/
COPY --chown=encm:encm docker/sopify-encm/requirements.txt /opt/encm/requirements.txt
COPY --chown=encm:encm docker/sopify-encm/entrypoint.sh /opt/encm/entrypoint.sh
COPY --chown=encm:encm docker/sopify-encm/healthcheck.sh /opt/encm/healthcheck.sh
RUN chmod +x /opt/encm/entrypoint.sh /opt/encm/healthcheck.sh

USER encm
RUN uv venv /opt/encm/.venv \
 && uv pip install --python /opt/encm/.venv/bin/python -r /opt/encm/requirements.txt

# Pre-create mount points so docker -v lands in expected locations
USER root
RUN mkdir -p /etc/encm /var/log/encm/audit \
 && chown -R encm:encm /etc/encm /var/log/encm

USER encm

# Smoke test — imports work, no broken modules
RUN /opt/encm/.venv/bin/python -c "import mitmproxy; import sys; sys.path.insert(0, '/opt/encm'); from sopify_encm import schema, ca; print('encm smoke ok')"

# Default listeners — overridable via env.
# PYTHONPATH lets `sopify_encm.*` resolve as a top-level package — mitmdump
# loads addons via `--scripts <path>` which runs them as standalone modules
# (no enclosing package), so absolute imports `from sopify_encm.audit import …`
# need this on sys.path.
ENV ENCM_HTTP_PROXY_PORT=3128 \
    ENCM_WEBSOCKET_PORT=9001 \
    ENCM_MQTT_BROKER_PORT=1883 \
    ENCM_POLICY_PATH=/etc/encm/policy.json \
    ENCM_AUDIT_DIR=/var/log/encm/audit \
    ENCM_CA_DIR=/etc/encm/ca \
    SOPIFY_ENCM_CA_DIR=/etc/encm/ca \
    PYTHONPATH=/opt/encm

EXPOSE 3128 1883 9001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD /opt/encm/healthcheck.sh

ENTRYPOINT ["tini", "--", "/opt/encm/entrypoint.sh"]

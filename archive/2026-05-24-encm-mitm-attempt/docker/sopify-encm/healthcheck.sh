#!/usr/bin/env bash
# Healthcheck — proxy is live iff it answers a HEAD request on the listen port.
# We don't care about the response code, just that the port is bound and
# accepting connections. mitmproxy returns 502 for unmatched destinations
# (no upstream), which is fine for a liveness probe.

set -e

PORT="${ENCM_HTTP_PROXY_PORT:-3128}"
curl --silent --output /dev/null --fail-with-body --max-time 3 \
     --proxy "http://127.0.0.1:${PORT}" \
     http://encm-healthcheck.invalid/ || exit_code=$?

# Any response (even an upstream-failure 502) means the proxy is alive.
# Curl exit 7 = connection refused → the only one we treat as unhealthy.
if [[ "${exit_code:-0}" == "7" ]]; then
    echo "encm: proxy not listening on port $PORT" >&2
    exit 1
fi
exit 0

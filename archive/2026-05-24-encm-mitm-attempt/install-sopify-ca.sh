#!/usr/bin/env bash
# Sopify CA install — runs at sandbox boot via the /usr/local/bin/sopify wrapper.
#
# Why env-vars and not the system trust store:
#   Sandbox runs as non-root user `sopify` (uid 10001) which can't write to
#   /usr/local/share/ca-certificates/ or run update-ca-certificates without
#   sudo (we deliberately don't install sudo — REQ-11.4 non-root invariant).
#
#   Instead we build a combined CA bundle (system roots + Sopify CA) at a
#   user-writable location and let the wrapper export CURL_CA_BUNDLE /
#   SSL_CERT_FILE / REQUESTS_CA_BUNDLE / NODE_EXTRA_CA_CERTS pointing at it.
#   Every mainstream HTTPS client honours at least one of these.
#
# Locating the CA cert:
#   - sbx microVM:   virtiofs preserves host path. SOPIFY_ENCM_CA_DIR_HOST is
#                    set by the launcher and points to the directory.
#   - docker run:    legacy bind-mount at /sopify-encm-ca/.
#
# Idempotent — overwriting /tmp/sopify-ca-bundle.pem each call is cheap.

set -euo pipefail

# ── 1. Find the source CA cert ──────────────────────────────────────────
if [[ -n "${SOPIFY_ENCM_CA_DIR_HOST:-}" ]] && [[ -f "$SOPIFY_ENCM_CA_DIR_HOST/ca.crt" ]]; then
    SRC="$SOPIFY_ENCM_CA_DIR_HOST/ca.crt"
elif [[ -f /sopify-encm-ca/ca.crt ]]; then
    SRC=/sopify-encm-ca/ca.crt
else
    # ENCM not installed yet on host (e.g. user opted out via SOPIFY_NO_ENCM=1)
    # — graceful: no bundle written, wrapper falls back to system trust store.
    exit 0
fi

# ── 2. Build the combined bundle ────────────────────────────────────────
# Concatenation order matters: system roots first, Sopify CA appended. Both
# OpenSSL and Node walk the file looking for any chain that validates, so a
# duplicate-name cert won't cause issues.
DST=/tmp/sopify-ca-bundle.pem
SYSTEM=/etc/ssl/certs/ca-certificates.crt

if [[ -f "$SYSTEM" ]]; then
    cat "$SYSTEM" "$SRC" > "$DST"
else
    # Minimal debian-slim base — fallback to Sopify CA alone. mitmproxy
    # signs every leaf so this is enough for proxied traffic.
    cat "$SRC" > "$DST"
fi
chmod 644 "$DST"

# Print the bundle path so the wrapper can export env vars from it.
echo "$DST"

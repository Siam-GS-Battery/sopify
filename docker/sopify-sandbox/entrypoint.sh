#!/usr/bin/env bash
# sopify-sandbox entrypoint. Runs as the non-root `sopify` user (REQ-11.4).
# REQ-1.2.* — sets up the in-container view of host-mounted config and
# kicks the Sopify runtime with sopify plugins loaded.

set -euo pipefail

# Fail-fast if the launcher forgot a required mount (REQ-1.2.5/6/7/8).
for mount in /workspace /sopify-auth /sopify-config /sopify-sessions; do
    if ! [ -e "$mount" ]; then
        echo "sopify-sandbox: missing required mount $mount" >&2
        exit 64
    fi
done

# Re-export the host-mounted config in the env the rest of sopify expects.
export SOPIFY_HOME=/home/sopify/.sopify
mkdir -p "$SOPIFY_HOME"
ln -sf /sopify-auth/auth.json   "$SOPIFY_HOME/auth.json"   || true
ln -sf /sopify-config/settings.json "$SOPIFY_HOME/settings.json" || true
ln -sf /sopify-sessions          "$SOPIFY_HOME/sessions"    || true

cd /workspace
exec python3 /opt/sopify/sopify-runtime.py "$@"

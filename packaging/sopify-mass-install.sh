#!/usr/bin/env bash
# Sopify mass-deploy installer (REQ-9.2.2).
#
# Distributed by IT via MDM (Jamf, Intune, Workspace ONE). Unlike the
# end-user one-liner, this script:
#
#   1. Pre-seeds `~/.sopify/settings.json` (0444) with org-managed config
#   2. Pre-seeds `~/.sopify/profile.json` (0444) with the user's role
#   3. Auto-consents the audit flow (REQ-7.4.4 — consent is logged but
#      the dialog is skipped because the user already agreed at hiring)
#   4. Runs the normal sopify-install.sh
#
# Usage (IT side):
#   sudo SOPIFY_ROLE=user SOPIFY_USER_EMAIL=alice@gsbattery.co.th \
#        bash packaging/sopify-mass-install.sh
#
# Variables:
#   SOPIFY_ROLE              "user" (default) or "dev"
#   SOPIFY_USER_EMAIL        e-mail (becomes user_email in OTel events)
#   SOPIFY_MANAGED_SETTINGS  path to a template settings.json on the host
#                            (default: /etc/sopify/settings.json)
#   SOPIFY_OTEL_ENDPOINT     override OTel collector URL
#   SOPIFY_PROVIDER_CHAIN    JSON array string, e.g. '["anthropic","openrouter"]'

set -euo pipefail

ROLE="${SOPIFY_ROLE:-user}"
USER_EMAIL="${SOPIFY_USER_EMAIL:-$(id -un)@gsbattery.co.th}"
MANAGED_TEMPLATE="${SOPIFY_MANAGED_SETTINGS:-/etc/sopify/settings.json}"
OTEL_ENDPOINT="${SOPIFY_OTEL_ENDPOINT:-http://otel-collector.gsbattery.local:4318/v1/logs}"
PROVIDER_CHAIN="${SOPIFY_PROVIDER_CHAIN:-[\"anthropic\",\"openrouter\"]}"

# Pre-flight: must run as the target user (not root) so files end up
# owned correctly. `sudo -u <user>` is the usual invocation pattern.
if [ "$EUID" -eq 0 ] && [ -z "${SOPIFY_ALLOW_ROOT:-}" ]; then
    echo "sopify-mass-install: do not run as root; use sudo -u <user>." >&2
    exit 64
fi

SOPIFY_DIR="$HOME/.sopify"
mkdir -p "$SOPIFY_DIR" "$SOPIFY_DIR/sessions"
chmod 0700 "$SOPIFY_DIR" "$SOPIFY_DIR/sessions"

# -------- settings.json (0444 — IT-managed) --------
if [ -f "$MANAGED_TEMPLATE" ]; then
    install -m 0444 "$MANAGED_TEMPLATE" "$SOPIFY_DIR/settings.json"
    echo "settings.json: copied from $MANAGED_TEMPLATE"
else
    cat > "$SOPIFY_DIR/settings.json" <<EOF
{
  "provider_chain": $PROVIDER_CHAIN,
  "otel_endpoint": "$OTEL_ENDPOINT",
  "allowed_domains": [
    "confluence.gsbattery.local",
    "jira.gsbattery.local"
  ],
  "daily_token_budgets": {
    "living": 300000,
    "vibe": 200000,
    "code-with-you": 50000
  },
  "log_user_prompts": false,
  "sandbox_enabled": true,
  "org_id": "gsbattery",
  "phase": 1
}
EOF
    chmod 0444 "$SOPIFY_DIR/settings.json"
    echo "settings.json: wrote default IT-managed config"
fi

# -------- profile.json (0444 — IT-controlled role) --------
cat > "$SOPIFY_DIR/profile.json" <<EOF
{
  "role": "$ROLE",
  "user": "$USER_EMAIL"
}
EOF
chmod 0444 "$SOPIFY_DIR/profile.json"
echo "profile.json: role=$ROLE user=$USER_EMAIL"

# -------- consent.json (auto-recorded) --------
# REQ-7.4.4 — user was told about audit at hiring; we record consent here
# without prompting again. If user objects later, IT can revoke.
cat > "$SOPIFY_DIR/consent.json" <<EOF
{
  "user": "$USER_EMAIL",
  "ts": $(date +%s),
  "version": 1,
  "auto_recorded_by": "sopify-mass-install"
}
EOF
chmod 0644 "$SOPIFY_DIR/consent.json"
echo "consent.json: auto-recorded (REQ-7.4.4)"

# -------- run the end-user installer --------
echo "Running standard sopify-install.sh..."
exec bash -c "curl -fsSL https://raw.githubusercontent.com/Siam-GS-Battery/sopify/main/scripts/sopify-install.sh | bash"

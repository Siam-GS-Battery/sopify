#!/usr/bin/env bash
# Sopify — one-line installer.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Siam-GS-Battery/sopify/main/scripts/sopify-install.sh | bash
#
# What it does:
#   1. Checks Docker is installed (or guides install).
#   2. Installs uv if missing.
#   3. Clones (or pulls) Sopify into ~/.sopify-app.
#   4. Sets up Python venv via uv sync.
#   5. Symlinks `sopify` into a directory on $PATH.
#   6. Runs `sopify install` to pull/build the sandbox image.
#
# Env overrides:
#   SOPIFY_REPO        git URL (default: https://github.com/Siam-GS-Battery/sopify.git)
#   SOPIFY_BRANCH      branch to install (default: main)
#   SOPIFY_INSTALL_DIR clone target (default: $HOME/.sopify-app)
#   SOPIFY_BIN_DIR     where to put the `sopify` symlink (default: $HOME/.local/bin)

set -euo pipefail

REPO="${SOPIFY_REPO:-https://github.com/Siam-GS-Battery/sopify.git}"
BRANCH="${SOPIFY_BRANCH:-main}"
INSTALL_DIR="${SOPIFY_INSTALL_DIR:-$HOME/.sopify-app}"
BIN_DIR="${SOPIFY_BIN_DIR:-$HOME/.local/bin}"

# ---------- pretty printing ----------
CYAN=$'\033[38;5;51m'
TEAL=$'\033[38;5;45m'
GREY=$'\033[38;5;240m'
RED=$'\033[31m'
BOLD=$'\033[1m'
RESET=$'\033[0m'

say()  { printf "%s%s%s\n" "${CYAN}"  "» $*" "${RESET}"; }
ok()   { printf "%s%s%s\n" "${TEAL}"  "✓ $*" "${RESET}"; }
warn() { printf "%s%s%s\n" "${GREY}"  "  $*" "${RESET}"; }
die()  { printf "%s%s%s\n" "${RED}"   "✗ $*" "${RESET}" >&2; exit 1; }

banner() {
cat <<EOF
${CYAN}       ,       ,${RESET}
${CYAN}      /|    |\\./'.${RESET}
${TEAL}     | |  ,  \\|| ,|${RESET}
${TEAL}     \\  \\_(\\.-""\\//.  _${RESET}
${TEAL}   .-'\`""\`\`"\` _   \` \`-.\`"""--.._${RESET}
${TEAL}   | '~\`      o\\                \`"---"${RESET}

  ${BOLD}${CYAN}☤ Sopify installer${RESET}
  ${TEAL}AI agent + sandbox + 3 modes + org governance${RESET}

EOF
}

# ---------- prereq checks ----------
check_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        die "Docker not installed. Install Docker Desktop first:
        macOS:    https://docs.docker.com/desktop/install/mac-install/
        Linux:    curl -fsSL https://get.docker.com | sudo sh
        Windows:  https://docs.docker.com/desktop/install/windows-install/"
    fi
    if ! docker info >/dev/null 2>&1; then
        warn "Docker installed but daemon not running."
        warn "Start Docker Desktop and re-run this script."
        warn "(Continuing anyway — \`sopify install\` will retry later.)"
        return 0
    fi
    ok "Docker ready: $(docker --version | cut -d',' -f1)"
}

check_uv() {
    if command -v uv >/dev/null 2>&1; then
        ok "uv already installed: $(uv --version)"
        return 0
    fi
    say "Installing uv (Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
    # uv installer drops binary in ~/.local/bin or ~/.cargo/bin.
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    command -v uv >/dev/null || die "uv install failed."
    ok "uv installed: $(uv --version)"
}

check_git() {
    if ! command -v git >/dev/null 2>&1; then
        die "git not installed. Install with:
        macOS:   brew install git
        Linux:   sudo apt-get install -y git"
    fi
    ok "git ready: $(git --version | cut -d' ' -f3)"
}

# ---------- Docker Sandboxes (sbx) — the microVM runtime ----------
# REQ-1.2.1 — Sopify ships with its sandbox backend. The user should not
# have to install sbx separately. We install it here and prompt for
# `sbx login` so the first `sopify dashboard` invocation just works.
install_sbx() {
    if command -v sbx >/dev/null 2>&1; then
        ok "sbx (Docker Sandboxes) already installed"
        return 0
    fi
    say "Installing Docker Sandboxes (sbx) — Sopify's microVM backend..."
    local os
    os="$(uname -s)"
    case "$os" in
        Darwin)
            if ! command -v brew >/dev/null 2>&1; then
                warn "Homebrew not found. Install via https://brew.sh, then re-run."
                warn "(Skipping sbx install — Sopify will fall back to host mode.)"
                return 0
            fi
            brew install docker/tap/sbx 2>&1 | tail -3 || \
                warn "sbx install failed — Sopify falls back to host mode"
            ;;
        Linux)
            if command -v apt-get >/dev/null 2>&1; then
                sudo apt-get update -qq
                sudo apt-get install -y docker-sbx 2>&1 | tail -3 || \
                    warn "apt-get install docker-sbx failed"
                if command -v usermod >/dev/null 2>&1; then
                    sudo usermod -aG kvm "$USER" 2>/dev/null || true
                fi
            else
                warn "Non-Debian Linux detected. Install sbx manually:"
                warn "  https://docs.docker.com/ai/sandboxes/get-started/"
                return 0
            fi
            ;;
        *)
            warn "Unsupported OS '$os' — install sbx manually:"
            warn "  https://docs.docker.com/ai/sandboxes/get-started/"
            return 0
            ;;
    esac
    if command -v sbx >/dev/null 2>&1; then
        ok "sbx installed: $(sbx version 2>&1 | head -1)"
    else
        warn "sbx install did not surface a binary — Sopify will use host mode"
    fi
}

login_sbx() {
    if ! command -v sbx >/dev/null 2>&1; then
        return 0
    fi
    # Detect existing login via the on-disk auth marker so we don't prompt twice.
    local auth_dir="$HOME/Library/Application Support/com.docker.sandboxes/com.docker.sandboxes-auth/sandboxes-auth"
    if [ -d "$auth_dir" ] && find "$auth_dir" -name 'metadata.json' -print -quit | grep -q .; then
        ok "sbx already logged in"
        return 0
    fi
    say "Signing in to Docker Sandboxes (browser will open)..."
    if [ -t 0 ]; then
        # Interactive — let sbx open the browser.
        sbx login || warn "sbx login skipped/failed — run 'sbx login' later to enable microVM mode"
    else
        # Non-interactive (mass deploy) — defer to user.
        warn "Non-interactive shell; run 'sbx login' on your first session to enable microVM mode"
    fi
}

register_sopify_kit() {
    if ! command -v sbx >/dev/null 2>&1; then
        return 0
    fi
    local kit_dir="$INSTALL_DIR/infra/sbx/sopify-kit"
    if [ ! -f "$kit_dir/spec.yaml" ]; then
        warn "Sopify kit not found at $kit_dir — skipping kit validation"
        return 0
    fi
    if sbx kit validate "$kit_dir" >/dev/null 2>&1; then
        ok "Sopify kit validated (17 allowed domains + env passthrough)"
    else
        warn "sbx kit validate failed — microVM mode may still work but check $kit_dir"
    fi
}

# ---------- clone / update ----------
clone_or_update() {
    if [ -d "$INSTALL_DIR/.git" ]; then
        say "Updating existing checkout at $INSTALL_DIR..."
        git -C "$INSTALL_DIR" fetch --quiet origin "$BRANCH"
        git -C "$INSTALL_DIR" checkout --quiet "$BRANCH"
        git -C "$INSTALL_DIR" reset --hard --quiet "origin/$BRANCH"
        ok "Updated to $(git -C "$INSTALL_DIR" rev-parse --short HEAD)"
    else
        say "Cloning Sopify from $REPO ($BRANCH) → $INSTALL_DIR..."
        git clone --quiet --depth 1 --branch "$BRANCH" "$REPO" "$INSTALL_DIR"
        ok "Cloned to $INSTALL_DIR"
    fi
}

# ---------- python env ----------
setup_venv() {
    say "Setting up Python venv via uv sync..."
    # `web` -> sopify dashboard (fastapi + uvicorn)
    # `cli` -> interactive TUI menu helper
    # `anthropic` -> default provider importable on first chat
    # `pty` -> ptyprocess so the in-browser /chat tab works
    (cd "$INSTALL_DIR" && uv sync --quiet \
        --extra web --extra cli --extra anthropic --extra pty 2>&1 | tail -3) || \
        warn "uv sync had warnings — continuing anyway"
    ok "venv ready at $INSTALL_DIR/.venv"
}

# ---------- wrapper script ----------
# Write a wrapper (not a symlink) so we can explicitly use the venv Python.
# A symlink inherits the user's system python3, which on macOS is 3.9 and
# is too old for the Hermes runtime (needs 3.10+ for PEP 604 syntax).
write_wrapper() {
    mkdir -p "$BIN_DIR"
    local target="$BIN_DIR/sopify"
    # Remove any stale symlink from older installs.
    [ -L "$target" ] && rm -f "$target"
    cat > "$target" <<WRAPPER_EOF
#!/usr/bin/env bash
# sopify wrapper - generated by sopify-install.sh.
# Uses the venv Python so we get 3.10+ regardless of system /usr/bin/python3.
SOPIFY_APP="$INSTALL_DIR"
PYTHON="\$SOPIFY_APP/.venv/bin/python"
if [ ! -x "\$PYTHON" ]; then
    for cand in python3.13 python3.12 python3.11 python3.10; do
        if command -v "\$cand" >/dev/null 2>&1; then
            PYTHON="\$(command -v "\$cand")"
            break
        fi
    done
    if [ ! -x "\$PYTHON" ]; then
        echo "sopify: no Python 3.10+ found. Run 'uv sync' in \$SOPIFY_APP." >&2
        exit 127
    fi
fi
exec "\$PYTHON" "\$SOPIFY_APP/sopify" "\$@"
WRAPPER_EOF
    chmod +x "$target"
    chmod +x "$INSTALL_DIR/sopify"
    ok "Wrote wrapper $target (uses venv Python)"

    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *)
            warn "$BIN_DIR is not on \$PATH. Add this to ~/.zshrc or ~/.bashrc:"
            warn "    export PATH=\"$BIN_DIR:\$PATH\""
            ;;
    esac
}

# ---------- run sandbox install ----------
run_sopify_install() {
    say "Running \`sopify install\` to set up the sandbox..."
    # Use the venv Python directly to bypass the system python3.9 trap.
    local py="$INSTALL_DIR/.venv/bin/python"
    if [ ! -x "$py" ]; then
        py="$(command -v python3.13 || command -v python3.12 || \
              command -v python3.11 || command -v python3.10 || \
              command -v python3)"
    fi
    if "$py" "$INSTALL_DIR/sopify" install; then
        ok "Sandbox ready."
    else
        warn "Sandbox install had issues — run \`sopify doctor\` to inspect."
    fi
}

# ---------- post-install hint ----------
final_message() {
cat <<EOF

  ${BOLD}${CYAN}Sopify installed.${RESET}

  Next steps (in a NEW terminal so \$PATH picks up):

  ${TEAL}1. Add an API key:${RESET}      sopify login
  ${TEAL}2. Confirm health:${RESET}      sopify doctor
  ${TEAL}3. Open the dashboard:${RESET}  sopify dashboard

  Read the manual:  $INSTALL_DIR/docs/sopify/TUTORIAL.md

EOF
}

# ---------- main ----------
banner
say "Checking prerequisites..."
check_docker
check_uv
check_git
install_sbx
echo
clone_or_update
setup_venv
write_wrapper
echo
register_sopify_kit
login_sbx
echo
run_sopify_install
final_message

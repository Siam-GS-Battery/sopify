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
    (cd "$INSTALL_DIR" && uv sync --quiet 2>&1 | tail -3) || \
        warn "uv sync had warnings — continuing anyway"
    ok "venv ready at $INSTALL_DIR/.venv"
}

# ---------- symlink ----------
symlink_sopify() {
    mkdir -p "$BIN_DIR"
    local target="$BIN_DIR/sopify"
    ln -sf "$INSTALL_DIR/sopify" "$target"
    chmod +x "$INSTALL_DIR/sopify"
    ok "Symlinked sopify → $target"

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
    if "$INSTALL_DIR/sopify" install; then
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
echo
clone_or_update
setup_venv
symlink_sopify
echo
run_sopify_install
final_message

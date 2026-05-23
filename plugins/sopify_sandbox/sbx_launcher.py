"""Docker Sandboxes (sbx) launcher.

Replaces our custom `docker run sopify-sandbox:latest` path with the
Docker Sandboxes microVM (`sbx run shell`) when the host has `sbx`
installed. microVM isolation is stronger than Docker container layers
(REQ-1.2.1 spirit) and lets IT centrally manage policies via the Docker
Admin Console (REQ-9.1.*).

How it works:
  1. Host has `sbx` CLI + is logged in (`sbx login`).
  2. `sopify install` registered the Sopify kit
     (infra/sbx/sopify-kit/spec.yaml) so the microVM picks up our
     network allowlist + env passthrough + startup commands.
  3. User runs `sopify chat` (or `/vibe`, `/living`, …):
       sbx run shell <cwd> /workspaces/sopify-app:ro -- /usr/local/bin/sopify chat
     `sbx` spins up a microVM, mounts cwd to /workspace, mounts the
     Sopify app dir read-only, applies the kit, then execs sopify
     inside it. stdio is forwarded transparently.
  4. Container exits → microVM stops → no orphans (REQ-1.2.4).

REQ traceability — same as launcher.py, but the sandbox is a microVM
not a container.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

SBX_BINARY = "sbx"
SANDBOX_PREFIX = "sopify"
KIT_DIR_REL = "infra/sbx/sopify-kit"

# AI provider endpoints that must bypass the sbx-injected MCP gateway proxy
# (gateway.docker.internal:3128). Kept in sync with the `no_proxy` value in
# infra/sbx/sopify-kit/spec.yaml — that file is the canonical declaration
# but sbx schema v1 silently drops the env block, so the launcher re-applies
# the same list at exec time. See spec.yaml comment block for full context.
_AI_NO_PROXY = (
    "localhost,127.0.0.1,::1,gateway.docker.internal,"
    "api.anthropic.com,api.openai.com,"
    "openrouter.ai,api.novita.ai,"
    "api-inference.huggingface.co,huggingface.co,"
    "registry.npmjs.org,pypi.org,files.pythonhosted.org,"
    "api.github.com,raw.githubusercontent.com"
)


def is_available() -> bool:
    """Return True if sbx CLI is on PATH."""
    return shutil.which(SBX_BINARY) is not None


def _sopify_app_root() -> Path:
    """Path to the Sopify install (== where this file lives)."""
    return Path(__file__).resolve().parents[2]


def _kit_path() -> Path:
    return _sopify_app_root() / KIT_DIR_REL


def _macos_auth_dir() -> Path:
    return (
        Path.home()
        / "Library" / "Application Support"
        / "com.docker.sandboxes"
        / "com.docker.sandboxes-auth" / "sandboxes-auth"
    )


def is_logged_in() -> bool:
    """Detect sbx login state via the on-disk credential marker.

    `sbx ls` works but takes ~1.5s — too slow for `sopify doctor` to
    keep its Gate P2 < 3s budget. The auth metadata file exists only
    after successful `sbx login` so we check that first (instant).
    Falls back to a subprocess probe when the file layout is unknown
    (Linux/Windows paths may differ from macOS).
    """
    # macOS — auth metadata files appear under sandboxes-auth/* per workspace
    auth_dir = _macos_auth_dir()
    if auth_dir.is_dir():
        for entry in auth_dir.iterdir():
            if (entry / "metadata.json").is_file():
                return True
        return False

    # Other platforms — fall back to a slow subprocess probe.
    try:
        r = subprocess.run(
            [SBX_BINARY, "ls"],
            capture_output=True, text=True, timeout=3,
        )
        return r.returncode == 0
    except Exception:
        return False


def _sandbox_name_for_cwd() -> str:
    """Stable name per cwd so repeated `sopify chat` reuses the same sandbox."""
    import hashlib
    h = hashlib.sha1(str(Path.cwd()).encode()).hexdigest()[:10]
    return f"{SANDBOX_PREFIX}-{h}"


def _sandbox_exists(name: str) -> bool:
    try:
        r = subprocess.run(
            [SBX_BINARY, "ls"], capture_output=True, text=True, timeout=3,
        )
        return r.returncode == 0 and any(
            line.split()[0] == name for line in r.stdout.splitlines()[1:] if line.strip()
        )
    except Exception:
        return False


def _sandbox_has_sopify(name: str) -> bool:
    """True if the running sandbox was built from sopify-sandbox image.

    We probe for /usr/local/bin/sopify which only exists in our custom image.
    Stale sandboxes created before --template flow landed will lack it.
    """
    try:
        r = subprocess.run(
            [SBX_BINARY, "exec", name, "test", "-x", "/usr/local/bin/sopify"],
            capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def _remove_sandbox(name: str) -> None:
    subprocess.run(
        [SBX_BINARY, "rm", "--force", name],
        capture_output=True, timeout=15,
    )


def _open_browser_when_ready(port: int, max_wait_seconds: int = 30) -> None:
    """Open the host browser after FastAPI inside the microVM is reachable.

    Sandbox publishes the port to the host immediately, but FastAPI takes
    a few seconds to import deps + bind. Spin a daemon thread that polls
    and opens the browser when the port answers. Falls back silently if
    the wait expires or we're on a headless host.
    """
    import socket
    import threading
    import time
    import webbrowser

    def _wait_then_open():
        url = f"http://127.0.0.1:{port}"
        deadline = time.time() + max_wait_seconds
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    webbrowser.open(url)
                    return
            except OSError:
                time.sleep(0.5)

    threading.Thread(target=_wait_then_open, name="sopify-open-browser",
                     daemon=True).start()


SOPIFY_IMAGE = "sopify-sandbox:latest"


def _image_exists() -> bool:
    """True when the Linux sopify-sandbox image is available locally."""
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", SOPIFY_IMAGE],
            capture_output=True, timeout=2,
        )
        return r.returncode == 0
    except Exception:
        return False


def _ensure_sandbox(name: str, workspaces: List[str]) -> int:
    """Create the sandbox if it doesn't exist. Returns rc.

    Uses the pre-built sopify-sandbox:latest image (--template) so the
    microVM boots with all Sopify Python deps already installed for
    Linux — no per-launch `uv sync` overhead and the host's macOS venv
    is irrelevant inside the microVM.
    """
    if _sandbox_exists(name):
        return 0
    argv = [SBX_BINARY, "create", "shell", *workspaces, "--name", name]
    if _image_exists():
        argv.extend(["--template", SOPIFY_IMAGE])
    kit = _kit_path()
    if kit.exists():
        argv.extend(["--kit", str(kit)])
    return subprocess.call(argv)


def _publish_port(name: str, host_port: int, sbx_port: int) -> int:
    """Publish a port. Returns rc (0 = ok, non-zero may mean already published)."""
    return subprocess.call(
        [SBX_BINARY, "ports", name, "--publish", f"{host_port}:{sbx_port}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _link_hermes_into_sandbox(name: str) -> None:
    """Symlink the mounted host ~/.hermes/.env into the sopify user's $HOME.

    sbx kit schema v1 only parses `network.allowedDomains` — its `startup`
    block is silently ignored. So instead of relying on kit-time symlinking,
    we run the link command via `sbx exec` right after sandbox creation
    (before Hermes' env_loader reads the .env at dashboard launch).

    The mount path inside the microVM is the host's absolute path (sbx
    preserves it). Probe the standard macOS / Linux home locations and
    link the first match into the sopify user's $HOME/.hermes/.
    """
    script = r"""
mkdir -p "$HOME/.hermes"
hermes_src=""
for candidate in /Users/*/.hermes /home/*/.hermes /root/.hermes; do
  if [ -d "$candidate" ] && [ "$candidate" != "$HOME/.hermes" ]; then
    hermes_src="$candidate"
    break
  fi
done
if [ -n "$hermes_src" ]; then
  for f in .env auth.json; do
    if [ -e "$hermes_src/$f" ]; then
      ln -sf "$hermes_src/$f" "$HOME/.hermes/$f"
    fi
  done
fi
"""
    subprocess.run(
        [SBX_BINARY, "exec", name, "bash", "-lc", script],
        capture_output=True, timeout=15,
    )


def spawn(argv: List[str], *, with_kit: bool = True,
          publish_ports: Optional[List[int]] = None) -> int:
    """Run argv inside an sbx microVM. Returns the exit code.

    Flow:
      1. `sbx create shell <cwd> <app>:ro --name X --kit <kit>`  (if missing)
      2. `sbx ports X --publish 9119:9119`                       (per port)
      3. `sbx run X -- bash -c "/usr/local/bin/sopify <argv>"`   (attach)

    Args:
      argv: command + args to run inside the sandbox (e.g. ["chat"]).
      with_kit: apply the Sopify kit at creation time.
      publish_ports: ports to publish from microVM to host (e.g. [9119]).
    """
    if not is_available():
        print("sopify: `sbx` not installed. Install via:", file=sys.stderr)
        print("  macOS:   brew install docker/tap/sbx", file=sys.stderr)
        print("  Linux:   sudo apt-get install docker-sbx", file=sys.stderr)
        print("  Windows: winget install -h Docker.sbx", file=sys.stderr)
        print("Then run `sbx login` and retry.", file=sys.stderr)
        return 127

    if not is_logged_in():
        print("sopify: `sbx login` required. Run:", file=sys.stderr)
        print("  sbx login", file=sys.stderr)
        return 13

    cwd_resolved = Path.cwd().resolve()
    cwd = str(cwd_resolved)
    app_root_resolved = _sopify_app_root().resolve()
    sandbox = _sandbox_name_for_cwd()

    # 1. Ensure sandbox exists with the right template (idempotent).
    #
    # Workspace mounts:
    #   - cwd          (rw, primary)  — user's project
    #   - app_root :ro                 — installed Sopify source (sopify
    #     command + plugins). Skip when cwd == app_root (dev mode where
    #     the user runs sopify from inside the repo, or has symlinked
    #     ~/.sopify-app → source repo). sbx rejects duplicate workspaces.
    #   - ~/.hermes :ro                — host .env / auth.json so the
    #     microVM's env_loader sees the user's ANTHROPIC_TOKEN.
    workspaces = [cwd]
    if app_root_resolved != cwd_resolved:
        workspaces.append(f"{app_root_resolved}:ro")
    hermes_home = Path.home() / ".hermes"
    if hermes_home.is_dir() and hermes_home.resolve() != cwd_resolved:
        workspaces.append(f"{hermes_home}:ro")
    if _sandbox_exists(sandbox) and _image_exists() and not _sandbox_has_sopify(sandbox):
        # Stale sandbox from before --template support landed. Recreate.
        print(f"sopify: recreating sandbox '{sandbox}' with sopify-sandbox template...",
              file=sys.stderr)
        _remove_sandbox(sandbox)
    rc = _ensure_sandbox(sandbox, workspaces)
    if rc != 0 and not _sandbox_exists(sandbox):
        print(f"sopify: sbx create failed (rc={rc})", file=sys.stderr)
        return rc

    # 1b. Link mounted host ~/.hermes/ into the sopify user's $HOME so
    #     Hermes' env_loader picks up ANTHROPIC_TOKEN at dashboard launch.
    #     sbx kit `startup` blocks are silently dropped (schema v1 only
    #     parses network.allowedDomains), so we run the symlink ourselves.
    _link_hermes_into_sandbox(sandbox)

    # 2. Publish each requested port.
    if publish_ports:
        for p in publish_ports:
            _publish_port(sandbox, p, p)  # ignore rc — already-published returns non-zero

    # 2b. When launching the dashboard, open the host browser to the
    #     published port after a short delay so FastAPI inside the microVM
    #     has time to bind. The microVM is started with --no-open so the
    #     browser-open responsibility lives here on the host.
    if publish_ports and 9119 in publish_ports:
        _open_browser_when_ready(9119)

    # 3. Build inner command — invoke sopify wrapper (set up by kit's startup
    #    script as /usr/local/bin/sopify) with the user's argv.
    #
    #    Workaround for sbx kit schema v1: only `network.allowedDomains` is
    #    parsed from spec.yaml; the `env:` block (which declares no_proxy +
    #    skipIfEnv passthroughs) is silently ignored. Without it the microVM
    #    boots with sbx defaults:
    #      ANTHROPIC_API_KEY="proxy-managed"  ← sentinel, not a real key
    #      https_proxy=http://gateway.docker.internal:3128  (TLS-intercept,
    #        self-signed CA → SDK verify fails → HTTP 000, chat goes silent)
    #    Re-apply the spec.yaml env contract here at exec time so all child
    #    processes (FastAPI → node PTY → tui_gateway → slash_worker) inherit
    #    a working configuration. auth_override.apply() then pulls the real
    #    ANTHROPIC_TOKEN from ~/.hermes/.env (sentinel triggers fallback).
    inner_cmd = (
        f"export no_proxy={_shellquote(_AI_NO_PROXY)}; "
        f"export NO_PROXY={_shellquote(_AI_NO_PROXY)}; "
        'if [ "$ANTHROPIC_API_KEY" = "proxy-managed" ]; then unset ANTHROPIC_API_KEY; fi; '
        "/usr/local/bin/sopify " + " ".join(_shellquote(a) for a in argv)
    )

    # `sbx run SANDBOX -- ...` passes args to the SHELL AGENT itself (which
    # is already bash), so `-- bash -lc X` becomes `bash bash -lc X` and
    # bash tries to interpret its own binary as a script (rc=126).
    # `sbx exec` is the right call — it runs an arbitrary command inside
    # the running sandbox, starting it first if needed.
    try:
        return subprocess.call([
            SBX_BINARY, "exec", "-it", sandbox,
            "bash", "-lc", inner_cmd,
        ])
    except KeyboardInterrupt:
        return 130


def _shellquote(s: str) -> str:
    """Minimal shell-quote — wrap in single quotes, escape embedded quotes."""
    if not s:
        return "''"
    if all(c.isalnum() or c in "_./-:=" for c in s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


def status_summary() -> str:
    """Used by `sopify doctor` — one-line status of sbx readiness."""
    if not is_available():
        return "sbx not installed"
    if not is_logged_in():
        return "sbx installed; `sbx login` required"
    try:
        # 2.5s — sbx version can be slow on cold daemon, especially first
        # call of the session. Still under the doctor 3s gate via parallelism.
        v = subprocess.check_output([SBX_BINARY, "version"], text=True, timeout=2.5)
        for line in v.splitlines():
            if "Client Version" in line:
                return f"sbx OK ({line.split(':',1)[1].strip().split()[0]})"
        return "sbx OK"
    except Exception as exc:
        return f"sbx error: {exc}"

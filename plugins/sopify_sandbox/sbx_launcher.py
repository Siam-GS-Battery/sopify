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

# SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md §3 Week 1 — pin sbx to a tested range.
# Lower bound: 0.24.0 = first version with the `policy` subcommand surface
# our adapter targets. Upper bound: 0.30.0 = next pending breaking release
# we haven't validated yet. Bump these intentionally + regenerate clients +
# rerun contract tests.
SBX_VERSION_MIN = "0.24.0"
SBX_VERSION_MAX = "0.30.0"  # exclusive — `0.30.0` itself untested
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


def _open_browser_now(port: int) -> None:
    """Launch the host browser at the published port. Caller has already
    verified the dashboard answers HTTP — there's no more waiting here.

    WSL note: ``webbrowser.open`` often no-ops because xdg-open isn't
    present; ``wslview`` (from ``wslu``) is the canonical way to punch
    out to the Windows host, with ``cmd.exe /c start`` as a fallback.
    """
    import webbrowser

    url = f"http://127.0.0.1:{port}"
    if _is_wsl():
        if shutil.which("wslview"):
            if subprocess.call(["wslview", url],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL) == 0:
                return
        if shutil.which("cmd.exe"):
            if subprocess.call(["cmd.exe", "/c", "start", "", url],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL) == 0:
                return
    webbrowser.open(url)


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


def _is_wsl() -> bool:
    """True when the launcher runs under WSL (any version).

    Detect via the standard markers: WSL2 sets ``WSL_DISTRO_NAME`` /
    ``WSL_INTEROP``; older WSL1 still produces ``Microsoft`` in
    ``/proc/version``. Errors are non-fatal — when we can't tell, we
    default to "not WSL" and keep the loopback-only bind.
    """
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        with open("/proc/version", "r", encoding="utf-8") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def _publish_bind_host() -> str:
    """Pick the host IP to bind sbx-published ports to.

    Default: ``127.0.0.1`` (loopback only — safest, matches what Jupyter
    does out of the box). On WSL the Docker-published localhost ports
    aren't reliably caught by WSL2's auto-forwarding, so the host browser
    on Windows can't reach them; binding to ``0.0.0.0`` inside WSL fixes
    that without changing the daemon's own bind (which stays loopback).

    Override with ``SOPIFY_PUBLISH_HOST`` env var:
      - ``127.0.0.1``  loopback only (default on macOS/Linux)
      - ``0.0.0.0``    all interfaces (default on WSL, lets Windows reach)
      - any IP         explicit interface
    """
    override = os.environ.get("SOPIFY_PUBLISH_HOST")
    if override:
        return override
    if _is_wsl():
        return "0.0.0.0"
    return "127.0.0.1"


def _sandbox_is_running(name: str) -> bool:
    """Cheap status probe via ``sbx ls`` (~50ms). Used by the publish-when-
    ready thread to time the publish against the main exec coming up."""
    try:
        r = subprocess.run(
            [SBX_BINARY, "ls"], capture_output=True, text=True, timeout=3,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    if r.returncode != 0:
        return False
    for line in r.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[0] == name:
            return parts[2] == "running"
    return False


def _publish_ports_when_ready(
    name: str,
    ports: List[int],
    *,
    open_browser_on: Optional[int],
    max_wait_seconds: int = 180,
) -> None:
    """Keep ports published until the dashboard actually answers HTTP.

    sbx cycles the sandbox container between ``sbx exec`` calls — a publish
    issued during our setup exec (link_hermes) gets silently cleared by
    the time the main exec starts the dashboard process. The thread now
    re-publishes on a cadence and verifies it stuck via an HTTP probe
    against the published port from the host's side. Once a 2xx/3xx comes
    back the dashboard is genuinely reachable and we hand off to the
    browser-open helper.

    Why HTTP-from-host (not just ``sbx ports`` listing): listing only tells
    us our publish request was accepted at *some* point — sbx clears it on
    container restart without notifying us. An HTTP round-trip from the
    host is the only signal that confirms the chain
    (host → docker port-proxy → sandbox network → hermes) is intact.
    """
    import threading
    import time
    import urllib.error
    import urllib.request

    if open_browser_on is not None:
        print(
            f"sopify: dashboard URL → http://127.0.0.1:{open_browser_on}",
            file=sys.stderr,
        )
        sys.stderr.flush()

    def _host_can_reach(port: int) -> bool:
        """True when an HTTP request from the host to the published port
        gets a real status line (not the Docker proxy hang)."""
        for path in ("/health", "/"):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}{path}", timeout=1.5
                ) as resp:
                    if 200 <= resp.status < 400:
                        return True
            except urllib.error.HTTPError as exc:
                # FastAPI replied with 4xx/5xx → still proof of life.
                if exc.code >= 400:
                    return True
            except (urllib.error.URLError, TimeoutError, OSError):
                continue
        return False

    def _worker() -> None:
        deadline = time.time() + max_wait_seconds
        start = time.time()
        next_progress = start + 5
        last_publish_at = 0.0
        announced_publish = False
        attempts = 0
        while time.time() < deadline:
            attempts += 1
            running = _sandbox_is_running(name)
            if running:
                # Re-publish at most every 3s. Each publish round-trips
                # ``sbx ports --publish`` which costs ~100ms, so don't
                # hammer; but do it often enough that a container cycle
                # is corrected within seconds.
                if time.time() - last_publish_at > 3.0:
                    for p in ports:
                        rc = _publish_port(name, p, p)
                        if rc == 0 and not announced_publish:
                            print(
                                f"sopify: port {p} published to host "
                                f"({_publish_bind_host()}:{p})",
                                file=sys.stderr,
                            )
                            sys.stderr.flush()
                            announced_publish = True
                    last_publish_at = time.time()

                if open_browser_on is not None and _host_can_reach(open_browser_on):
                    elapsed = time.time() - start
                    print(
                        f"sopify: dashboard ready after {elapsed:.1f}s "
                        f"({attempts} probes) — opening "
                        f"http://127.0.0.1:{open_browser_on}",
                        file=sys.stderr,
                    )
                    sys.stderr.flush()
                    _open_browser_now(open_browser_on)
                    return
                if open_browser_on is None:
                    # No browser to wait for; one publish round suffices.
                    return

            if time.time() >= next_progress:
                elapsed = int(time.time() - start)
                state = "running" if running else "starting"
                print(
                    f"sopify: still waiting ({elapsed}s, {attempts} probes) — "
                    f"sandbox {state}, dashboard not responding yet",
                    file=sys.stderr,
                )
                sys.stderr.flush()
                next_progress = time.time() + 5
            time.sleep(1.0)

        print(
            f"sopify: dashboard never responded after {max_wait_seconds}s — "
            f"try `curl http://127.0.0.1:{open_browser_on or ports[0]}/` "
            "and `sbx ports` to debug",
            file=sys.stderr,
        )

    threading.Thread(target=_worker, name="sopify-publish-ports",
                     daemon=True).start()

    threading.Thread(target=_worker, name="sopify-publish-ports",
                     daemon=True).start()


def _publish_port(name: str, host_port: int, sbx_port: int) -> int:
    """Publish a port. Returns rc (0 = ok, non-zero may mean already published).

    Port spec ``HOST_IP:HOST_PORT:SANDBOX_PORT`` — see ``sbx ports --help``.
    Bind interface is chosen by :func:`_publish_bind_host` (loopback-only
    on macOS/Linux, all-interfaces on WSL).

    sbx reaps the sandbox's container quickly between exec calls — if our
    publish lands in the gap we get "no container endpoint with IP address
    found" and the dashboard becomes unreachable. Retry briefly with an
    ``sbx exec`` poke to revive the container; surface the final error
    (no more silent failure) so users can see what went wrong.
    """
    bind_host = _publish_bind_host()
    spec = f"{bind_host}:{host_port}:{sbx_port}"
    last_stderr = ""
    for attempt in range(3):
        result = subprocess.run(
            [SBX_BINARY, "ports", name, "--publish", spec],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            if attempt > 0:
                print(
                    f"sopify: published {spec} on attempt {attempt + 1}",
                    file=sys.stderr,
                )
            return 0
        last_stderr = (result.stderr or "").strip()
        # "already published" is benign — the port is mapped, we're just
        # restating it. The caller's HTTP probe is the real signal anyway.
        if "already published" in last_stderr:
            return 0
        # "no container endpoint" = the sandbox's container has been
        # reaped between exec calls. A noop exec brings it back; then
        # retry the publish in the same tight window.
        if "no container endpoint" in last_stderr and attempt < 2:
            subprocess.run(
                [SBX_BINARY, "exec", name, "true"],
                capture_output=True, timeout=10,
            )
            continue
        break
    if last_stderr:
        print(
            f"sopify: failed to publish {spec}: {last_stderr}",
            file=sys.stderr,
        )
    return 1


def _link_hermes_into_sandbox(name: str) -> None:
    """Symlink the mounted host ~/.hermes/{.env, auth.json, state.db} into the
    sopify user's $HOME and (if mounted) re-link ``/usr/local/bin/sopify`` to
    the host's dev repo so code edits are live without rebuilding the image.

    Sharing ``state.db`` is what makes the dashboard's Token Status / analytics
    show real usage — otherwise the microVM reads an empty sandbox-local DB.

    sbx kit schema v1 only parses `network.allowedDomains` — its `startup`
    block is silently ignored. So instead of relying on kit-time symlinking,
    we run the link commands via ``sbx exec`` right after sandbox creation
    (before Hermes' env_loader reads the .env at dashboard launch).

    **Dev-mode override (sopify symlink):** the spec.yaml startup expects
    the dev repo at ``/workspaces/sopify-app/`` and falls back to the baked
    ``/opt/sopify/`` when missing. sbx, however, mounts workspaces at the
    *host's* absolute path (not at ``/workspaces/...``), so the fallback
    always wins — meaning host edits to ``hermes_cli/`` or ``web_dist/``
    never reach the running dashboard until the sandbox image is rebuilt.
    Probe each mounted workspace for a ``sopify`` executable and re-link
    ``/usr/local/bin/sopify`` to it when found, falling back to ``/opt``.
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
  # .env / auth.json  — credentials the env_loader + dashboard API-key form need.
  # state.db          — the session history DB. Without it the sandboxed
  #   dashboard reads an empty sandbox-local DB, so Token Status / analytics
  #   always show zero even when the host has real usage. Symlinking shares the
  #   one DB so analytics (and sessions started inside the sandbox) reflect the
  #   host's real history. Safe here: ~/.hermes is already rw-mounted and sopify
  #   is single-user, so there is no competing writer to race the SQLite WAL.
  # kanban.db          — the Kanban board DB. Same reasoning as state.db: a
  #   sandbox-local copy makes the dashboard's /kanban tab show an empty board
  #   even when the host has cards. Share the one file so boards persist.
  for f in .env auth.json state.db kanban.db; do
    if [ -e "$hermes_src/$f" ]; then
      ln -sf "$hermes_src/$f" "$HOME/.hermes/$f"
    fi
  done
  # vibe-projects/  — user-created Vibe Code apps. These are a DIRECTORY of
  #   real project trees, not a single file. Until this was linked they were
  #   written to the sandbox-local $HOME/.hermes/vibe-projects, which lives on
  #   the ephemeral container fs — so every sandbox recreate silently wiped
  #   every project ("No projects yet"). Point it at the rw host mount so apps
  #   survive. `ln -sf` into an existing dir would nest the link inside it, so
  #   migrate any not-yet-persisted projects, drop the local dir, then link.
  mkdir -p "$hermes_src/vibe-projects"
  vp="$HOME/.hermes/vibe-projects"
  if [ -d "$vp" ] && [ ! -L "$vp" ]; then
    cp -an "$vp/." "$hermes_src/vibe-projects/" 2>/dev/null || true
    rm -rf "$vp"
  fi
  ln -sfn "$hermes_src/vibe-projects" "$vp"
fi

# Make the Hermes-managed Anthropic config reach the `claude` CLI. sbx runs
# every command via ``bash -lc`` (login shell), which sources ~/.profile, so
# appending an env block there means `claude` — whether spawned by sopify or
# run directly inside the sandbox — inherits ANTHROPIC_BASE_URL plus a
# Claude-Code-compatible credential. The single source of truth is the linked
# ~/.hermes/.env (the dashboard /env page writes ANTHROPIC_BASE_URL there in
# PR 1.3). Idempotent: a marker guard keeps repeated launches from stacking
# duplicate blocks. NOTE: when ANTHROPIC_BASE_URL points at a relay host that
# is not already in _AI_NO_PROXY (api.anthropic.com / openrouter.ai / ... are),
# that host must be added there too or its traffic hits the gateway proxy.
profile="$HOME/.profile"
if ! grep -qF '# >>> sopify claude-code env (PR 1.2) >>>' "$profile" 2>/dev/null; then
  cat >> "$profile" <<'PROFILE_EOF'

# >>> sopify claude-code env (PR 1.2) >>>
# Share the Hermes-managed Anthropic config with Claude Code, which reads
# ANTHROPIC_BASE_URL + ANTHROPIC_API_KEY from its environment. Values come
# from the linked ~/.hermes/.env (written via the dashboard /env page).
__hermes_env="$HOME/.hermes/.env"
if [ -f "$__hermes_env" ]; then
  for __k in ANTHROPIC_BASE_URL ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_TOKEN CLAUDE_CODE_OAUTH_TOKEN; do
    __v=$(grep -E "^[[:space:]]*${__k}=" "$__hermes_env" 2>/dev/null | tail -n1 | cut -d= -f2-)
    __v=${__v%\"}; __v=${__v#\"}; __v=${__v%\'}; __v=${__v#\'}
    [ -n "$__v" ] && export "${__k}=${__v}"
  done
  # Hermes writes the "proxy-managed" sentinel when the real key lives elsewhere.
  [ "$ANTHROPIC_API_KEY" = "proxy-managed" ] && unset ANTHROPIC_API_KEY
  # Claude Code authenticates via ANTHROPIC_API_KEY; fall back to Hermes' token.
  if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -n "${ANTHROPIC_TOKEN:-}" ]; then
    export ANTHROPIC_API_KEY="$ANTHROPIC_TOKEN"
  fi
  unset __hermes_env __k __v
fi
# <<< sopify claude-code env (PR 1.2) <<<
PROFILE_EOF
fi

# Dev-mode override decision is taken at exec-time inside ``inner_cmd``
# below, not here — the sopify user has no write access to
# /usr/local/bin so we can't rewrite the baked wrapper. Just record the
# detected path so the user sees what's going on.
dev_sopify=""
for candidate in \
    /Users/*/ai_engineer/*/project-based/sopify/sopify-harness/sopify \
    /Users/*/sopify/sopify-harness/sopify \
    /Users/*/sopify-harness/sopify \
    /home/*/sopify-harness/sopify \
    /workspaces/sopify-app/sopify; do
  if [ -x "$candidate" ]; then
    dev_sopify="$candidate"
    break
  fi
done
if [ -n "$dev_sopify" ]; then
  echo "sopify: dev-mode detected → $dev_sopify" >&2
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
    #   - ~/.hermes (rw, default)      — host .env / auth.json so the
    #     microVM's env_loader sees the user's ANTHROPIC_TOKEN, AND so the
    #     dashboard's API-key form (token-protected `/api/providers/api-key`)
    #     can persist new keys back to the host's ~/.hermes/.env without
    #     bouncing the user out to a host terminal.  sbx workspaces default
    #     to rw; an explicit ``:rw`` suffix is NOT recognised and silently
    #     creates a sibling dir literally named ``.hermes:rw`` — use a bare
    #     path here.  Trade-off: the agent's shell tools could in principle
    #     overwrite credentials too — accepted because the dashboard UX
    #     requires it and the trust boundary is "user-owned host" anyway.
    #     For stricter isolation, run `sopify dashboard --no-sandbox`.
    workspaces = [cwd]
    if app_root_resolved != cwd_resolved:
        workspaces.append(f"{app_root_resolved}:ro")
    hermes_home = Path.home() / ".hermes"
    if hermes_home.is_dir() and hermes_home.resolve() != cwd_resolved:
        workspaces.append(str(hermes_home))
    # ~/.sopify/ holds the daemon's bearer token + port (config.yaml). The
    # dashboard's ENCM proxy (hermes_cli/encm_client.py) reads it to forward
    # /api/encm/* to the daemon on the host at 127.0.0.1:7777. Without this
    # mount the proxy returns 503 "config not found" and the /network page
    # falls into its daemon-down empty state. Read-only is enough — the
    # daemon, which writes this file, runs on the host, not in the microVM.
    sopify_home = Path.home() / ".sopify"
    if sopify_home.is_dir() and sopify_home.resolve() != cwd_resolved:
        workspaces.append(f"{sopify_home}:ro")
    # ENCM CA mount intentionally removed (2026-05-24) — the MITM-proxy
    # variant of ENCM is archived under archive/2026-05-24-encm-mitm-attempt/.
    # The new ENCM Control Plane talks to sbx's sandboxd API instead of
    # injecting a CA, so the sandbox no longer needs a Sopify-issued trust
    # anchor.
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

    # 2. Defer port publishing to a background thread that fires AFTER the
    #    main ``sbx exec`` boots the container. Doing it here-and-now sees
    #    the container in the brief gap between our setup exec and the
    #    dashboard exec — sbx reaps that container and clears any earlier
    #    publish state, so the dashboard would start with no port mapped.
    #
    #    The thread polls ``sbx ls`` for ``running`` (which the main exec
    #    drives a moment later), publishes, then triggers browser auto-open
    #    once the published port answers. Errors are surfaced to stderr —
    #    silent failure here was the GHSA-class bug that left users staring
    #    at "Connection refused" with no clue why.
    if publish_ports:
        _publish_ports_when_ready(
            sandbox,
            publish_ports,
            open_browser_on=(
                9119
                if 9119 in publish_ports
                and os.environ.get("SOPIFY_NO_BROWSER") != "1"
                else None
            ),
        )

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
    # Force truecolor terminal capability inside the microVM. sbx exec -it
    # allocates a PTY but ships TERM=dumb by default, which makes rich set
    # color_system=None — the banner mascot then renders in monochrome even
    # though the host terminal supports 24-bit color end-to-end.
    # ENCM proxy-chain env exports removed 2026-05-24 — see
    # SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md §1.2 for why the custom-proxy
    # approach is dead. The new ENCM Control Plane runs as a host-side
    # FastAPI daemon talking to sandboxd via Unix socket; no proxy env
    # vars are injected into the sandbox process itself.
    # Dev-mode runtime resolution: prefer the mounted host repo's sopify
    # over the baked /opt/sopify so code edits land without rebuilding the
    # sandbox image. The Linux venv from /opt/sopify is reused — the host's
    # (macOS) .venv would refuse to run inside the microVM.
    #
    # We compute the dev path inline so that:
    #   - permission isn't an issue (no /usr/local/bin rewrites)
    #   - falling back to /usr/local/bin/sopify is automatic
    #   - the user sees ``sopify: dev-mode active …`` when it kicks in
    sopify_argv = " ".join(_shellquote(a) for a in argv)
    # cd into the user's host cwd before exec. sbx mounts that path at the
    # same host absolute path inside the sandbox, so it always exists.
    # Without this, sbx exec lands bash in the image's WORKDIR (/workspace,
    # an empty stub directory) — both the dashboard's Files page root and
    # the chat agent's terminal subprocess end up there instead of the
    # user's actual project, and agent writes either fail (sopify-harness
    # mount is ro) or fall back to /home/sopify (sandbox-only scratch,
    # invisible to the host and to the Files page).
    cd_to_workspace = f"cd {_shellquote(cwd)} 2>/dev/null || true; "
    inner_cmd = (
        cd_to_workspace
        + "export COLORTERM=truecolor; "
        "export TERM=xterm-256color; "
        # Pin Python to the Sopify venv so any subprocess (in particular
        # the TUI's ``python -m tui_gateway.entry`` child, spawned with
        # ``stdio: pipe`` rather than a login shell) picks up the
        # installed deps — ``dotenv``, ``rich``, etc. The default PATH
        # inside the microVM is ``/usr/local/bin:/usr/bin:/bin`` and
        # does NOT contain ``/opt/sopify/.venv/bin``, so a bare
        # ``python3`` falls back to system Python which is missing every
        # package and the gateway crashes with ModuleNotFoundError before
        # ever emitting ``gateway.ready``. Pinning ``HERMES_PYTHON``
        # plus prepending the venv to ``PATH`` covers both the TUI
        # spawn path and any other ``python``-by-name shell-outs.
        "export HERMES_PYTHON=/opt/sopify/.venv/bin/python3; "
        "export PATH=/opt/sopify/.venv/bin:$PATH; "
        # Enable gateway-lifecycle trace logging so the chat tab's
        # "gateway exited" bug leaves a paper trail in stderr (visible
        # via the dashboard PTY mirror and ~/.hermes/logs/agent.log).
        # See ui-tui/src/gatewayClient.ts ``_trace()``.
        "export SOPIFY_TUI_TRACE=1; "
        f"export no_proxy={_shellquote(_AI_NO_PROXY)}; "
        f"export NO_PROXY={_shellquote(_AI_NO_PROXY)}; "
        'if [ "$ANTHROPIC_API_KEY" = "proxy-managed" ]; then unset ANTHROPIC_API_KEY; fi; '
        # Resolve dev sopify path. ``set -- <glob>`` expands; ``$1`` is the
        # first match (empty if no match because nullglob isn't on).
        "DEV_SOPIFY=''; "
        "for c in "
        "/Users/*/ai_engineer/*/project-based/sopify/sopify-harness/sopify "
        "/Users/*/sopify/sopify-harness/sopify "
        "/Users/*/sopify-harness/sopify "
        "/home/*/sopify-harness/sopify "
        "/workspaces/sopify-app/sopify; do "
        '  if [ -x "$c" ]; then DEV_SOPIFY="$c"; break; fi; '
        "done; "
        # When running the dev sopify from a host-mounted repo, the
        # ui-tui/node_modules belongs to the host platform (macOS) and
        # esbuild's prebuilt binaries refuse to execute inside the Linux
        # microVM. Skip the in-sandbox esbuild step by pointing
        # HERMES_TUI_DIR at the host-built ``dist/entry.js`` — hermes_cli
        # picks the prebuilt branch and never invokes node_modules/.
        'if [ -n "$DEV_SOPIFY" ]; then '
        '  DEV_ROOT="$(dirname "$DEV_SOPIFY")"; '
        '  if [ -f "$DEV_ROOT/ui-tui/dist/entry.js" ]; then '
        '    export HERMES_TUI_DIR="$DEV_ROOT/ui-tui"; '
        '    echo "sopify: HERMES_TUI_DIR=$HERMES_TUI_DIR (skipping in-sandbox esbuild)" >&2; '
        '  fi; '
        '  echo "sopify: dev-mode active → $DEV_SOPIFY" >&2; '
        f'  exec /opt/sopify/.venv/bin/python "$DEV_SOPIFY" {sopify_argv}; '
        "fi; "
        f"exec /usr/local/bin/sopify {sopify_argv}"
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


def _parse_semver(v: str) -> tuple[int, int, int] | None:
    """Best-effort semver tuple extraction. Returns None for non-semver
    strings rather than raising — doctor must remain non-fatal."""
    import re
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", v)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _version_in_range(detected: str) -> tuple[bool, str]:
    """True iff `detected` is within [SBX_VERSION_MIN, SBX_VERSION_MAX).

    Returns (ok, friendly_reason) so doctor can surface why the version
    failed without reimplementing the comparison logic.
    """
    det = _parse_semver(detected)
    lo = _parse_semver(SBX_VERSION_MIN)
    hi = _parse_semver(SBX_VERSION_MAX)
    if det is None or lo is None or hi is None:
        return True, "version unparseable, skipping range check"
    if det < lo:
        return False, f"too old (need ≥ {SBX_VERSION_MIN})"
    if det >= hi:
        return False, f"too new (untested, max < {SBX_VERSION_MAX})"
    return True, "in supported range"


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
        client_ver = ""
        for line in v.splitlines():
            if "Client Version" in line:
                client_ver = line.split(":", 1)[1].strip().split()[0]
                break
        if not client_ver:
            return "sbx OK"
        # `sbx version` may report "v0.29.0" or "0.29.0" depending on the
        # release tag style — normalise so the doctor row reads cleanly.
        normalised = client_ver.lstrip("vV")
        ok, why = _version_in_range(normalised)
        if not ok:
            return f"sbx v{normalised} — {why}"
        return f"sbx OK (v{normalised})"
    except Exception as exc:
        return f"sbx error: {exc}"

"""
Hermes Agent — Web UI server.

Provides a FastAPI backend serving the Vite/React frontend and REST API
endpoints for managing configuration, environment variables, and sessions.

Usage:
    python -m hermes_cli.main web          # Start on http://127.0.0.1:9119
    python -m hermes_cli.main web --port 8080
"""

import asyncio
import errno
import hmac
import importlib.util
import json
import logging
import mimetypes
import os
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hermes_cli import __version__, __release_date__
from hermes_cli.config import (
    cfg_get,
    DEFAULT_CONFIG,
    OPTIONAL_ENV_VARS,
    get_config_path,
    get_env_path,
    get_hermes_home,
    load_config,
    load_env,
    save_config,
    save_env_value,
    remove_env_value,
    check_config_version,
    redact_key,
)
from gateway.status import get_running_pid, read_runtime_status

try:
    from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError:
    # First try lazy-installing the dashboard extras. Only the user actually
    # running `hermes dashboard` needs fastapi+uvicorn; lazy install keeps
    # them out of every other install path. After install, re-import.
    try:
        from tools.lazy_deps import ensure as _lazy_ensure
        _lazy_ensure("tool.dashboard", prompt=False)
        from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
        from fastapi.staticfiles import StaticFiles
        from pydantic import BaseModel
    except Exception:
        raise SystemExit(
            "Web UI requires fastapi and uvicorn.\n"
            f"Install with: {sys.executable} -m pip install 'fastapi' 'uvicorn[standard]'"
        )

WEB_DIST = Path(os.environ["HERMES_WEB_DIST"]) if "HERMES_WEB_DIST" in os.environ else Path(__file__).parent / "web_dist"
_log = logging.getLogger(__name__)

app = FastAPI(title="Hermes Agent", version=__version__)

# ---------------------------------------------------------------------------
# Session token for protecting sensitive endpoints (reveal).
# Generated fresh on every server start — dies when the process exits.
# Injected into the SPA HTML so only the legitimate web UI can use it.
# ---------------------------------------------------------------------------
_SESSION_TOKEN = secrets.token_urlsafe(32)
_SESSION_HEADER_NAME = "X-Hermes-Session-Token"

# In-browser Chat tab (/chat, /api/pty, …).  Off unless ``hermes dashboard --tui``
# or HERMES_DASHBOARD_TUI=1.  Set from :func:`start_server`.
_DASHBOARD_EMBEDDED_CHAT_ENABLED = False

# Simple rate limiter for the reveal endpoint
_reveal_timestamps: List[float] = []
_REVEAL_MAX_PER_WINDOW = 5
_REVEAL_WINDOW_SECONDS = 30

# CORS: restrict to localhost origins only.  The web UI is intended to run
# locally; binding to 0.0.0.0 with allow_origins=["*"] would let any website
# read/modify config and secrets.

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Endpoints that do NOT require the session token.  Everything else under
# /api/ is gated by the auth middleware below.  Keep this list minimal —
# only truly non-sensitive, read-only endpoints belong here.
# ---------------------------------------------------------------------------
_PUBLIC_API_PATHS: frozenset = frozenset({
    "/api/status",
    "/api/config/defaults",
    "/api/config/schema",
    "/api/model/info",
    "/api/dashboard/plugins",
    "/api/dashboard/plugins/rescan",
})


def _has_valid_session_token_query(request: Request) -> bool:
    """Accept the session token as a `?_token=` query param.

    `<img src>` and `<a href>` can't carry our custom X-Hermes-Session-Token
    header — the browser strips custom headers on subresource loads — so
    endpoints that the UI needs to embed (file downloads, image previews)
    rely on this fallback. Loopback-only by default; for non-loopback binds
    the operator has already opted into the trust posture.
    """
    qs_token = request.query_params.get("_token", "")
    if not qs_token:
        return False
    return hmac.compare_digest(qs_token.encode(), _SESSION_TOKEN.encode())


def _has_valid_session_token(request: Request) -> bool:
    """True if the request carries a valid dashboard session token.

    The dedicated session header avoids collisions with reverse proxies that
    already use ``Authorization`` (for example Caddy ``basic_auth``). We still
    accept the legacy Bearer path for backward compatibility with older
    dashboard bundles.
    """
    session_header = request.headers.get(_SESSION_HEADER_NAME, "")
    if session_header and hmac.compare_digest(
        session_header.encode(),
        _SESSION_TOKEN.encode(),
    ):
        return True

    auth = request.headers.get("authorization", "")
    expected = f"Bearer {_SESSION_TOKEN}"
    return hmac.compare_digest(auth.encode(), expected.encode())


def _require_token(request: Request) -> None:
    """Validate the ephemeral session token.  Raises 401 on mismatch."""
    if not _has_valid_session_token(request):
        raise HTTPException(status_code=401, detail="Unauthorized")


# Accepted Host header values for loopback binds. DNS rebinding attacks
# point a victim browser at an attacker-controlled hostname (evil.test)
# which resolves to 127.0.0.1 after a TTL flip — bypassing same-origin
# checks because the browser now considers evil.test and our dashboard
# "same origin". Validating the Host header at the app layer rejects any
# request whose Host isn't one we bound for. See GHSA-ppp5-vxwm-4cf7.
_LOOPBACK_HOST_VALUES: frozenset = frozenset({
    "localhost", "127.0.0.1", "::1",
})


def _is_accepted_host(host_header: str, bound_host: str) -> bool:
    """True if the Host header targets the interface we bound to.

    Accepts:
    - Exact bound host (with or without port suffix)
    - Loopback aliases when bound to loopback
    - Any host when bound to 0.0.0.0 (explicit opt-in to non-loopback,
      no protection possible at this layer)
    """
    if not host_header:
        return False
    # Strip port suffix. IPv6 addresses use bracket notation:
    #   [::1]         — no port
    #   [::1]:9119    — with port
    # Plain hosts/v4:
    #   localhost:9119
    #   127.0.0.1:9119
    h = host_header.strip()
    if h.startswith("["):
        # IPv6 bracketed — port (if any) follows "]:"
        close = h.find("]")
        if close != -1:
            host_only = h[1:close]  # strip brackets
        else:
            host_only = h.strip("[]")
    else:
        host_only = h.rsplit(":", 1)[0] if ":" in h else h
    host_only = host_only.lower()

    # 0.0.0.0 bind means operator explicitly opted into all-interfaces
    # (requires --insecure per web_server.start_server). No Host-layer
    # defence can protect that mode; rely on operator network controls.
    if bound_host in {"0.0.0.0", "::"}:
        return True

    # Loopback bind: accept the loopback names
    bound_lc = bound_host.lower()
    if bound_lc in _LOOPBACK_HOST_VALUES:
        return host_only in _LOOPBACK_HOST_VALUES

    # Explicit non-loopback bind: require exact host match
    return host_only == bound_lc


@app.middleware("http")
async def host_header_middleware(request: Request, call_next):
    """Reject requests whose Host header doesn't match the bound interface.

    Defends against DNS rebinding: a victim browser on a localhost
    dashboard is tricked into fetching from an attacker hostname that
    TTL-flips to 127.0.0.1. CORS and same-origin checks don't help —
    the browser now treats the attacker origin as same-origin with the
    dashboard. Host-header validation at the app layer catches it.

    See GHSA-ppp5-vxwm-4cf7.
    """
    # Store the bound host on app.state so this middleware can read it —
    # set by start_server() at listen time.
    bound_host = getattr(app.state, "bound_host", None)
    if bound_host:
        host_header = request.headers.get("host", "")
        if not _is_accepted_host(host_header, bound_host):
            return JSONResponse(
                status_code=400,
                content={
                    "detail": (
                        "Invalid Host header. Dashboard requests must use "
                        "the hostname the server was bound to."
                    ),
                },
            )
    return await call_next(request)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Require the session token on all /api/ routes except the public list."""
    path = request.url.path
    if path.startswith("/api/") and path not in _PUBLIC_API_PATHS:
        if not (
            _has_valid_session_token(request)
            or _has_valid_session_token_query(request)
        ):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )
    return await call_next(request)


# ---------------------------------------------------------------------------
# Config schema — auto-generated from DEFAULT_CONFIG
# ---------------------------------------------------------------------------

# Manual overrides for fields that need select options or custom types
_SCHEMA_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "model": {
        "type": "string",
        "description": "Default model (e.g. anthropic/claude-sonnet-4.6)",
        "category": "general",
    },
    "model_context_length": {
        "type": "number",
        "description": "Context window override (0 = auto-detect from model metadata)",
        "category": "general",
    },
    "terminal.backend": {
        "type": "select",
        "description": "Terminal execution backend",
        "options": ["local", "docker", "ssh", "modal", "daytona", "vercel_sandbox", "singularity"],
    },
    "terminal.vercel_runtime": {
        "type": "select",
        "description": "Vercel Sandbox runtime",
        "options": ["node24", "node22", "python3.13"],  # sync with _SUPPORTED_VERCEL_RUNTIMES in terminal_tool.py
    },
    "terminal.modal_mode": {
        "type": "select",
        "description": "Modal sandbox mode",
        "options": ["sandbox", "function"],
    },
    "tts.provider": {
        "type": "select",
        "description": "Text-to-speech provider",
        "options": ["edge", "elevenlabs", "openai", "neutts"],
    },
    "stt.provider": {
        "type": "select",
        "description": "Speech-to-text provider",
        # "mistral" temporarily removed — mistralai PyPI package quarantined
        # (malicious 2.4.6 release on 2026-05-12). Restore once available.
        "options": ["local", "openai"],
    },
    "display.skin": {
        "type": "select",
        "description": "CLI visual theme",
        "options": ["default", "ares", "mono", "slate"],
    },
    "display.resume_display": {
        "type": "select",
        "description": "How resumed sessions display history",
        "options": ["minimal", "full", "off"],
    },
    "display.busy_input_mode": {
        "type": "select",
        "description": "Input behavior while agent is running",
        "options": ["interrupt", "queue", "steer"],
    },
    "memory.provider": {
        "type": "select",
        "description": "Memory provider plugin",
        "options": ["builtin", "honcho"],
    },
    "approvals.mode": {
        "type": "select",
        "description": "Dangerous command approval mode",
        "options": ["ask", "yolo", "deny"],
    },
    "context.engine": {
        "type": "select",
        "description": "Context management engine",
        "options": ["default", "custom"],
    },
    "human_delay.mode": {
        "type": "select",
        "description": "Simulated typing delay mode",
        "options": ["off", "typing", "fixed"],
    },
    "logging.level": {
        "type": "select",
        "description": "Log level for agent.log",
        "options": ["DEBUG", "INFO", "WARNING", "ERROR"],
    },
    "agent.service_tier": {
        "type": "select",
        "description": "API service tier (OpenAI/Anthropic)",
        "options": ["", "auto", "default", "flex"],
    },
    "delegation.reasoning_effort": {
        "type": "select",
        "description": "Reasoning effort for delegated subagents",
        "options": ["", "low", "medium", "high"],
    },
}

# Categories with fewer fields get merged into "general" to avoid tab sprawl.
_CATEGORY_MERGE: Dict[str, str] = {
    "privacy": "security",
    "context": "agent",
    "skills": "agent",
    "cron": "agent",
    "network": "agent",
    "checkpoints": "agent",
    "approvals": "security",
    "human_delay": "display",
    "dashboard": "display",
    "code_execution": "agent",
    "prompt_caching": "agent",
    "goals": "agent",
    # Only `telegram.reactions` currently lives under telegram — fold it in
    # with the other messaging-platform config (discord) so it isn't an
    # orphan tab of one field.
    "telegram": "discord",
}

# Display order for tabs — unlisted categories sort alphabetically after these.
_CATEGORY_ORDER = [
    "general", "agent", "terminal", "display", "delegation",
    "memory", "compression", "security", "browser", "voice",
    "tts", "stt", "logging", "discord", "auxiliary",
]


def _infer_type(value: Any) -> str:
    """Infer a UI field type from a Python value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "number"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "string"


def _build_schema_from_config(
    config: Dict[str, Any],
    prefix: str = "",
) -> Dict[str, Dict[str, Any]]:
    """Walk DEFAULT_CONFIG and produce a flat dot-path → field schema dict."""
    schema: Dict[str, Dict[str, Any]] = {}
    for key, value in config.items():
        full_key = f"{prefix}.{key}" if prefix else key

        # Skip internal / version keys
        if full_key in {"_config_version",}:
            continue

        # Category is the first path component for nested keys, or "general"
        # for top-level scalar fields (model, toolsets, timezone, etc.).
        if prefix:
            category = prefix.split(".")[0]
        elif isinstance(value, dict):
            category = key
        else:
            category = "general"

        if isinstance(value, dict):
            # Recurse into nested dicts
            schema.update(_build_schema_from_config(value, full_key))
        else:
            entry: Dict[str, Any] = {
                "type": _infer_type(value),
                "description": full_key.replace(".", " → ").replace("_", " ").title(),
                "category": category,
            }
            # Apply manual overrides
            if full_key in _SCHEMA_OVERRIDES:
                entry.update(_SCHEMA_OVERRIDES[full_key])
            # Merge small categories
            entry["category"] = _CATEGORY_MERGE.get(entry["category"], entry["category"])
            schema[full_key] = entry
    return schema


CONFIG_SCHEMA = _build_schema_from_config(DEFAULT_CONFIG)

# Inject virtual fields that don't live in DEFAULT_CONFIG but are surfaced
# by the normalize/denormalize cycle.  Insert model_context_length right after
# the "model" key so it renders adjacent in the frontend.
_mcl_entry = _SCHEMA_OVERRIDES["model_context_length"]
_ordered_schema: Dict[str, Dict[str, Any]] = {}
for _k, _v in CONFIG_SCHEMA.items():
    _ordered_schema[_k] = _v
    if _k == "model":
        _ordered_schema["model_context_length"] = _mcl_entry
CONFIG_SCHEMA = _ordered_schema


class ConfigUpdate(BaseModel):
    config: dict


class EnvVarUpdate(BaseModel):
    key: str
    value: str


class EnvVarDelete(BaseModel):
    key: str


class EnvVarReveal(BaseModel):
    key: str


class ModelAssignment(BaseModel):
    """Payload for POST /api/model/set — assign a provider/model to a slot.

    scope="main"        → writes model.provider + model.default
    scope="auxiliary"   → writes auxiliary.<task>.provider + auxiliary.<task>.model
    scope="auxiliary" with task=""  → applied to every auxiliary.* slot
    scope="auxiliary" with task="__reset__"  → resets every slot to provider="auto"
    """
    scope: str
    provider: str
    model: str
    task: str = ""


_GATEWAY_HEALTH_URL = os.getenv("GATEWAY_HEALTH_URL")
try:
    _GATEWAY_HEALTH_TIMEOUT = float(os.getenv("GATEWAY_HEALTH_TIMEOUT", "3"))
except (ValueError, TypeError):
    _log.warning(
        "Invalid GATEWAY_HEALTH_TIMEOUT value %r — using default 3.0s",
        os.getenv("GATEWAY_HEALTH_TIMEOUT"),
    )
    _GATEWAY_HEALTH_TIMEOUT = 3.0

# DEPRECATED (scheduled for removal): GATEWAY_HEALTH_URL / GATEWAY_HEALTH_TIMEOUT.
# Cross-container / cross-host gateway liveness detection will be folded into a
# first-class dashboard config key so it's no longer Docker-adjacent lore buried
# in env vars.  The env vars still work for now so existing Compose deployments
# don't break.  Do not add new callers — wire new uses through the planned
# config surface.


def _probe_gateway_health() -> tuple[bool, dict | None]:
    """Probe the gateway via its HTTP health endpoint (cross-container).

    .. deprecated::
        Driven by the deprecated ``GATEWAY_HEALTH_URL`` /
        ``GATEWAY_HEALTH_TIMEOUT`` env vars.  Scheduled for removal alongside
        a move to a first-class dashboard config key.  See
        :data:`_GATEWAY_HEALTH_URL` for context.

    Uses ``/health/detailed`` first (returns full state), falling back to
    the simpler ``/health`` endpoint.  Returns ``(is_alive, body_dict)``.

    Accepts any of these as ``GATEWAY_HEALTH_URL``:
    - ``http://gateway:8642``                (base URL — recommended)
    - ``http://gateway:8642/health``         (explicit health path)
    - ``http://gateway:8642/health/detailed`` (explicit detailed path)

    This is a **blocking** call — run via ``run_in_executor`` from async code.
    """
    if not _GATEWAY_HEALTH_URL:
        return False, None

    # Normalise to base URL so we always probe the right paths regardless of
    # whether the user included /health or /health/detailed in the env var.
    base = _GATEWAY_HEALTH_URL.rstrip("/")
    if base.endswith("/health/detailed"):
        base = base[: -len("/health/detailed")]
    elif base.endswith("/health"):
        base = base[: -len("/health")]

    for path in (f"{base}/health/detailed", f"{base}/health"):
        try:
            req = urllib.request.Request(path, method="GET")
            with urllib.request.urlopen(req, timeout=_GATEWAY_HEALTH_TIMEOUT) as resp:
                if resp.status == 200:
                    body = json.loads(resp.read())
                    return True, body
        except Exception:
            continue
    return False, None


@app.get("/api/status")
async def get_status():
    current_ver, latest_ver = check_config_version()

    # --- Gateway liveness detection ---
    # Try local PID check first (same-host).  If that fails and a remote
    # GATEWAY_HEALTH_URL is configured, probe the gateway over HTTP so the
    # dashboard works when the gateway runs in a separate container.
    gateway_pid = get_running_pid()
    gateway_running = gateway_pid is not None
    remote_health_body: dict | None = None

    if not gateway_running and _GATEWAY_HEALTH_URL:
        loop = asyncio.get_running_loop()
        alive, remote_health_body = await loop.run_in_executor(
            None, _probe_gateway_health
        )
        if alive:
            gateway_running = True
            # PID from the remote container (display only — not locally valid)
            if remote_health_body:
                gateway_pid = remote_health_body.get("pid")

    gateway_state = None
    gateway_platforms: dict = {}
    gateway_exit_reason = None
    gateway_updated_at = None
    configured_gateway_platforms: set[str] | None = None
    try:
        from gateway.config import load_gateway_config

        gateway_config = load_gateway_config()
        configured_gateway_platforms = {
            platform.value for platform in gateway_config.get_connected_platforms()
        }
    except Exception:
        configured_gateway_platforms = None

    # Prefer the detailed health endpoint response (has full state) when the
    # local runtime status file is absent or stale (cross-container).
    runtime = read_runtime_status()
    if runtime is None and remote_health_body and remote_health_body.get("gateway_state"):
        runtime = remote_health_body

    if runtime:
        gateway_state = runtime.get("gateway_state")
        gateway_platforms = runtime.get("platforms") or {}
        if configured_gateway_platforms is not None:
            gateway_platforms = {
                key: value
                for key, value in gateway_platforms.items()
                if key in configured_gateway_platforms
            }
        gateway_exit_reason = runtime.get("exit_reason")
        gateway_updated_at = runtime.get("updated_at")
        if not gateway_running:
            gateway_state = gateway_state if gateway_state in {"stopped", "startup_failed"} else "stopped"
            gateway_platforms = {}
        elif gateway_running and remote_health_body is not None:
            # The health probe confirmed the gateway is alive, but the local
            # runtime status file may be stale (cross-container).  Override
            # stopped/None state so the dashboard shows the correct badge.
            if gateway_state in {None, "stopped"}:
                gateway_state = "running"

    # If there was no runtime info at all but the health probe confirmed alive,
    # ensure we still report the gateway as running (no shared volume scenario).
    if gateway_running and gateway_state is None and remote_health_body is not None:
        gateway_state = "running"

    active_sessions = 0
    try:
        from hermes_state import SessionDB
        db = SessionDB()
        try:
            sessions = db.list_sessions_rich(limit=50)
            now = time.time()
            active_sessions = sum(
                1 for s in sessions
                if s.get("ended_at") is None
                and (now - s.get("last_active", s.get("started_at", 0))) < 300
            )
        finally:
            db.close()
    except Exception:
        pass

    return {
        "version": __version__,
        "release_date": __release_date__,
        "hermes_home": str(get_hermes_home()),
        "config_path": str(get_config_path()),
        "env_path": str(get_env_path()),
        "config_version": current_ver,
        "latest_config_version": latest_ver,
        "gateway_running": gateway_running,
        "gateway_pid": gateway_pid,
        "gateway_health_url": _GATEWAY_HEALTH_URL,
        "gateway_state": gateway_state,
        "gateway_platforms": gateway_platforms,
        "gateway_exit_reason": gateway_exit_reason,
        "gateway_updated_at": gateway_updated_at,
        "active_sessions": active_sessions,
    }


# ---------------------------------------------------------------------------
# Gateway + update actions (invoked from the Status page).
#
# Both commands are spawned as detached subprocesses so the HTTP request
# returns immediately.  stdin is closed (``DEVNULL``) so any stray ``input()``
# calls fail fast with EOF rather than hanging forever.  stdout/stderr are
# streamed to a per-action log file under ``~/.hermes/logs/<action>.log`` so
# the dashboard can tail them back to the user.
# ---------------------------------------------------------------------------

_ACTION_LOG_DIR: Path = get_hermes_home() / "logs"

# Short ``name`` (from the URL) → absolute log file path.
_ACTION_LOG_FILES: Dict[str, str] = {
    "gateway-restart": "gateway-restart.log",
    "hermes-update": "hermes-update.log",
}

# ``name`` → most recently spawned Popen handle.  Used so ``status`` can
# report liveness and exit code without shelling out to ``ps``.
_ACTION_PROCS: Dict[str, subprocess.Popen] = {}


def _spawn_hermes_action(subcommand: List[str], name: str) -> subprocess.Popen:
    """Spawn ``hermes <subcommand>`` detached and record the Popen handle.

    Uses the running interpreter's ``hermes_cli.main`` module so the action
    inherits the same venv/PYTHONPATH the web server is using.
    """
    log_file_name = _ACTION_LOG_FILES[name]
    _ACTION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _ACTION_LOG_DIR / log_file_name
    log_file = open(log_path, "ab", buffering=0)
    log_file.write(
        f"\n=== {name} started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode()
    )

    cmd = [sys.executable, "-m", "hermes_cli.main", *subcommand]

    popen_kwargs: Dict[str, Any] = {
        "cwd": str(PROJECT_ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
        "env": {**os.environ, "HERMES_NONINTERACTIVE": "1"},
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **popen_kwargs)
    _ACTION_PROCS[name] = proc
    return proc


def _tail_lines(path: Path, n: int) -> List[str]:
    """Return the last ``n`` lines of ``path``.  Reads the whole file — fine
    for our small per-action logs.  Binary-decoded with ``errors='replace'``
    so log corruption doesn't 500 the endpoint."""
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[-n:] if n > 0 else lines


@app.post("/api/gateway/restart")
async def restart_gateway():
    """Kick off a ``hermes gateway restart`` in the background."""
    try:
        proc = _spawn_hermes_action(["gateway", "restart"], "gateway-restart")
    except Exception as exc:
        _log.exception("Failed to spawn gateway restart")
        raise HTTPException(status_code=500, detail=f"Failed to restart gateway: {exc}")
    return {
        "ok": True,
        "pid": proc.pid,
        "name": "gateway-restart",
    }


@app.post("/api/hermes/update")
async def update_hermes():
    """Kick off ``hermes update`` in the background."""
    try:
        proc = _spawn_hermes_action(["update"], "hermes-update")
    except Exception as exc:
        _log.exception("Failed to spawn hermes update")
        raise HTTPException(status_code=500, detail=f"Failed to start update: {exc}")
    return {
        "ok": True,
        "pid": proc.pid,
        "name": "hermes-update",
    }


@app.get("/api/actions/{name}/status")
async def get_action_status(name: str, lines: int = 200):
    """Tail an action log and report whether the process is still running."""
    log_file_name = _ACTION_LOG_FILES.get(name)
    if log_file_name is None:
        raise HTTPException(status_code=404, detail=f"Unknown action: {name}")

    log_path = _ACTION_LOG_DIR / log_file_name
    tail = _tail_lines(log_path, min(max(lines, 1), 2000))

    proc = _ACTION_PROCS.get(name)
    if proc is None:
        running = False
        exit_code: Optional[int] = None
        pid: Optional[int] = None
    else:
        exit_code = proc.poll()
        running = exit_code is None
        pid = proc.pid

    return {
        "name": name,
        "running": running,
        "exit_code": exit_code,
        "pid": pid,
        "lines": tail,
    }


@app.get("/api/sessions")
async def get_sessions(limit: int = 20, offset: int = 0):
    try:
        from hermes_state import SessionDB
        db = SessionDB()
        try:
            sessions = db.list_sessions_rich(limit=limit, offset=offset)
            total = db.session_count()
            now = time.time()
            for s in sessions:
                s["is_active"] = (
                    s.get("ended_at") is None
                    and (now - s.get("last_active", s.get("started_at", 0))) < 300
                )
            return {"sessions": sessions, "total": total, "limit": limit, "offset": offset}
        finally:
            db.close()
    except Exception:
        _log.exception("GET /api/sessions failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/sessions/search")
async def search_sessions(q: str = "", limit: int = 20):
    """Full-text search across session message content using FTS5."""
    if not q or not q.strip():
        return {"results": []}
    try:
        from hermes_state import SessionDB
        db = SessionDB()
        try:
            # Auto-add prefix wildcards so partial words match
            # e.g. "nimb" → "nimb*" matches "nimby"
            # Preserve quoted phrases and existing wildcards as-is
            import re
            terms = []
            for token in re.findall(r'"[^"]*"|\S+', q.strip()):
                if token.startswith('"') or token.endswith("*"):
                    terms.append(token)
                else:
                    terms.append(token + "*")
            prefix_query = " ".join(terms)
            matches = db.search_messages(query=prefix_query, limit=limit)
            # Group by session_id — return unique sessions with their best snippet
            seen: dict = {}
            for m in matches:
                sid = m["session_id"]
                if sid not in seen:
                    seen[sid] = {
                        "session_id": sid,
                        "snippet": m.get("snippet", ""),
                        "role": m.get("role"),
                        "source": m.get("source"),
                        "model": m.get("model"),
                        "session_started": m.get("session_started"),
                    }
            return {"results": list(seen.values())}
        finally:
            db.close()
    except Exception:
        _log.exception("GET /api/sessions/search failed")
        raise HTTPException(status_code=500, detail="Search failed")


def _normalize_config_for_web(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize config for the web UI.

    Hermes supports ``model`` as either a bare string (``"anthropic/claude-sonnet-4"``)
    or a dict (``{default: ..., provider: ..., base_url: ...}``).  The schema is built
    from DEFAULT_CONFIG where ``model`` is a string, but user configs often have the
    dict form.  Normalize to the string form so the frontend schema matches.

    Also surfaces ``model_context_length`` as a top-level field so the web UI can
    display and edit it.  A value of 0 means "auto-detect".
    """
    config = dict(config)  # shallow copy
    model_val = config.get("model")
    if isinstance(model_val, dict):
        # Extract context_length before flattening the dict
        ctx_len = model_val.get("context_length", 0)
        config["model"] = model_val.get("default", model_val.get("name", ""))
        config["model_context_length"] = ctx_len if isinstance(ctx_len, int) else 0
    else:
        config["model_context_length"] = 0
    return config


@app.get("/api/config")
async def get_config():
    config = _normalize_config_for_web(load_config())
    # Strip internal keys that the frontend shouldn't see or send back
    return {k: v for k, v in config.items() if not k.startswith("_")}


@app.get("/api/config/defaults")
async def get_defaults():
    return DEFAULT_CONFIG


@app.get("/api/config/schema")
async def get_schema():
    return {"fields": CONFIG_SCHEMA, "category_order": _CATEGORY_ORDER}


_EMPTY_MODEL_INFO: dict = {
    "model": "",
    "provider": "",
    "auto_context_length": 0,
    "config_context_length": 0,
    "effective_context_length": 0,
    "capabilities": {},
}


@app.get("/api/model/info")
def get_model_info():
    """Return resolved model metadata for the currently configured model.

    Calls the same context-length resolution chain the agent uses, so the
    frontend can display "Auto-detected: 200K" alongside the override field.
    Also returns model capabilities (vision, reasoning, tools) when available.
    """
    try:
        cfg = load_config()
        model_cfg = cfg.get("model", "")

        # Extract model name and provider from the config
        if isinstance(model_cfg, dict):
            model_name = model_cfg.get("default", model_cfg.get("name", ""))
            provider = model_cfg.get("provider", "")
            base_url = model_cfg.get("base_url", "")
            config_ctx = model_cfg.get("context_length")
        else:
            model_name = str(model_cfg) if model_cfg else ""
            provider = ""
            base_url = ""
            config_ctx = None

        if not model_name:
            return dict(_EMPTY_MODEL_INFO, provider=provider)

        # Resolve auto-detected context length (pass config_ctx=None to get
        # purely auto-detected value, then separately report the override)
        try:
            from agent.model_metadata import get_model_context_length
            auto_ctx = get_model_context_length(
                model=model_name,
                base_url=base_url,
                provider=provider,
                config_context_length=None,  # ignore override — we want auto value
            )
        except Exception:
            auto_ctx = 0

        config_ctx_int = 0
        if isinstance(config_ctx, int) and config_ctx > 0:
            config_ctx_int = config_ctx

        # Effective is what the agent actually uses
        effective_ctx = config_ctx_int if config_ctx_int > 0 else auto_ctx

        # Try to get model capabilities from models.dev
        caps = {}
        try:
            from agent.models_dev import get_model_capabilities
            mc = get_model_capabilities(provider=provider, model=model_name)
            if mc is not None:
                caps = {
                    "supports_tools": mc.supports_tools,
                    "supports_vision": mc.supports_vision,
                    "supports_reasoning": mc.supports_reasoning,
                    "context_window": mc.context_window,
                    "max_output_tokens": mc.max_output_tokens,
                    "model_family": mc.model_family,
                }
        except Exception:
            pass

        return {
            "model": model_name,
            "provider": provider,
            "auto_context_length": auto_ctx,
            "config_context_length": config_ctx_int,
            "effective_context_length": effective_ctx,
            "capabilities": caps,
        }
    except Exception:
        _log.exception("GET /api/model/info failed")
        return dict(_EMPTY_MODEL_INFO)


# ---------------------------------------------------------------------------
# Model assignment — pick provider+model for main slot or auxiliary slots.
# Mirrors the model.options JSON-RPC from tui_gateway but uses REST so the
# Models page (which has no chat PTY open) can drive it.
# ---------------------------------------------------------------------------

# Canonical auxiliary task slots. Keep in sync with DEFAULT_CONFIG["auxiliary"]
# in hermes_cli/config.py — listed here for deterministic ordering in the UI.
_AUX_TASK_SLOTS: Tuple[str, ...] = (
    "vision",
    "web_extract",
    "compression",
    "session_search",
    "skills_hub",
    "approval",
    "mcp",
    "title_generation",
    "curator",
)


@app.get("/api/model/options")
def get_model_options():
    """Return authenticated providers + their curated model lists.

    REST equivalent of the ``model.options`` JSON-RPC on tui_gateway, so the
    dashboard Models page can render the picker without a live chat session.
    The response shape matches ``model.options`` 1:1 so ``ModelPickerDialog``
    can share the same types.
    """
    try:
        from hermes_cli.inventory import build_models_payload, load_picker_context

        return build_models_payload(load_picker_context(), max_models=50)
    except Exception:
        _log.exception("GET /api/model/options failed")
        raise HTTPException(status_code=500, detail="Failed to list model options")


@app.get("/api/model/auxiliary")
def get_auxiliary_models():
    """Return current auxiliary task assignments.

    Shape:
      {
        "tasks": [
          {"task": "vision", "provider": "auto", "model": "", "base_url": ""},
          ...
        ],
        "main": {"provider": "openrouter", "model": "anthropic/claude-opus-4.7"},
      }
    """
    try:
        cfg = load_config()
        aux_cfg = cfg.get("auxiliary", {})
        if not isinstance(aux_cfg, dict):
            aux_cfg = {}

        tasks = []
        for slot in _AUX_TASK_SLOTS:
            slot_cfg = aux_cfg.get(slot, {}) if isinstance(aux_cfg.get(slot), dict) else {}
            tasks.append({
                "task": slot,
                "provider": str(slot_cfg.get("provider", "auto") or "auto"),
                "model": str(slot_cfg.get("model", "") or ""),
                "base_url": str(slot_cfg.get("base_url", "") or ""),
            })

        model_cfg = cfg.get("model", {})
        if isinstance(model_cfg, dict):
            main = {
                "provider": str(model_cfg.get("provider", "") or ""),
                "model": str(model_cfg.get("default", model_cfg.get("name", "")) or ""),
            }
        else:
            main = {"provider": "", "model": str(model_cfg) if model_cfg else ""}

        return {"tasks": tasks, "main": main}
    except Exception:
        _log.exception("GET /api/model/auxiliary failed")
        raise HTTPException(status_code=500, detail="Failed to read auxiliary config")


@app.post("/api/model/set")
async def set_model_assignment(body: ModelAssignment):
    """Assign a model to the main slot or an auxiliary task slot.

    Writes to ``~/.hermes/config.yaml`` — applies to **new** sessions only.
    The currently running chat PTY (if any) is not affected; use the
    ``/model`` slash command inside a chat to hot-swap that specific session.
    """
    scope = (body.scope or "").strip().lower()
    provider = (body.provider or "").strip()
    model = (body.model or "").strip()
    task = (body.task or "").strip().lower()

    if scope not in {"main", "auxiliary"}:
        raise HTTPException(status_code=400, detail="scope must be 'main' or 'auxiliary'")

    try:
        cfg = load_config()

        if scope == "main":
            if not provider or not model:
                raise HTTPException(status_code=400, detail="provider and model required for main")
            model_cfg = cfg.get("model", {})
            if not isinstance(model_cfg, dict):
                model_cfg = {}
            model_cfg["provider"] = provider
            model_cfg["default"] = model
            # Clear stale base_url so the resolver picks the provider's own default.
            if "base_url" in model_cfg and model_cfg.get("base_url"):
                model_cfg["base_url"] = ""
            # Also clear hardcoded context_length override — new model may have
            # a different context window.
            if "context_length" in model_cfg:
                model_cfg.pop("context_length", None)
            cfg["model"] = model_cfg
            save_config(cfg)
            return {"ok": True, "scope": "main", "provider": provider, "model": model}

        # scope == "auxiliary"
        aux = cfg.get("auxiliary")
        if not isinstance(aux, dict):
            aux = {}

        if task == "__reset__":
            # Reset every slot to provider="auto", model="" — keeps other fields intact.
            for slot in _AUX_TASK_SLOTS:
                slot_cfg = aux.get(slot)
                if not isinstance(slot_cfg, dict):
                    slot_cfg = {}
                slot_cfg["provider"] = "auto"
                slot_cfg["model"] = ""
                aux[slot] = slot_cfg
            cfg["auxiliary"] = aux
            save_config(cfg)
            return {"ok": True, "scope": "auxiliary", "reset": True}

        if not provider:
            raise HTTPException(status_code=400, detail="provider required for auxiliary")

        targets = [task] if task else list(_AUX_TASK_SLOTS)
        for slot in targets:
            if slot not in _AUX_TASK_SLOTS:
                raise HTTPException(status_code=400, detail=f"unknown auxiliary task: {slot}")
            slot_cfg = aux.get(slot)
            if not isinstance(slot_cfg, dict):
                slot_cfg = {}
            slot_cfg["provider"] = provider
            slot_cfg["model"] = model
            aux[slot] = slot_cfg

        cfg["auxiliary"] = aux
        save_config(cfg)
        return {
            "ok": True,
            "scope": "auxiliary",
            "tasks": targets,
            "provider": provider,
            "model": model,
        }
    except HTTPException:
        raise
    except Exception:
        _log.exception("POST /api/model/set failed")
        raise HTTPException(status_code=500, detail="Failed to save model assignment")




def _denormalize_config_from_web(config: Dict[str, Any]) -> Dict[str, Any]:
    """Reverse _normalize_config_for_web before saving.

    Reconstructs ``model`` as a dict by reading the current on-disk config
    to recover model subkeys (provider, base_url, api_mode, etc.) that were
    stripped from the GET response.  The frontend only sees model as a flat
    string; the rest is preserved transparently.

    Also handles ``model_context_length`` — writes it back into the model dict
    as ``context_length``.  A value of 0 or absent means "auto-detect" (omitted
    from the dict so get_model_context_length() uses its normal resolution).
    """
    config = dict(config)
    # Remove any _model_meta that might have leaked in (shouldn't happen
    # with the stripped GET response, but be defensive)
    config.pop("_model_meta", None)

    # Extract and remove model_context_length before processing model
    ctx_override = config.pop("model_context_length", 0)
    if not isinstance(ctx_override, int):
        try:
            ctx_override = int(ctx_override)
        except (TypeError, ValueError):
            ctx_override = 0

    model_val = config.get("model")
    if isinstance(model_val, str) and model_val:
        # Read the current disk config to recover model subkeys
        try:
            disk_config = load_config()
            disk_model = disk_config.get("model")
            if isinstance(disk_model, dict):
                # Preserve all subkeys, update default with the new value
                disk_model["default"] = model_val
                # Write context_length into the model dict (0 = remove/auto)
                if ctx_override > 0:
                    disk_model["context_length"] = ctx_override
                else:
                    disk_model.pop("context_length", None)
                config["model"] = disk_model
            # Model was previously a bare string — upgrade to dict if
            # user is setting a context_length override
            elif ctx_override > 0:
                config["model"] = {
                    "default": model_val,
                    "context_length": ctx_override,
                }
        except Exception:
            pass  # can't read disk config — just use the string form
    return config


@app.put("/api/config")
async def update_config(body: ConfigUpdate):
    try:
        save_config(_denormalize_config_from_web(body.config))
        return {"ok": True}
    except Exception:
        _log.exception("PUT /api/config failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/env")
async def get_env_vars():
    env_on_disk = load_env()
    result = {}
    for var_name, info in OPTIONAL_ENV_VARS.items():
        value = env_on_disk.get(var_name)
        result[var_name] = {
            "is_set": bool(value),
            "redacted_value": redact_key(value) if value else None,
            "description": info.get("description", ""),
            "url": info.get("url"),
            "category": info.get("category", ""),
            "is_password": info.get("password", False),
            "tools": info.get("tools", []),
            "advanced": info.get("advanced", False),
        }
    return result


@app.put("/api/env")
async def set_env_var(body: EnvVarUpdate):
    try:
        save_env_value(body.key, body.value)
        return {"ok": True, "key": body.key}
    except Exception:
        _log.exception("PUT /api/env failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/api/env")
async def remove_env_var(body: EnvVarDelete):
    try:
        removed = remove_env_value(body.key)
        if not removed:
            raise HTTPException(status_code=404, detail=f"{body.key} not found in .env")
        return {"ok": True, "key": body.key}
    except HTTPException:
        raise
    except Exception:
        _log.exception("DELETE /api/env failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/env/reveal")
async def reveal_env_var(body: EnvVarReveal, request: Request):
    """Return the real (unredacted) value of a single env var.

    Protected by:
    - Ephemeral session token (generated per server start, injected into SPA)
    - Rate limiting (max 5 reveals per 30s window)
    - Audit logging
    """
    # --- Token check ---
    _require_token(request)

    # --- Rate limit ---
    now = time.time()
    cutoff = now - _REVEAL_WINDOW_SECONDS
    _reveal_timestamps[:] = [t for t in _reveal_timestamps if t > cutoff]
    if len(_reveal_timestamps) >= _REVEAL_MAX_PER_WINDOW:
        raise HTTPException(status_code=429, detail="Too many reveal requests. Try again shortly.")
    _reveal_timestamps.append(now)

    # --- Reveal ---
    env_on_disk = load_env()
    value = env_on_disk.get(body.key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"{body.key} not found in .env")

    _log.info("env/reveal: %s", body.key)
    return {"key": body.key, "value": value}


# ---------------------------------------------------------------------------
# OAuth provider endpoints — status + disconnect (Phase 1)
# ---------------------------------------------------------------------------
#
# Phase 1 surfaces *which OAuth providers exist* and whether each is
# connected, plus a disconnect button. The actual login flow (PKCE for
# Anthropic, device-code for Nous/Codex) still runs in the CLI for now;
# Phase 2 will add in-browser flows. For unconnected providers we return
# the canonical ``hermes auth add <provider>`` command so the dashboard
# can surface a one-click copy.


def _truncate_token(value: Optional[str], visible: int = 6) -> str:
    """Return ``...XXXXXX`` (last N chars) for safe display in the UI.

    We never expose more than the trailing ``visible`` characters of an
    OAuth access token. JWT prefixes (the part before the first dot) are
    stripped first when present so the visible suffix is always part of
    the signing region rather than a meaningless header chunk.

    Returns the Entra-ID placeholder when handed a callable (Azure Foundry
    bearer provider) — the callable is NEVER invoked here.
    """
    if not value:
        return ""
    if callable(value) and not isinstance(value, str):
        # Entra ID bearer provider — never reveal a minted token in the UI.
        return "<entra-id-bearer>"
    s = str(value)
    if "." in s and s.count(".") >= 2:
        # Looks like a JWT — show the trailing piece of the signature only.
        s = s.rsplit(".", 1)[-1]
    if len(s) <= visible:
        return s
    return f"…{s[-visible:]}"


def _anthropic_oauth_status() -> Dict[str, Any]:
    """Combined status across the three Anthropic credential sources we read.

    Hermes resolves Anthropic creds in this order at runtime:
    1. ``~/.hermes/.anthropic_oauth.json`` — Hermes-managed PKCE flow
    2. ``~/.claude/.credentials.json`` — Claude Code CLI credentials (auto)
    3. ``ANTHROPIC_TOKEN`` / ``ANTHROPIC_API_KEY`` env vars
    The dashboard reports the highest-priority source that's actually present.
    """
    try:
        from agent.anthropic_adapter import (
            read_hermes_oauth_credentials,
            read_claude_code_credentials,
            _HERMES_OAUTH_FILE,
        )
    except ImportError:
        read_claude_code_credentials = None  # type: ignore
        read_hermes_oauth_credentials = None  # type: ignore
        _HERMES_OAUTH_FILE = None  # type: ignore

    hermes_creds = None
    if read_hermes_oauth_credentials:
        try:
            hermes_creds = read_hermes_oauth_credentials()
        except Exception:
            hermes_creds = None
    if hermes_creds and hermes_creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "hermes_pkce",
            "source_label": f"Hermes PKCE ({_HERMES_OAUTH_FILE})",
            "token_preview": _truncate_token(hermes_creds.get("accessToken")),
            "expires_at": hermes_creds.get("expiresAt"),
            "has_refresh_token": bool(hermes_creds.get("refreshToken")),
        }

    cc_creds = None
    if read_claude_code_credentials:
        try:
            cc_creds = read_claude_code_credentials()
        except Exception:
            cc_creds = None
    if cc_creds and cc_creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "claude_code",
            "source_label": "Claude Code (~/.claude/.credentials.json)",
            "token_preview": _truncate_token(cc_creds.get("accessToken")),
            "expires_at": cc_creds.get("expiresAt"),
            "has_refresh_token": bool(cc_creds.get("refreshToken")),
        }

    env_token = os.getenv("ANTHROPIC_TOKEN") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
    if env_token:
        return {
            "logged_in": True,
            "source": "env_var",
            "source_label": "ANTHROPIC_TOKEN environment variable",
            "token_preview": _truncate_token(env_token),
            "expires_at": None,
            "has_refresh_token": False,
        }
    return {"logged_in": False, "source": None}


def _claude_code_only_status() -> Dict[str, Any]:
    """Surface Claude Code CLI credentials as their own provider entry.

    Independent of the Anthropic entry above so users can see whether their
    Claude Code subscription tokens are actively flowing into Hermes even
    when they also have a separate Hermes-managed PKCE login.
    """
    try:
        from agent.anthropic_adapter import read_claude_code_credentials
        creds = read_claude_code_credentials()
    except Exception:
        creds = None
    if creds and creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "claude_code_cli",
            "source_label": "~/.claude/.credentials.json",
            "token_preview": _truncate_token(creds.get("accessToken")),
            "expires_at": creds.get("expiresAt"),
            "has_refresh_token": bool(creds.get("refreshToken")),
        }
    return {"logged_in": False, "source": None}


# Provider catalog. The order matters — it's how we render the UI list.
# ``cli_command`` is what the dashboard surfaces as the copy-to-clipboard
# fallback while Phase 2 (in-browser flows) isn't built yet.
# ``flow`` describes the OAuth shape so the future modal can pick the
# right UI: ``pkce`` = open URL + paste callback code, ``device_code`` =
# show code + verification URL + poll, ``external`` = read-only (delegated
# to a third-party CLI like Claude Code or Qwen).
_OAUTH_PROVIDER_CATALOG: tuple[Dict[str, Any], ...] = (
    {
        "id": "anthropic",
        "name": "Anthropic (Claude API)",
        "flow": "pkce",
        "cli_command": "hermes auth add anthropic",
        "docs_url": "https://docs.claude.com/en/api/getting-started",
        "status_fn": _anthropic_oauth_status,
    },
    {
        "id": "claude-code",
        "name": "Claude Code (subscription)",
        "flow": "external",
        "cli_command": "claude setup-token",
        "docs_url": "https://docs.claude.com/en/docs/claude-code",
        "status_fn": _claude_code_only_status,
    },
    {
        "id": "nous",
        "name": "Nous Portal",
        "flow": "device_code",
        "cli_command": "hermes auth add nous",
        "docs_url": "https://portal.nousresearch.com",
        "status_fn": None,  # dispatched via auth.get_nous_auth_status
    },
    {
        "id": "openai-codex",
        "name": "OpenAI Codex (ChatGPT)",
        "flow": "device_code",
        "cli_command": "hermes auth add openai-codex",
        "docs_url": "https://platform.openai.com/docs",
        "status_fn": None,  # dispatched via auth.get_codex_auth_status
    },
    {
        "id": "qwen-oauth",
        "name": "Qwen (via Qwen CLI)",
        "flow": "external",
        "cli_command": "hermes auth add qwen-oauth",
        "docs_url": "https://github.com/QwenLM/qwen-code",
        "status_fn": None,  # dispatched via auth.get_qwen_auth_status
    },
    {
        "id": "minimax-oauth",
        "name": "MiniMax (OAuth)",
        # MiniMax's flow is structurally device-code (verification URI +
        # user code, backend polls the token endpoint) with a PKCE
        # extension for code-binding. The dashboard renders the same UX
        # as Nous's device-code flow; the PKCE bit is a security
        # extension that doesn't change the operator experience.
        "flow": "device_code",
        "cli_command": "hermes auth add minimax-oauth",
        "docs_url": "https://www.minimax.io",
        "status_fn": None,  # dispatched via auth.get_minimax_oauth_auth_status
    },
)


def _resolve_provider_status(provider_id: str, status_fn) -> Dict[str, Any]:
    """Dispatch to the right status helper for an OAuth provider entry."""
    if status_fn is not None:
        try:
            return status_fn()
        except Exception as e:
            return {"logged_in": False, "error": str(e)}
    try:
        from hermes_cli import auth as hauth
        if provider_id == "nous":
            raw = hauth.get_nous_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": "nous_portal",
                "source_label": raw.get("portal_base_url") or "Nous Portal",
                "token_preview": _truncate_token(raw.get("access_token")),
                "expires_at": raw.get("access_expires_at"),
                "has_refresh_token": bool(raw.get("has_refresh_token")),
            }
        if provider_id == "openai-codex":
            raw = hauth.get_codex_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": raw.get("source") or "openai_codex",
                "source_label": raw.get("auth_mode") or "OpenAI Codex",
                "token_preview": _truncate_token(raw.get("api_key")),
                "expires_at": None,
                "has_refresh_token": False,
                "last_refresh": raw.get("last_refresh"),
            }
        if provider_id == "qwen-oauth":
            raw = hauth.get_qwen_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": "qwen_cli",
                "source_label": raw.get("auth_store_path") or "Qwen CLI",
                "token_preview": _truncate_token(raw.get("access_token")),
                "expires_at": raw.get("expires_at"),
                "has_refresh_token": bool(raw.get("has_refresh_token")),
            }
        if provider_id == "minimax-oauth":
            raw = hauth.get_minimax_oauth_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": "minimax_oauth",
                "source_label": f"MiniMax ({raw.get('region', 'global')})",
                "token_preview": None,
                "expires_at": raw.get("expires_at"),
                "has_refresh_token": True,
            }
    except Exception as e:
        return {"logged_in": False, "error": str(e)}
    return {"logged_in": False}


@app.get("/api/providers/oauth")
async def list_oauth_providers():
    """Enumerate every OAuth-capable LLM provider with current status.

    Response shape (per provider):
        id              stable identifier (used in DELETE path)
        name            human label
        flow            "pkce" | "device_code" | "external"
        cli_command     fallback CLI command for users to run manually
        docs_url        external docs/portal link for the "Learn more" link
        status:
          logged_in        bool — currently has usable creds
          source           short slug ("hermes_pkce", "claude_code", ...)
          source_label     human-readable origin (file path, env var name)
          token_preview    last N chars of the token, never the full token
          expires_at       ISO timestamp string or null
          has_refresh_token bool
    """
    providers = []
    for p in _OAUTH_PROVIDER_CATALOG:
        status = _resolve_provider_status(p["id"], p.get("status_fn"))
        providers.append({
            "id": p["id"],
            "name": p["name"],
            "flow": p["flow"],
            "cli_command": p["cli_command"],
            "docs_url": p["docs_url"],
            "status": status,
        })
    return {"providers": providers}


@app.delete("/api/providers/oauth/{provider_id}")
async def disconnect_oauth_provider(provider_id: str, request: Request):
    """Disconnect an OAuth provider. Token-protected (matches /env/reveal)."""
    _require_token(request)

    valid_ids = {p["id"] for p in _OAUTH_PROVIDER_CATALOG}
    if provider_id not in valid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {provider_id}. "
                   f"Available: {', '.join(sorted(valid_ids))}",
        )

    # Anthropic and claude-code clear the same Hermes-managed PKCE file
    # AND forget the Claude Code import. We don't touch ~/.claude/* directly
    # — that's owned by the Claude Code CLI; users can re-auth there if they
    # want to undo a disconnect.
    if provider_id in {"anthropic", "claude-code"}:
        try:
            from agent.anthropic_adapter import _HERMES_OAUTH_FILE
            if _HERMES_OAUTH_FILE.exists():
                _HERMES_OAUTH_FILE.unlink()
        except Exception:
            pass
        # Also clear the credential pool entry if present.
        try:
            from hermes_cli.auth import clear_provider_auth
            clear_provider_auth("anthropic")
        except Exception:
            pass
        _log.info("oauth/disconnect: %s", provider_id)
        return {"ok": True, "provider": provider_id}

    try:
        from hermes_cli.auth import clear_provider_auth
        cleared = clear_provider_auth(provider_id)
        _log.info("oauth/disconnect: %s (cleared=%s)", provider_id, cleared)
        return {"ok": bool(cleared), "provider": provider_id}
    except Exception as e:
        _log.exception("disconnect %s failed", provider_id)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# OAuth Phase 2 — in-browser PKCE & device-code flows
# ---------------------------------------------------------------------------
#
# Two flow shapes are supported:
#
#   PKCE (Anthropic):
#     1. POST /api/providers/oauth/anthropic/start
#          → server generates code_verifier + challenge, builds claude.ai
#            authorize URL, stashes verifier in _oauth_sessions[session_id]
#          → returns { session_id, flow: "pkce", auth_url }
#     2. UI opens auth_url in a new tab. User authorizes, copies code.
#     3. POST /api/providers/oauth/anthropic/submit { session_id, code }
#          → server exchanges (code + verifier) → tokens at console.anthropic.com
#          → persists to ~/.hermes/.anthropic_oauth.json AND credential pool
#          → returns { ok: true, status: "approved" }
#
#   Device code (Nous, OpenAI Codex):
#     1. POST /api/providers/oauth/{nous|openai-codex}/start
#          → server hits provider's device-auth endpoint
#          → gets { user_code, verification_url, device_code, interval, expires_in }
#          → spawns background poller thread that polls the token endpoint
#            every `interval` seconds until approved/expired
#          → stores poll status in _oauth_sessions[session_id]
#          → returns { session_id, flow: "device_code", user_code,
#                      verification_url, expires_in, poll_interval }
#     2. UI opens verification_url in a new tab and shows user_code.
#     3. UI polls GET /api/providers/oauth/{provider}/poll/{session_id}
#          every 2s until status != "pending".
#     4. On "approved" the background thread has already saved creds; UI
#        refreshes the providers list.
#
# Sessions are kept in-memory only (single-process FastAPI) and time out
# after 15 minutes. A periodic cleanup runs on each /start call to GC
# expired sessions so the dict doesn't grow without bound.

_OAUTH_SESSION_TTL_SECONDS = 15 * 60
_oauth_sessions: Dict[str, Dict[str, Any]] = {}
_oauth_sessions_lock = threading.Lock()

# Import OAuth constants from canonical source instead of duplicating.
# Guarded so hermes web still starts if anthropic_adapter is unavailable;
# Phase 2 endpoints will return 501 in that case.
try:
    from agent.anthropic_adapter import (
        _OAUTH_CLIENT_ID as _ANTHROPIC_OAUTH_CLIENT_ID,
        _OAUTH_TOKEN_URL as _ANTHROPIC_OAUTH_TOKEN_URL,
        _OAUTH_REDIRECT_URI as _ANTHROPIC_OAUTH_REDIRECT_URI,
        _OAUTH_SCOPES as _ANTHROPIC_OAUTH_SCOPES,
        _generate_pkce as _generate_pkce_pair,
    )
    _ANTHROPIC_OAUTH_AVAILABLE = True
except ImportError:
    _ANTHROPIC_OAUTH_AVAILABLE = False
_ANTHROPIC_OAUTH_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"


def _gc_oauth_sessions() -> None:
    """Drop expired sessions. Called opportunistically on /start."""
    cutoff = time.time() - _OAUTH_SESSION_TTL_SECONDS
    with _oauth_sessions_lock:
        stale = [sid for sid, sess in _oauth_sessions.items() if sess["created_at"] < cutoff]
        for sid in stale:
            _oauth_sessions.pop(sid, None)


def _new_oauth_session(provider_id: str, flow: str) -> tuple[str, Dict[str, Any]]:
    """Create + register a new OAuth session, return (session_id, session_dict)."""
    sid = secrets.token_urlsafe(16)
    sess = {
        "session_id": sid,
        "provider": provider_id,
        "flow": flow,
        "created_at": time.time(),
        "status": "pending",  # pending | approved | denied | expired | error
        "error_message": None,
    }
    with _oauth_sessions_lock:
        _oauth_sessions[sid] = sess
    return sid, sess


def _save_anthropic_oauth_creds(access_token: str, refresh_token: str, expires_at_ms: int) -> None:
    """Persist Anthropic PKCE creds to both Hermes file AND credential pool.

    Mirrors what auth_commands.add_command does so the dashboard flow leaves
    the system in the same state as ``hermes auth add anthropic``.
    """
    from agent.anthropic_adapter import _HERMES_OAUTH_FILE
    payload = {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresAt": expires_at_ms,
    }
    _HERMES_OAUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _HERMES_OAUTH_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Best-effort credential-pool insert. Failure here doesn't invalidate
    # the file write — pool registration only matters for the rotation
    # strategy, not for runtime credential resolution.
    try:
        from agent.credential_pool import (
            PooledCredential,
            load_pool,
            AUTH_TYPE_OAUTH,
            SOURCE_MANUAL,
        )
        import uuid
        pool = load_pool("anthropic")
        # Avoid duplicate entries: delete any prior dashboard-issued OAuth entry
        existing = [e for e in pool.entries() if getattr(e, "source", "").startswith(f"{SOURCE_MANUAL}:dashboard_pkce")]
        for e in existing:
            try:
                pool.remove_entry(getattr(e, "id", ""))
            except Exception:
                pass
        entry = PooledCredential(
            provider="anthropic",
            id=uuid.uuid4().hex[:6],
            label="dashboard PKCE",
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=f"{SOURCE_MANUAL}:dashboard_pkce",
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at_ms=expires_at_ms,
        )
        pool.add_entry(entry)
    except Exception as e:
        _log.warning("anthropic pool add (dashboard) failed: %s", e)


def _start_anthropic_pkce() -> Dict[str, Any]:
    """Begin PKCE flow. Returns the auth URL the UI should open."""
    if not _ANTHROPIC_OAUTH_AVAILABLE:
        raise HTTPException(status_code=501, detail="Anthropic OAuth not available (missing adapter)")
    verifier, challenge = _generate_pkce_pair()
    sid, sess = _new_oauth_session("anthropic", "pkce")
    sess["verifier"] = verifier
    sess["state"] = verifier  # Anthropic round-trips verifier as state
    params = {
        "code": "true",
        "client_id": _ANTHROPIC_OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": _ANTHROPIC_OAUTH_REDIRECT_URI,
        "scope": _ANTHROPIC_OAUTH_SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": verifier,
    }
    auth_url = f"{_ANTHROPIC_OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    return {
        "session_id": sid,
        "flow": "pkce",
        "auth_url": auth_url,
        "expires_in": _OAUTH_SESSION_TTL_SECONDS,
    }


def _submit_anthropic_pkce(session_id: str, code_input: str) -> Dict[str, Any]:
    """Exchange authorization code for tokens. Persists on success."""
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess or sess["provider"] != "anthropic" or sess["flow"] != "pkce":
        raise HTTPException(status_code=404, detail="Unknown or expired session")
    if sess["status"] != "pending":
        return {"ok": False, "status": sess["status"], "message": sess.get("error_message")}

    # Anthropic's redirect callback page formats the code as `<code>#<state>`.
    # Strip the state suffix if present (we already have the verifier server-side).
    parts = code_input.strip().split("#", 1)
    code = parts[0].strip()
    if not code:
        return {"ok": False, "status": "error", "message": "No code provided"}
    state_from_callback = parts[1] if len(parts) > 1 else ""

    exchange_data = json.dumps({
        "grant_type": "authorization_code",
        "client_id": _ANTHROPIC_OAUTH_CLIENT_ID,
        "code": code,
        "state": state_from_callback or sess["state"],
        "redirect_uri": _ANTHROPIC_OAUTH_REDIRECT_URI,
        "code_verifier": sess["verifier"],
    }).encode()
    req = urllib.request.Request(
        _ANTHROPIC_OAUTH_TOKEN_URL,
        data=exchange_data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "hermes-dashboard/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode())
    except Exception as e:
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = f"Token exchange failed: {e}"
        return {"ok": False, "status": "error", "message": sess["error_message"]}

    access_token = result.get("access_token", "")
    refresh_token = result.get("refresh_token", "")
    expires_in = int(result.get("expires_in") or 3600)
    if not access_token:
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = "No access token returned"
        return {"ok": False, "status": "error", "message": sess["error_message"]}

    expires_at_ms = int(time.time() * 1000) + (expires_in * 1000)
    try:
        _save_anthropic_oauth_creds(access_token, refresh_token, expires_at_ms)
    except Exception as e:
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = f"Save failed: {e}"
        return {"ok": False, "status": "error", "message": sess["error_message"]}
    with _oauth_sessions_lock:
        sess["status"] = "approved"
    _log.info("oauth/pkce: anthropic login completed (session=%s)", session_id)
    return {"ok": True, "status": "approved"}


async def _start_device_code_flow(provider_id: str) -> Dict[str, Any]:
    """Initiate a device-code flow (Nous, OpenAI Codex, or MiniMax).

    Calls the provider's device-auth endpoint via the existing CLI helpers,
    then spawns a background poller. Returns the user-facing display fields
    so the UI can render the verification page link + user code.
    """
    if provider_id == "nous":
        from hermes_cli.auth import (
            _nous_device_scope_with_env_override,
            _request_nous_device_code_with_scope_fallback,
            PROVIDER_REGISTRY,
        )
        import httpx
        pconfig = PROVIDER_REGISTRY["nous"]
        portal_base_url = (
            os.getenv("HERMES_PORTAL_BASE_URL")
            or os.getenv("NOUS_PORTAL_BASE_URL")
            or pconfig.portal_base_url
        ).rstrip("/")
        client_id = pconfig.client_id
        scope, explicit_scope = _nous_device_scope_with_env_override(
            None,
            default_scope=pconfig.scope,
        )

        def _do_nous_device_request():
            with httpx.Client(
                timeout=httpx.Timeout(15.0),
                headers={"Accept": "application/json"},
            ) as client:
                return _request_nous_device_code_with_scope_fallback(
                    client=client,
                    portal_base_url=portal_base_url,
                    client_id=client_id,
                    scope=scope,
                    allow_legacy_fallback=not explicit_scope,
                )

        device_data, effective_scope = await asyncio.get_running_loop().run_in_executor(
            None, _do_nous_device_request
        )
        sid, sess = _new_oauth_session("nous", "device_code")
        sess["device_code"] = str(device_data["device_code"])
        sess["interval"] = int(device_data["interval"])
        sess["expires_at"] = time.time() + int(device_data["expires_in"])
        sess["portal_base_url"] = portal_base_url
        sess["client_id"] = client_id
        sess["scope"] = effective_scope
        threading.Thread(
            target=_nous_poller, args=(sid,), daemon=True, name=f"oauth-poll-{sid[:6]}"
        ).start()
        return {
            "session_id": sid,
            "flow": "device_code",
            "user_code": str(device_data["user_code"]),
            "verification_url": str(device_data["verification_uri_complete"]),
            "expires_in": int(device_data["expires_in"]),
            "poll_interval": int(device_data["interval"]),
        }

    if provider_id == "openai-codex":
        # Codex uses fixed OpenAI device-auth endpoints; reuse the helper.
        sid, _ = _new_oauth_session("openai-codex", "device_code")
        # Use the helper but in a thread because it polls inline.
        # We can't extract just the start step without refactoring auth.py,
        # so we run the full helper in a worker and proxy the user_code +
        # verification_url back via the session dict. The helper prints
        # to stdout — we capture nothing here, just status.
        threading.Thread(
            target=_codex_full_login_worker, args=(sid,), daemon=True,
            name=f"oauth-codex-{sid[:6]}",
        ).start()
        # Block briefly until the worker has populated the user_code, OR error.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with _oauth_sessions_lock:
                s = _oauth_sessions.get(sid)
            if s and (s.get("user_code") or s["status"] != "pending"):
                break
            await asyncio.sleep(0.1)
        with _oauth_sessions_lock:
            s = _oauth_sessions.get(sid, {})
        if s.get("status") == "error":
            raise HTTPException(status_code=500, detail=s.get("error_message") or "device-auth failed")
        if not s.get("user_code"):
            raise HTTPException(status_code=504, detail="device-auth timed out before returning a user code")
        return {
            "session_id": sid,
            "flow": "device_code",
            "user_code": s["user_code"],
            "verification_url": s["verification_url"],
            "expires_in": int(s.get("expires_in") or 900),
            "poll_interval": int(s.get("interval") or 5),
        }

    if provider_id == "minimax-oauth":
        # MiniMax uses a device-code-style flow (verification URI + user
        # code + background poll) with a PKCE extension on top. From the
        # operator's perspective it's identical to Nous's device-code
        # flow; the PKCE bit (verifier + challenge from
        # _minimax_pkce_pair) is a security extension that binds the
        # token exchange to the original session.
        from hermes_cli.auth import (
            _minimax_pkce_pair,
            _minimax_request_user_code,
            MINIMAX_OAUTH_CLIENT_ID,
            MINIMAX_OAUTH_GLOBAL_BASE,
        )
        import httpx
        verifier, challenge, state = _minimax_pkce_pair()
        portal_base_url = (
            os.getenv("MINIMAX_PORTAL_BASE_URL") or MINIMAX_OAUTH_GLOBAL_BASE
        ).rstrip("/")
        def _do_minimax_request():
            with httpx.Client(
                timeout=httpx.Timeout(15.0),
                headers={"Accept": "application/json"},
                follow_redirects=True,
            ) as client:
                return _minimax_request_user_code(
                    client=client,
                    portal_base_url=portal_base_url,
                    client_id=MINIMAX_OAUTH_CLIENT_ID,
                    code_challenge=challenge,
                    state=state,
                )
        device_data = await asyncio.get_event_loop().run_in_executor(
            None, _do_minimax_request
        )
        sid, sess = _new_oauth_session("minimax-oauth", "device_code")
        # The CLI flow names this `interval_ms` because MiniMax's
        # `interval` field is in milliseconds (defensive default 2000ms
        # in _minimax_poll_token).
        interval_raw = device_data.get("interval")
        sess["interval_ms"] = (
            int(interval_raw) if interval_raw is not None else None
        )
        sess["user_code"] = str(device_data["user_code"])
        sess["code_verifier"] = verifier
        sess["state"] = state
        sess["portal_base_url"] = portal_base_url
        sess["client_id"] = MINIMAX_OAUTH_CLIENT_ID
        sess["region"] = "global"
        # `expired_in` from MiniMax is overloaded — could be a unix-ms
        # timestamp OR a seconds-from-now duration. Mirror the heuristic
        # in _minimax_poll_token. Stash the raw value for the poller;
        # compute a derived expires_at + UI-friendly expires_in seconds.
        expired_in_raw = int(device_data["expired_in"])
        sess["expired_in_raw"] = expired_in_raw
        if expired_in_raw > 1_000_000_000_000:  # likely unix-ms
            expires_at_ts = expired_in_raw / 1000.0
            expires_in_seconds = max(0, int(expires_at_ts - time.time()))
        else:
            expires_at_ts = time.time() + expired_in_raw
            expires_in_seconds = expired_in_raw
        sess["expires_at"] = expires_at_ts
        threading.Thread(
            target=_minimax_poller,
            args=(sid,),
            daemon=True,
            name=f"oauth-poll-{sid[:6]}",
        ).start()
        return {
            "session_id": sid,
            "flow": "device_code",
            "user_code": str(device_data["user_code"]),
            "verification_url": str(device_data["verification_uri"]),
            "expires_in": expires_in_seconds,
            "poll_interval": max(2, (sess["interval_ms"] or 2000) // 1000),
        }

    raise HTTPException(status_code=400, detail=f"Provider {provider_id} does not support device-code flow")


def _nous_poller(session_id: str) -> None:
    """Background poller that drives a Nous device-code flow to completion."""
    from hermes_cli.auth import (
        NOUS_INFERENCE_AUTH_MODE_FRESH,
        _poll_for_token,
        refresh_nous_oauth_from_state,
    )
    from datetime import datetime, timezone
    import httpx
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess:
        return
    portal_base_url = sess["portal_base_url"]
    client_id = sess["client_id"]
    device_code = sess["device_code"]
    interval = sess["interval"]
    scope = sess.get("scope")
    expires_in = max(60, int(sess["expires_at"] - time.time()))
    try:
        with httpx.Client(timeout=httpx.Timeout(15.0), headers={"Accept": "application/json"}) as client:
            token_data = _poll_for_token(
                client=client,
                portal_base_url=portal_base_url,
                client_id=client_id,
                device_code=device_code,
                expires_in=expires_in,
                poll_interval=interval,
            )
        # Same post-processing as _nous_device_code_login (mint agent key)
        now = datetime.now(timezone.utc)
        token_ttl = int(token_data.get("expires_in") or 0)
        auth_state = {
            "portal_base_url": portal_base_url,
            "inference_base_url": token_data.get("inference_base_url"),
            "client_id": client_id,
            "scope": token_data.get("scope") or scope,
            "token_type": token_data.get("token_type", "Bearer"),
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "obtained_at": now.isoformat(),
            "expires_at": (
                datetime.fromtimestamp(now.timestamp() + token_ttl, tz=timezone.utc).isoformat()
                if token_ttl else None
            ),
            "expires_in": token_ttl,
        }
        full_state = refresh_nous_oauth_from_state(
            auth_state,
            min_key_ttl_seconds=300,
            timeout_seconds=15.0,
            force_refresh=False,
            inference_auth_mode=NOUS_INFERENCE_AUTH_MODE_FRESH,
        )
        from hermes_cli.auth import persist_nous_credentials
        persist_nous_credentials(full_state)
        with _oauth_sessions_lock:
            sess["status"] = "approved"
        _log.info("oauth/device: nous login completed (session=%s)", session_id)
    except Exception as e:
        _log.warning("nous device-code poll failed (session=%s): %s", session_id, e)
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = str(e)


def _minimax_poller(session_id: str) -> None:
    """Background poller that drives a MiniMax OAuth flow to completion.

    Mirrors `_nous_poller` but calls the MiniMax-specific token endpoint,
    which uses a PKCE-style ``code_verifier`` + ``user_code`` rather than
    the ``device_code`` field used by Nous. On success, builds the same
    auth_state dict that ``_minimax_oauth_login`` (the CLI flow) builds
    and persists via ``_minimax_save_auth_state`` — so the dashboard
    path leaves the system in the same state as
    ``hermes auth add minimax-oauth``.
    """
    from hermes_cli.auth import (
        _minimax_poll_token,
        _minimax_resolve_token_expiry_unix,
        _minimax_save_auth_state,
        MINIMAX_OAUTH_GLOBAL_INFERENCE,
        MINIMAX_OAUTH_SCOPE,
    )
    from datetime import datetime, timezone
    import httpx
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess:
        return
    portal_base_url = sess["portal_base_url"]
    client_id = sess["client_id"]
    user_code = sess["user_code"]
    code_verifier = sess["code_verifier"]
    interval_ms = sess.get("interval_ms")
    expired_in_raw = sess["expired_in_raw"]
    try:
        with httpx.Client(
            timeout=httpx.Timeout(15.0),
            headers={"Accept": "application/json"},
            follow_redirects=True,
        ) as client:
            token_data = _minimax_poll_token(
                client=client,
                portal_base_url=portal_base_url,
                client_id=client_id,
                user_code=user_code,
                code_verifier=code_verifier,
                expired_in=expired_in_raw,
                interval_ms=interval_ms,
            )
        # Build the auth_state dict in the same shape as the CLI flow's
        # `_minimax_oauth_login` so `_minimax_save_auth_state` writes
        # the canonical record. Region is fixed to "global" for the
        # dashboard path; cn-region operators can still use the CLI
        # flow which supports `--region cn`.
        now = datetime.now(timezone.utc)
        expires_at_ts = _minimax_resolve_token_expiry_unix(
            int(token_data["expired_in"]), now=now,
        )
        expires_in_s = max(0, int(expires_at_ts - now.timestamp()))
        auth_state = {
            "provider": "minimax-oauth",
            "region": sess.get("region", "global"),
            "portal_base_url": portal_base_url,
            "inference_base_url": MINIMAX_OAUTH_GLOBAL_INFERENCE,
            "client_id": client_id,
            "scope": MINIMAX_OAUTH_SCOPE,
            "token_type": token_data.get("token_type", "Bearer"),
            "access_token": token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            "resource_url": token_data.get("resource_url"),
            "obtained_at": now.isoformat(),
            "expires_at": datetime.fromtimestamp(
                expires_at_ts, tz=timezone.utc
            ).isoformat(),
            "expires_in": expires_in_s,
        }
        _minimax_save_auth_state(auth_state)
        with _oauth_sessions_lock:
            sess["status"] = "approved"
        _log.info("oauth/device: minimax login completed (session=%s)", session_id)
    except Exception as e:
        _log.warning("minimax device-code poll failed (session=%s): %s", session_id, e)
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = str(e)


def _codex_full_login_worker(session_id: str) -> None:
    """Run the complete OpenAI Codex device-code flow.

    Codex doesn't use the standard OAuth device-code endpoints; it has its
    own ``/api/accounts/deviceauth/usercode`` (JSON body, returns
    ``device_auth_id``) and ``/api/accounts/deviceauth/token`` (JSON body
    polled until 200). On success the response carries an
    ``authorization_code`` + ``code_verifier`` that get exchanged at
    CODEX_OAUTH_TOKEN_URL with grant_type=authorization_code.

    The flow is replicated inline (rather than calling
    _codex_device_code_login) because that helper prints/blocks/polls in a
    single function — we need to surface the user_code to the dashboard the
    moment we receive it, well before polling completes.
    """
    try:
        import httpx
        from hermes_cli.auth import (
            CODEX_OAUTH_CLIENT_ID,
            CODEX_OAUTH_TOKEN_URL,
            DEFAULT_CODEX_BASE_URL,
        )
        issuer = "https://auth.openai.com"

        # Step 1: request device code
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            resp = client.post(
                f"{issuer}/api/accounts/deviceauth/usercode",
                json={"client_id": CODEX_OAUTH_CLIENT_ID},
                headers={"Content-Type": "application/json"},
            )
        if resp.status_code != 200:
            raise RuntimeError(f"deviceauth/usercode returned {resp.status_code}")
        device_data = resp.json()
        user_code = device_data.get("user_code", "")
        device_auth_id = device_data.get("device_auth_id", "")
        poll_interval = max(3, int(device_data.get("interval", "5")))
        if not user_code or not device_auth_id:
            raise RuntimeError("device-code response missing user_code or device_auth_id")
        verification_url = f"{issuer}/codex/device"
        with _oauth_sessions_lock:
            sess = _oauth_sessions.get(session_id)
            if not sess:
                return
            sess["user_code"] = user_code
            sess["verification_url"] = verification_url
            sess["device_auth_id"] = device_auth_id
            sess["interval"] = poll_interval
            sess["expires_in"] = 15 * 60  # OpenAI's effective limit
            sess["expires_at"] = time.time() + sess["expires_in"]

        # Step 2: poll until authorized
        deadline = time.monotonic() + sess["expires_in"]
        code_resp = None
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            while time.monotonic() < deadline:
                time.sleep(poll_interval)
                poll = client.post(
                    f"{issuer}/api/accounts/deviceauth/token",
                    json={"device_auth_id": device_auth_id, "user_code": user_code},
                    headers={"Content-Type": "application/json"},
                )
                if poll.status_code == 200:
                    code_resp = poll.json()
                    break
                if poll.status_code in {403, 404}:
                    continue  # user hasn't authorized yet
                raise RuntimeError(f"deviceauth/token poll returned {poll.status_code}")

        if code_resp is None:
            with _oauth_sessions_lock:
                sess["status"] = "expired"
                sess["error_message"] = "Device code expired before approval"
            return

        # Step 3: exchange authorization_code for tokens
        authorization_code = code_resp.get("authorization_code", "")
        code_verifier = code_resp.get("code_verifier", "")
        if not authorization_code or not code_verifier:
            raise RuntimeError("device-auth response missing authorization_code/code_verifier")
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            token_resp = client.post(
                CODEX_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": f"{issuer}/deviceauth/callback",
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if token_resp.status_code != 200:
            raise RuntimeError(f"token exchange returned {token_resp.status_code}")
        tokens = token_resp.json()
        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        if not access_token:
            raise RuntimeError("token exchange did not return access_token")

        # Persist via credential pool — same shape as auth_commands.add_command
        from agent.credential_pool import (
            PooledCredential,
            load_pool,
            AUTH_TYPE_OAUTH,
            SOURCE_MANUAL,
        )
        import uuid as _uuid
        pool = load_pool("openai-codex")
        base_url = (
            os.getenv("HERMES_CODEX_BASE_URL", "").strip().rstrip("/")
            or DEFAULT_CODEX_BASE_URL
        )
        entry = PooledCredential(
            provider="openai-codex",
            id=_uuid.uuid4().hex[:6],
            label="dashboard device_code",
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=f"{SOURCE_MANUAL}:dashboard_device_code",
            access_token=access_token,
            refresh_token=refresh_token,
            base_url=base_url,
        )
        pool.add_entry(entry)
        with _oauth_sessions_lock:
            sess["status"] = "approved"
        _log.info("oauth/device: openai-codex login completed (session=%s)", session_id)
    except Exception as e:
        _log.warning("codex device-code worker failed (session=%s): %s", session_id, e)
        with _oauth_sessions_lock:
            s = _oauth_sessions.get(session_id)
            if s:
                s["status"] = "error"
                s["error_message"] = str(e)


@app.post("/api/providers/oauth/{provider_id}/start")
async def start_oauth_login(provider_id: str, request: Request):
    """Initiate an OAuth login flow. Token-protected."""
    _require_token(request)
    _gc_oauth_sessions()
    valid = {p["id"] for p in _OAUTH_PROVIDER_CATALOG}
    if provider_id not in valid:
        raise HTTPException(status_code=400, detail=f"Unknown provider {provider_id}")
    catalog_entry = next(p for p in _OAUTH_PROVIDER_CATALOG if p["id"] == provider_id)
    if catalog_entry["flow"] == "external":
        raise HTTPException(
            status_code=400,
            detail=f"{provider_id} uses an external CLI; run `{catalog_entry['cli_command']}` manually",
        )
    try:
        # The pkce branch is gated on provider_id == "anthropic" because
        # `_start_anthropic_pkce()` is hardcoded to the Anthropic flow.
        # Routing any other future pkce-flagged provider through it would
        # silently launch the Anthropic OAuth flow (the bug fixed in this
        # change for MiniMax). New PKCE providers must add their own
        # start function and an explicit branch here.
        if catalog_entry["flow"] == "pkce" and provider_id == "anthropic":
            return _start_anthropic_pkce()
        if catalog_entry["flow"] == "device_code":
            return await _start_device_code_flow(provider_id)
    except HTTPException:
        raise
    except Exception as e:
        _log.exception("oauth/start %s failed", provider_id)
        raise HTTPException(status_code=500, detail=str(e))
    raise HTTPException(status_code=400, detail="Unsupported flow")


class OAuthSubmitBody(BaseModel):
    session_id: str
    code: str


@app.post("/api/providers/oauth/{provider_id}/submit")
async def submit_oauth_code(provider_id: str, body: OAuthSubmitBody, request: Request):
    """Submit the auth code for PKCE flows. Token-protected."""
    _require_token(request)
    if provider_id == "anthropic":
        return await asyncio.get_running_loop().run_in_executor(
            None, _submit_anthropic_pkce, body.session_id, body.code,
        )
    raise HTTPException(status_code=400, detail=f"submit not supported for {provider_id}")


@app.get("/api/providers/oauth/{provider_id}/poll/{session_id}")
async def poll_oauth_session(provider_id: str, session_id: str):
    """Poll a device-code session's status (no auth — read-only state)."""
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    if sess["provider"] != provider_id:
        raise HTTPException(status_code=400, detail="Provider mismatch for session")
    return {
        "session_id": session_id,
        "status": sess["status"],
        "error_message": sess.get("error_message"),
        "expires_at": sess.get("expires_at"),
    }


@app.delete("/api/providers/oauth/sessions/{session_id}")
async def cancel_oauth_session(session_id: str, request: Request):
    """Cancel a pending OAuth session. Token-protected."""
    _require_token(request)
    with _oauth_sessions_lock:
        sess = _oauth_sessions.pop(session_id, None)
    if sess is None:
        return {"ok": False, "message": "session not found"}
    return {"ok": True, "session_id": session_id}


# ---------------------------------------------------------------------------
# Provider API key upload — Sopify-specific.
#
# Replaces the terminal flow:
#     echo "$KEY" | sbx secret set -g anthropic
#     <update ~/.hermes/.env>
# with a single PUT /api/providers/api-key that writes to both stores.
# ---------------------------------------------------------------------------

try:  # plugin module — only present in Sopify installs
    from plugins.sopify_providers import (  # type: ignore
        providers_registry as _sopify_providers,
        sbx_secret as _sopify_sbx_secret,
        env_file as _sopify_env_file,
    )
    _SOPIFY_API_KEYS_AVAILABLE = True
except Exception:  # pragma: no cover — Hermes-only install
    _SOPIFY_API_KEYS_AVAILABLE = False


class ApiKeyUpdate(BaseModel):
    provider_id: str
    api_key: str
    sync_to_sbx_secret: bool = True


def _env_writable() -> bool:
    """True when the process can write ~/.hermes/.env.

    The sandbox launcher now bind-mounts ~/.hermes :rw so saving from inside
    the microVM works — but older sandboxes were created with :ro and there
    are still hosts where ~/.hermes lives on a read-only filesystem.  We probe
    `os.access` (or attempt-touch when the file doesn't yet exist) so the UI
    can disable the Save controls in those cases instead of letting the user
    type a key only to hit a 409.
    """
    env_path = _sopify_env_file.env_path()
    try:
        if env_path.exists():
            return os.access(str(env_path), os.W_OK)
        # File doesn't exist yet — check the parent dir's writability.
        parent = env_path.parent
        return parent.is_dir() and os.access(str(parent), os.W_OK)
    except OSError:
        return False


def _api_key_status_list() -> list[dict]:
    """Render the provider registry against the current key stores."""
    env_keys = _sopify_env_file.read_keys()
    sbx_services = _sopify_sbx_secret.list_services()
    sbx_ok = _sopify_sbx_secret.is_available()
    env_writable = _env_writable()
    out: list[dict] = []
    for p in _sopify_providers.PROVIDERS:
        env_value = env_keys.get(p.env_var, "").strip().strip('"').strip("'")
        set_in_env = bool(env_value) and env_value not in {"proxy-managed", "managed", "placeholder"}
        in_sbx = bool(p.sbx_service) and p.sbx_service.lower() in sbx_services
        out.append({
            "id": p.id,
            "label": p.label,
            "env_var": p.env_var,
            "sbx_service": p.sbx_service,
            "key_prefix": p.key_prefix,
            "docs_url": p.docs_url,
            "set_in_env": set_in_env,
            "set_in_sbx_secret": in_sbx,
            "redacted_value": redact_key(env_value) if set_in_env else None,
            "sbx_available": sbx_ok,
            "env_writable": env_writable,
        })
    return out


@app.get("/api/providers/api-key")
async def list_api_keys():
    """Return per-provider key status. Read-only — no auth required since
    only redacted previews are returned (`redact_key` shows first 4 + last 4
    of the key, never the full value)."""
    if not _SOPIFY_API_KEYS_AVAILABLE:
        raise HTTPException(status_code=501, detail="sopify_providers plugin not installed")
    return {"providers": _api_key_status_list()}


@app.put("/api/providers/api-key")
async def set_api_key(body: ApiKeyUpdate, request: Request):
    """Save an API key to ~/.hermes/.env and (optionally) the sbx secret store.

    Token-protected. Validates the provider id against the registry and
    optionally the expected key prefix. Never logs the raw value.
    """
    _require_token(request)
    if not _SOPIFY_API_KEYS_AVAILABLE:
        raise HTTPException(status_code=501, detail="sopify_providers plugin not installed")

    provider = _sopify_providers.by_id(body.provider_id)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {body.provider_id}")

    key = body.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="api_key is empty")
    if len(key) < 16:
        raise HTTPException(status_code=400, detail="api_key looks too short to be valid")
    if provider.key_prefix and not key.startswith(provider.key_prefix):
        raise HTTPException(
            status_code=400,
            detail=f"Key does not start with expected prefix '{provider.key_prefix}'",
        )

    # 1) Write to ~/.hermes/.env (always — needed for non-sandbox callers).
    try:
        _sopify_env_file.set_keys({provider.env_var: key})
    except OSError as exc:
        # Defensive: catch the EROFS case explicitly so legacy sandboxes
        # created with the old :ro mount (or hosts whose ~/.hermes lives on a
        # read-only filesystem) surface as 409 instead of a generic 500.
        _log.exception("PUT /api/providers/api-key — env write failed for %s", provider.id)
        if exc.errno == errno.EROFS:
            raise HTTPException(
                status_code=409,
                detail="~/.hermes/.env is on a read-only filesystem — cannot persist the key here.",
            )
        raise HTTPException(status_code=500, detail="Failed to write ~/.hermes/.env")
    except Exception:
        _log.exception("PUT /api/providers/api-key — env write failed for %s", provider.id)
        raise HTTPException(status_code=500, detail="Failed to write ~/.hermes/.env")
    _log.info("api-key saved to .env: provider=%s var=%s len=%d",
              provider.id, provider.env_var, len(key))

    # 2) Optionally sync to sbx secret store.
    sbx_synced = False
    sbx_error: str | None = None
    if (
        body.sync_to_sbx_secret
        and provider.sbx_service
        and _sopify_sbx_secret.is_available()
    ):
        # Only attempt the sync when sbx is reachable. is_available() returns
        # False inside the microVM (SOPIFY_IN_SANDBOX=1) since sbx is a
        # host-side controller — the caller will see sbx_available=false in
        # the GET response and can render that as "stored in .env only".
        ok, err = _sopify_sbx_secret.set_secret(provider.sbx_service, key)
        sbx_synced = ok
        if not ok:
            sbx_error = err
            _log.warning("sbx secret set failed for service=%s: %s", provider.sbx_service, err)
        else:
            _log.info("api-key synced to sbx secret store: service=%s", provider.sbx_service)

    return {
        "ok": True,
        "provider_id": provider.id,
        "synced_to_env": True,
        "synced_to_sbx_secret": sbx_synced,
        "sbx_secret_error": sbx_error,
        "redacted_value": redact_key(key),
    }


@app.delete("/api/providers/api-key/{provider_id}")
async def delete_api_key(provider_id: str, request: Request):
    """Remove a provider's key from both ~/.hermes/.env and sbx secret store."""
    _require_token(request)
    if not _SOPIFY_API_KEYS_AVAILABLE:
        raise HTTPException(status_code=501, detail="sopify_providers plugin not installed")
    provider = _sopify_providers.by_id(provider_id)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_id}")

    # Strip from env (no-op if absent).
    _sopify_env_file.set_keys({}, strip=[provider.env_var])

    # Strip from sbx store if applicable.
    sbx_removed = False
    sbx_error: str | None = None
    if provider.sbx_service and _sopify_sbx_secret.is_available():
        ok, err = _sopify_sbx_secret.remove_secret(provider.sbx_service)
        sbx_removed = ok
        if not ok:
            sbx_error = err

    _log.info("api-key removed: provider=%s", provider.id)
    return {
        "ok": True,
        "provider_id": provider.id,
        "removed_from_env": True,
        "removed_from_sbx_secret": sbx_removed,
        "sbx_secret_error": sbx_error,
    }


@app.post("/api/providers/api-key/test/{provider_id}")
async def test_api_key(provider_id: str, request: Request):
    """Smoke-test the stored key by hitting a cheap provider endpoint.

    Currently supports anthropic + openai. Other providers return
    `tested=False` (UI will fall back to "stored but not verified").
    """
    _require_token(request)
    if not _SOPIFY_API_KEYS_AVAILABLE:
        raise HTTPException(status_code=501, detail="sopify_providers plugin not installed")
    provider = _sopify_providers.by_id(provider_id)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_id}")

    env_keys = _sopify_env_file.read_keys()
    key = env_keys.get(provider.env_var, "").strip().strip('"').strip("'")
    if not key or key in {"proxy-managed", "managed", "placeholder"}:
        return {"tested": False, "ok": False, "reason": "no key stored"}

    import urllib.request
    import urllib.error

    if provider.id == "anthropic":
        url = "https://api.anthropic.com/v1/models"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    elif provider.id == "openai":
        url = "https://api.openai.com/v1/models"
        headers = {"Authorization": f"Bearer {key}"}
    elif provider.id == "alibaba":
        # Singapore intl endpoint (DASHSCOPE_BASE_URL override is supported
        # at the agent runtime, but for the test probe we hit the canonical
        # endpoint defined in hermes_cli.auth — same one the agent uses by
        # default).  Cheap GET /models confirms the key is accepted.
        base = os.environ.get("DASHSCOPE_BASE_URL", "").rstrip("/") \
            or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
        url = f"{base}/models"
        headers = {"Authorization": f"Bearer {key}"}
    else:
        return {"tested": False, "ok": False, "reason": "test not implemented for this provider"}

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return {"tested": True, "ok": True, "http_status": resp.status}
    except urllib.error.HTTPError as exc:
        return {"tested": True, "ok": False, "http_status": exc.code, "reason": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"tested": True, "ok": False, "reason": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Session detail endpoints
# ---------------------------------------------------------------------------



def _session_latest_descendant(session_id: str):
    """Resolve a session id to the newest child leaf session.

    /model may create child sessions. Dashboard refresh should continue the
    newest child instead of reopening the old parent.
    """
    from hermes_state import SessionDB

    def row_get(row, key, index):
        if isinstance(row, dict):
            return row.get(key)
        try:
            return row[key]
        except Exception:
            try:
                return row[index]
            except Exception:
                return None

    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid or not db.get_session(sid):
            return None, []

        conn = (
            getattr(db, "conn", None)
            or getattr(db, "_conn", None)
            or getattr(db, "connection", None)
            or getattr(db, "_connection", None)
        )

        rows = []
        if conn is not None:
            raw_rows = conn.execute(
                "SELECT id, parent_session_id, started_at FROM sessions"
            ).fetchall()
            for row in raw_rows:
                rows.append({
                    "id": row_get(row, "id", 0),
                    "parent_session_id": row_get(row, "parent_session_id", 1),
                    "started_at": row_get(row, "started_at", 2),
                })
        else:
            rows = db.list_sessions_rich(limit=10000, offset=0)

        children = {}
        for row in rows:
            rid = row.get("id")
            parent = row.get("parent_session_id")
            if rid and parent:
                children.setdefault(parent, []).append(row)

        def started(row):
            try:
                return float(row.get("started_at") or 0)
            except Exception:
                return 0.0

        current = sid
        path = [sid]
        seen = {sid}

        while children.get(current):
            candidates = [r for r in children[current] if r.get("id") not in seen]
            if not candidates:
                break
            candidates.sort(key=started, reverse=True)
            current = candidates[0]["id"]
            path.append(current)
            seen.add(current)

        return current, path
    finally:
        db.close()

@app.get("/api/sessions/{session_id}")
async def get_session_detail(session_id: str):
    from hermes_state import SessionDB
    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        session = db.get_session(sid) if sid else None
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    finally:
        db.close()



@app.get("/api/sessions/{session_id}/latest-descendant")
async def get_session_latest_descendant(session_id: str):
    latest, path = _session_latest_descendant(session_id)
    if not latest:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "requested_session_id": path[0] if path else session_id,
        "session_id": latest,
        "path": path,
        "changed": bool(path and latest != path[0]),
    }

@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    from hermes_state import SessionDB
    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
        messages = db.get_messages(sid)
        return {"session_id": sid, "messages": messages}
    finally:
        db.close()


@app.delete("/api/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    from hermes_state import SessionDB
    db = SessionDB()
    try:
        if not db.delete_session(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        return {"ok": True}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Log viewer endpoint
# ---------------------------------------------------------------------------


@app.get("/api/logs")
async def get_logs(
    file: str = "agent",
    lines: int = 100,
    level: Optional[str] = None,
    component: Optional[str] = None,
    search: Optional[str] = None,
):
    from hermes_cli.logs import _read_tail, LOG_FILES

    log_name = LOG_FILES.get(file)
    if not log_name:
        raise HTTPException(status_code=400, detail=f"Unknown log file: {file}")
    log_path = get_hermes_home() / "logs" / log_name
    if not log_path.exists():
        return {"file": file, "lines": []}

    try:
        from hermes_logging import COMPONENT_PREFIXES
    except ImportError:
        COMPONENT_PREFIXES = {}

    # Normalize "ALL" / "all" / empty → no filter. _matches_filters treats an
    # empty tuple as "must match a prefix" (startswith(()) is always False),
    # so passing () instead of None silently drops every line.
    min_level = level if level and level.upper() != "ALL" else None
    if component and component.lower() != "all":
        comp_prefixes = COMPONENT_PREFIXES.get(component)
        if comp_prefixes is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown component: {component}. "
                       f"Available: {', '.join(sorted(COMPONENT_PREFIXES))}",
            )
    else:
        comp_prefixes = None

    has_filters = bool(min_level or comp_prefixes or search)
    result = _read_tail(
        log_path, min(lines, 500) if not search else 2000,
        has_filters=has_filters,
        min_level=min_level,
        component_prefixes=comp_prefixes,
    )
    # Post-filter by search term (case-insensitive substring match).
    # _read_tail doesn't support free-text search, so we filter here and
    # trim to the requested line count afterward.
    if search:
        needle = search.lower()
        result = [l for l in result if needle in l.lower()][-min(lines, 500):]
    return {"file": file, "lines": result}


# ---------------------------------------------------------------------------
# Cron job management endpoints
# ---------------------------------------------------------------------------


class CronJobCreate(BaseModel):
    prompt: str
    schedule: str
    name: str = ""
    deliver: str = "local"


class CronJobUpdate(BaseModel):
    updates: dict


_CRON_PROFILE_LOCK = threading.RLock()


def _cron_profile_dicts() -> List[Dict[str, Any]]:
    """Return dashboard profile records, falling back to a directory scan."""
    from hermes_cli import profiles as profiles_mod
    try:
        return [_profile_to_dict(p) for p in profiles_mod.list_profiles()]
    except Exception:
        _log.exception("Failed to list profiles for cron dashboard; falling back to directory scan")
        return _fallback_profile_dicts(profiles_mod)


def _cron_profile_home(profile: Optional[str]) -> Tuple[str, Path]:
    """Resolve a profile query value to (profile_name, HERMES_HOME)."""
    from hermes_cli import profiles as profiles_mod

    raw = (profile or "default").strip() or "default"
    try:
        canon = profiles_mod.normalize_profile_name(raw)
        profiles_mod.validate_profile_name(canon)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not profiles_mod.profile_exists(canon):
        raise HTTPException(status_code=404, detail=f"Profile '{canon}' does not exist.")
    return canon, profiles_mod.get_profile_dir(canon)


def _annotate_cron_job(job: Dict[str, Any], profile: str, home: Path) -> Dict[str, Any]:
    annotated = dict(job)
    annotated["profile"] = profile
    annotated["profile_name"] = profile
    annotated["hermes_home"] = str(home)
    annotated["is_default_profile"] = profile == "default"
    return annotated


def _call_cron_for_profile(profile: Optional[str], func_name: str, *args, **kwargs):
    """Run cron.jobs helpers against the selected profile's cron directory.

    cron.jobs keeps CRON_DIR/JOBS_FILE/OUTPUT_DIR as module globals resolved
    from the process HERMES_HOME at import time. The dashboard is a single
    process that can inspect many profiles, so temporarily retarget those
    globals while holding a lock and restore them immediately after the call.
    """
    profile_name, home = _cron_profile_home(profile)
    with _CRON_PROFILE_LOCK:
        from cron import jobs as cron_jobs

        old_cron_dir = cron_jobs.CRON_DIR
        old_jobs_file = cron_jobs.JOBS_FILE
        old_output_dir = cron_jobs.OUTPUT_DIR
        cron_jobs.CRON_DIR = home / "cron"
        cron_jobs.JOBS_FILE = cron_jobs.CRON_DIR / "jobs.json"
        cron_jobs.OUTPUT_DIR = cron_jobs.CRON_DIR / "output"
        try:
            result = getattr(cron_jobs, func_name)(*args, **kwargs)
        finally:
            cron_jobs.CRON_DIR = old_cron_dir
            cron_jobs.JOBS_FILE = old_jobs_file
            cron_jobs.OUTPUT_DIR = old_output_dir

    if isinstance(result, list):
        return [_annotate_cron_job(j, profile_name, home) for j in result]
    if isinstance(result, dict):
        return _annotate_cron_job(result, profile_name, home)
    return result


def _find_cron_job_profile(job_id: str) -> Optional[str]:
    for profile in _cron_profile_dicts():
        name = str(profile.get("name") or "")
        if not name:
            continue
        jobs = _call_cron_for_profile(name, "list_jobs", True)
        if any(j.get("id") == job_id or j.get("name") == job_id for j in jobs):
            return name
    return None


@app.get("/api/cron/jobs")
async def list_cron_jobs(profile: str = "all"):
    requested = (profile or "all").strip()
    if requested.lower() != "all":
        return _call_cron_for_profile(requested, "list_jobs", True)

    jobs: List[Dict[str, Any]] = []
    for item in _cron_profile_dicts():
        name = str(item.get("name") or "")
        if not name:
            continue
        try:
            jobs.extend(_call_cron_for_profile(name, "list_jobs", True))
        except Exception:
            _log.exception("Failed to list cron jobs for profile %s", name)
    return jobs


@app.get("/api/cron/jobs/{job_id}")
async def get_cron_job(job_id: str, profile: Optional[str] = None):
    selected = profile or _find_cron_job_profile(job_id)
    if not selected:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _call_cron_for_profile(selected, "get_job", job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs")
async def create_cron_job(body: CronJobCreate, profile: str = "default"):
    try:
        return _call_cron_for_profile(
            profile,
            "create_job",
            prompt=body.prompt,
            schedule=body.schedule,
            name=body.name,
            deliver=body.deliver,
        )
    except Exception as e:
        _log.exception("POST /api/cron/jobs failed")
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/cron/jobs/{job_id}")
async def update_cron_job(job_id: str, body: CronJobUpdate, profile: Optional[str] = None):
    selected = profile or _find_cron_job_profile(job_id)
    if not selected:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _call_cron_for_profile(selected, "update_job", job_id, body.updates)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs/{job_id}/pause")
async def pause_cron_job(job_id: str, profile: Optional[str] = None):
    selected = profile or _find_cron_job_profile(job_id)
    if not selected:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _call_cron_for_profile(selected, "pause_job", job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs/{job_id}/resume")
async def resume_cron_job(job_id: str, profile: Optional[str] = None):
    selected = profile or _find_cron_job_profile(job_id)
    if not selected:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _call_cron_for_profile(selected, "resume_job", job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs/{job_id}/trigger")
async def trigger_cron_job(job_id: str, profile: Optional[str] = None):
    selected = profile or _find_cron_job_profile(job_id)
    if not selected:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _call_cron_for_profile(selected, "trigger_job", job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.delete("/api/cron/jobs/{job_id}")
async def delete_cron_job(job_id: str, profile: Optional[str] = None):
    selected = profile or _find_cron_job_profile(job_id)
    if not selected:
        raise HTTPException(status_code=404, detail="Job not found")
    if not _call_cron_for_profile(selected, "remove_job", job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Profile management endpoints (minimal — list/create/rename/delete + SOUL.md)
# ---------------------------------------------------------------------------


class ProfileCreate(BaseModel):
    name: str
    clone_from_default: bool = False
    no_skills: bool = False


class ProfileRename(BaseModel):
    new_name: str


class ProfileSoulUpdate(BaseModel):
    content: str


def _profile_attr(info, name: str, default: Any = None) -> Any:
    try:
        return getattr(info, name)
    except Exception:
        return default


def _profile_to_dict(info) -> Dict[str, Any]:
    return {
        "name": _profile_attr(info, "name", ""),
        "path": str(_profile_attr(info, "path", "")),
        "is_default": bool(_profile_attr(info, "is_default", False)),
        "model": _profile_attr(info, "model"),
        "provider": _profile_attr(info, "provider"),
        "has_env": bool(_profile_attr(info, "has_env", False)),
        "skill_count": int(_profile_attr(info, "skill_count", 0) or 0),
    }


def _fallback_profile_dicts(profiles_mod) -> List[Dict[str, Any]]:
    def _safe(callable_, default):
        try:
            return callable_()
        except Exception:
            return default

    profiles: List[Dict[str, Any]] = []
    default_home = profiles_mod._get_default_hermes_home()
    if default_home.is_dir():
        model, provider = _safe(lambda: profiles_mod._read_config_model(default_home), (None, None))
        profiles.append({
            "name": "default",
            "path": str(default_home),
            "is_default": True,
            "model": model,
            "provider": provider,
            "has_env": (default_home / ".env").exists(),
            "skill_count": _safe(lambda: profiles_mod._count_skills(default_home), 0),
        })

    profiles_root = profiles_mod._get_profiles_root()
    if profiles_root.is_dir():
        for entry in sorted(profiles_root.iterdir()):
            if not entry.is_dir() or not profiles_mod._PROFILE_ID_RE.match(entry.name):
                continue
            model, provider = _safe(lambda entry=entry: profiles_mod._read_config_model(entry), (None, None))
            profiles.append({
                "name": entry.name,
                "path": str(entry),
                "is_default": False,
                "model": model,
                "provider": provider,
                "has_env": (entry / ".env").exists(),
                "skill_count": _safe(lambda entry=entry: profiles_mod._count_skills(entry), 0),
            })

    return profiles


def _resolve_profile_dir(name: str) -> Path:
    """Validate ``name`` and resolve to its directory or raise an HTTPException."""
    from hermes_cli import profiles as profiles_mod
    try:
        profiles_mod.validate_profile_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not profiles_mod.profile_exists(name):
        raise HTTPException(status_code=404, detail=f"Profile '{name}' does not exist.")
    return profiles_mod.get_profile_dir(name)


def _profile_setup_command(name: str) -> str:
    """Return the shell command used to configure a profile in the CLI."""
    _resolve_profile_dir(name)
    return "hermes setup" if name == "default" else f"{name} setup"


@app.get("/api/profiles")
async def list_profiles_endpoint():
    from hermes_cli import profiles as profiles_mod
    try:
        return {"profiles": [_profile_to_dict(p) for p in profiles_mod.list_profiles()]}
    except Exception:
        _log.exception("GET /api/profiles failed; falling back to profile directory scan")
        return {"profiles": _fallback_profile_dicts(profiles_mod)}


@app.post("/api/profiles")
async def create_profile_endpoint(body: ProfileCreate):
    from hermes_cli import profiles as profiles_mod
    try:
        path = profiles_mod.create_profile(
            name=body.name,
            clone_from="default" if body.clone_from_default else None,
            clone_config=body.clone_from_default,
            no_skills=body.no_skills,
        )
        # Match the CLI's profile-create flow: fresh named profiles get the
        # bundled skills installed. When cloning from default, create_profile()
        # has already copied the source profile's skills, including any
        # user-installed skills. When no_skills=True, create_profile() wrote
        # the opt-out marker and seed_profile_skills() will no-op.
        if not body.clone_from_default:
            profiles_mod.seed_profile_skills(path, quiet=True)

        # Match the CLI's profile-create flow: named profiles should get a
        # wrapper in ~/.local/bin when the alias is safe to create.
        collision = profiles_mod.check_alias_collision(body.name)
        if not collision:
            profiles_mod.create_wrapper_script(body.name)
    except (ValueError, FileExistsError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _log.exception("POST /api/profiles failed")
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "name": body.name, "path": str(path)}


@app.get("/api/profiles/{name}/setup-command")
async def get_profile_setup_command(name: str):
    return {"command": _profile_setup_command(name)}


@app.post("/api/profiles/{name}/open-terminal")
async def open_profile_terminal_endpoint(name: str):
    try:
        command = _profile_setup_command(name)

        if sys.platform.startswith("win"):
            subprocess.Popen(["cmd.exe", "/c", "start", "", command])
        elif sys.platform == "darwin":
            escaped = command.replace("\\", "\\\\").replace('"', '\\"')
            applescript = (
                'tell application "Terminal"\n'
                "activate\n"
                f'do script "{escaped}"\n'
                "end tell"
            )
            subprocess.Popen(["osascript", "-e", applescript])
        else:
            terminal_commands = [
                ("x-terminal-emulator", ["x-terminal-emulator", "-e", "sh", "-lc", command]),
                ("gnome-terminal", ["gnome-terminal", "--", "sh", "-lc", command]),
                ("konsole", ["konsole", "-e", "sh", "-lc", command]),
                ("xfce4-terminal", ["xfce4-terminal", "-e", f"sh -lc '{command}'"]),
                ("mate-terminal", ["mate-terminal", "-e", f"sh -lc '{command}'"]),
                ("lxterminal", ["lxterminal", "-e", f"sh -lc '{command}'"]),
                ("tilix", ["tilix", "-e", "sh", "-lc", command]),
                ("alacritty", ["alacritty", "-e", "sh", "-lc", command]),
                ("kitty", ["kitty", "sh", "-lc", command]),
                ("xterm", ["xterm", "-e", "sh", "-lc", command]),
            ]
            for executable, popen_args in terminal_commands:
                if subprocess.call(
                    ["which", executable],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ) == 0:
                    subprocess.Popen(popen_args)
                    break
            else:
                raise HTTPException(
                    status_code=400,
                    detail="No supported terminal emulator found",
                )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        _log.exception("POST /api/profiles/%s/open-terminal failed", name)
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "command": command}


@app.patch("/api/profiles/{name}")
async def rename_profile_endpoint(name: str, body: ProfileRename):
    from hermes_cli import profiles as profiles_mod
    try:
        path = profiles_mod.rename_profile(name, body.new_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, FileExistsError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _log.exception("PATCH /api/profiles/%s failed", name)
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "name": body.new_name, "path": str(path)}


@app.delete("/api/profiles/{name}")
async def delete_profile_endpoint(name: str):
    """Delete a profile. The dashboard collects the user's confirmation in
    its own dialog before this request, so we always pass ``yes=True`` to
    skip the CLI's interactive prompt."""
    from hermes_cli import profiles as profiles_mod
    try:
        path = profiles_mod.delete_profile(name, yes=True)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _log.exception("DELETE /api/profiles/%s failed", name)
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "path": str(path)}


@app.get("/api/profiles/{name}/soul")
async def get_profile_soul(name: str):
    soul_path = _resolve_profile_dir(name) / "SOUL.md"
    if soul_path.exists():
        try:
            return {"content": soul_path.read_text(encoding="utf-8"), "exists": True}
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Could not read SOUL.md: {e}")
    return {"content": "", "exists": False}


@app.put("/api/profiles/{name}/soul")
async def update_profile_soul(name: str, body: ProfileSoulUpdate):
    soul_path = _resolve_profile_dir(name) / "SOUL.md"
    try:
        soul_path.write_text(body.content, encoding="utf-8")
    except OSError as e:
        _log.exception("PUT /api/profiles/%s/soul failed", name)
        raise HTTPException(status_code=500, detail=f"Could not write SOUL.md: {e}")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Skills & Tools endpoints
# ---------------------------------------------------------------------------


class SkillToggle(BaseModel):
    name: str
    enabled: bool


@app.get("/api/skills")
async def get_skills():
    from tools.skills_tool import _find_all_skills
    from hermes_cli.skills_config import get_disabled_skills
    config = load_config()
    disabled = get_disabled_skills(config)
    skills = _find_all_skills(skip_disabled=True)
    for s in skills:
        s["enabled"] = s["name"] not in disabled
    return skills


@app.put("/api/skills/toggle")
async def toggle_skill(body: SkillToggle):
    from hermes_cli.skills_config import get_disabled_skills, save_disabled_skills
    config = load_config()
    disabled = get_disabled_skills(config)
    if body.enabled:
        disabled.discard(body.name)
    else:
        disabled.add(body.name)
    save_disabled_skills(config, disabled)
    return {"ok": True, "name": body.name, "enabled": body.enabled}


@app.get("/api/tools/toolsets")
async def get_toolsets():
    from hermes_cli.tools_config import (
        _get_effective_configurable_toolsets,
        _get_platform_tools,
        _toolset_has_keys,
    )
    from toolsets import resolve_toolset

    config = load_config()
    enabled_toolsets = _get_platform_tools(
        config,
        "cli",
        include_default_mcp_servers=False,
    )
    result = []
    for name, label, desc in _get_effective_configurable_toolsets():
        try:
            tools = sorted(set(resolve_toolset(name)))
        except Exception:
            tools = []
        is_enabled = name in enabled_toolsets
        result.append({
            "name": name, "label": label, "description": desc,
            "enabled": is_enabled,
            "available": is_enabled,
            "configured": _toolset_has_keys(name, config),
            "tools": tools,
        })
    return result


# ---------------------------------------------------------------------------
# Raw YAML config endpoint
# ---------------------------------------------------------------------------


class RawConfigUpdate(BaseModel):
    yaml_text: str


@app.get("/api/config/raw")
async def get_config_raw():
    path = get_config_path()
    if not path.exists():
        return {"yaml": ""}
    return {"yaml": path.read_text(encoding="utf-8")}


@app.put("/api/config/raw")
async def update_config_raw(body: RawConfigUpdate):
    try:
        parsed = yaml.safe_load(body.yaml_text)
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="YAML must be a mapping")
        save_config(parsed)
        return {"ok": True}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")


# ---------------------------------------------------------------------------
# Token / cost analytics endpoint
# ---------------------------------------------------------------------------


@app.get("/api/analytics/usage")
async def get_usage_analytics(days: int = 30):
    from hermes_state import SessionDB
    from agent.insights import InsightsEngine

    db = SessionDB()
    try:
        cutoff = time.time() - (days * 86400)
        cur = db._conn.execute("""
            SELECT date(started_at, 'unixepoch') as day,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   SUM(cache_read_tokens) as cache_read_tokens,
                   SUM(reasoning_tokens) as reasoning_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as actual_cost,
                   COUNT(*) as sessions,
                   SUM(COALESCE(api_call_count, 0)) as api_calls
            FROM sessions WHERE started_at > ?
            GROUP BY day ORDER BY day
        """, (cutoff,))
        daily = [dict(r) for r in cur.fetchall()]

        cur2 = db._conn.execute("""
            SELECT model,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COUNT(*) as sessions,
                   SUM(COALESCE(api_call_count, 0)) as api_calls
            FROM sessions WHERE started_at > ? AND model IS NOT NULL
            GROUP BY model ORDER BY SUM(input_tokens) + SUM(output_tokens) DESC
        """, (cutoff,))
        by_model = [dict(r) for r in cur2.fetchall()]

        cur3 = db._conn.execute("""
            SELECT SUM(input_tokens) as total_input,
                   SUM(output_tokens) as total_output,
                   SUM(cache_read_tokens) as total_cache_read,
                   SUM(reasoning_tokens) as total_reasoning,
                   COALESCE(SUM(estimated_cost_usd), 0) as total_estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as total_actual_cost,
                   COUNT(*) as total_sessions,
                   SUM(COALESCE(api_call_count, 0)) as total_api_calls
            FROM sessions WHERE started_at > ?
        """, (cutoff,))
        totals = dict(cur3.fetchone())
        insights_report = InsightsEngine(db).generate(days=days)
        skills = insights_report.get("skills", {
            "summary": {
                "total_skill_loads": 0,
                "total_skill_edits": 0,
                "total_skill_actions": 0,
                "distinct_skills_used": 0,
            },
            "top_skills": [],
        })

        return {
            "daily": daily,
            "by_model": by_model,
            "totals": totals,
            "period_days": days,
            "skills": skills,
        }
    finally:
        db.close()


@app.get("/api/analytics/models")
async def get_models_analytics(days: int = 30):
    """Rich per-model analytics for the Models dashboard page.

    Returns token/cost/session breakdown per model plus capability metadata
    from models.dev (context window, vision, tools, reasoning, etc.).
    """
    from hermes_state import SessionDB

    db = SessionDB()
    try:
        cutoff = time.time() - (days * 86400)

        cur = db._conn.execute("""
            SELECT model,
                   billing_provider,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   SUM(cache_read_tokens) as cache_read_tokens,
                   SUM(reasoning_tokens) as reasoning_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as actual_cost,
                   COUNT(*) as sessions,
                   SUM(COALESCE(api_call_count, 0)) as api_calls,
                   SUM(tool_call_count) as tool_calls,
                   MAX(started_at) as last_used_at,
                   AVG(input_tokens + output_tokens) as avg_tokens_per_session
            FROM sessions WHERE started_at > ? AND model IS NOT NULL AND model != ''
            GROUP BY model, billing_provider
            ORDER BY SUM(input_tokens) + SUM(output_tokens) DESC
        """, (cutoff,))
        rows = [dict(r) for r in cur.fetchall()]

        models = []
        for row in rows:
            provider = row.get("billing_provider") or ""
            model_name = row["model"]
            caps = {}
            try:
                from agent.models_dev import get_model_capabilities
                mc = get_model_capabilities(provider=provider, model=model_name)
                if mc is not None:
                    caps = {
                        "supports_tools": mc.supports_tools,
                        "supports_vision": mc.supports_vision,
                        "supports_reasoning": mc.supports_reasoning,
                        "context_window": mc.context_window,
                        "max_output_tokens": mc.max_output_tokens,
                        "model_family": mc.model_family,
                    }
            except Exception:
                pass

            models.append({
                "model": model_name,
                "provider": provider,
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cache_read_tokens": row["cache_read_tokens"],
                "reasoning_tokens": row["reasoning_tokens"],
                "estimated_cost": row["estimated_cost"],
                "actual_cost": row["actual_cost"],
                "sessions": row["sessions"],
                "api_calls": row["api_calls"],
                "tool_calls": row["tool_calls"],
                "last_used_at": row["last_used_at"],
                "avg_tokens_per_session": row["avg_tokens_per_session"],
                "capabilities": caps,
            })

        totals_cur = db._conn.execute("""
            SELECT COUNT(DISTINCT model) as distinct_models,
                   SUM(input_tokens) as total_input,
                   SUM(output_tokens) as total_output,
                   SUM(cache_read_tokens) as total_cache_read,
                   SUM(reasoning_tokens) as total_reasoning,
                   COALESCE(SUM(estimated_cost_usd), 0) as total_estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as total_actual_cost,
                   COUNT(*) as total_sessions,
                   SUM(COALESCE(api_call_count, 0)) as total_api_calls
            FROM sessions WHERE started_at > ? AND model IS NOT NULL AND model != ''
        """, (cutoff,))
        totals = dict(totals_cur.fetchone())

        return {
            "models": models,
            "totals": totals,
            "period_days": days,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# /api/pty — PTY-over-WebSocket bridge for the dashboard "Chat" tab.
#
# The endpoint spawns the same ``hermes --tui`` binary the CLI uses, behind
# a POSIX pseudo-terminal, and forwards bytes + resize escapes across a
# WebSocket.  The browser renders the ANSI through xterm.js (see
# web/src/pages/ChatPage.tsx).
#
# Auth: ``?token=<session_token>`` query param (browsers can't set
# Authorization on the WS upgrade).  Same ephemeral ``_SESSION_TOKEN`` as
# REST.  Localhost-only — we defensively reject non-loopback clients even
# though uvicorn binds to 127.0.0.1.
# ---------------------------------------------------------------------------

import re
import asyncio

# PTY bridge is POSIX-only (depends on fcntl/termios/ptyprocess).  On native
# Windows the import raises; catch and leave PtyBridge=None so the rest of
# the dashboard (sessions, jobs, metrics, config editor) still loads and the
# /api/pty endpoint cleanly refuses with a WSL-suggested message.
try:
    from hermes_cli.pty_bridge import PtyBridge, PtyUnavailableError
    _PTY_BRIDGE_AVAILABLE = True
except ImportError as _pty_import_err:  # pragma: no cover - Windows-only path
    PtyBridge = None  # type: ignore[assignment]
    _PTY_BRIDGE_AVAILABLE = False

    class PtyUnavailableError(RuntimeError):  # type: ignore[no-redef]
        """Stub on platforms where pty_bridge can't be imported."""
        pass

_RESIZE_RE = re.compile(rb"\x1b\[RESIZE:(\d+);(\d+)\]")
_PTY_READ_CHUNK_TIMEOUT = 0.2
_VALID_CHANNEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
# Starlette's TestClient reports the peer as "testclient"; treat it as
# loopback so tests don't need to rewrite request scope.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def _is_public_bind() -> bool:
    """True when bound to all-interfaces (operator used --insecure)."""
    return getattr(app.state, "bound_host", "") in {"0.0.0.0", "::"}


def _ws_client_is_allowed(ws: "WebSocket") -> bool:
    """Check if the WebSocket client IP is acceptable.

    Allows loopback always; allows any IP when bound to all-interfaces
    (--insecure mode, guarded by session token auth).
    """
    if _is_public_bind():
        return True
    client_host = ws.client.host if ws.client else ""
    if not client_host:
        return True
    return client_host in _LOOPBACK_HOSTS

# Per-channel subscriber registry used by /api/pub (PTY-side gateway → dashboard)
# and /api/events (dashboard → browser sidebar).  Keyed by an opaque channel id
# the chat tab generates on mount; entries auto-evict when the last subscriber
# drops AND the publisher has disconnected.
_event_channels: dict[str, set] = {}
_event_lock = asyncio.Lock()


def _resolve_chat_argv(
    resume: Optional[str] = None,
    sidecar_url: Optional[str] = None,
) -> tuple[list[str], Optional[str], Optional[dict]]:
    """Resolve the argv + cwd + env for the chat PTY.

    Default: whatever ``hermes --tui`` would run.  Tests monkeypatch this
    function to inject a tiny fake command (``cat``, ``sh -c 'printf …'``)
    so nothing has to build Node or the TUI bundle.

    Session resume is propagated via the ``HERMES_TUI_RESUME`` env var —
    matching what ``hermes_cli.main._launch_tui`` does for the CLI path.
    Appending ``--resume <id>`` to argv doesn't work because ``ui-tui`` does
    not parse its argv.

    `sidecar_url` (when set) is forwarded as ``HERMES_TUI_SIDECAR_URL`` so
    the spawned ``tui_gateway.entry`` can mirror dispatcher emits to the
    dashboard's ``/api/pub`` endpoint (see :func:`pub_ws`).
    """
    from hermes_cli.main import PROJECT_ROOT, _make_tui_argv

    argv, cwd = _make_tui_argv(PROJECT_ROOT / "ui-tui", tui_dev=False)
    env = os.environ.copy()
    env.setdefault("NODE_ENV", "production")
    # Browser-embedded chat should prefer stable wheel-based scrollback over
    # native terminal mouse tracking. When mouse tracking is enabled, wheel
    # events are consumed by the TUI and forwarded as terminal input, which
    # makes browser-side transcript scrolling feel broken. Keep the terminal
    # build unchanged for native CLI usage; only disable mouse tracking for
    # the dashboard PTY path.
    env.setdefault("HERMES_TUI_DISABLE_MOUSE", "1")
    env.setdefault("HERMES_TUI_INLINE", "1")

    if resume:
        latest_resume, _latest_path = _session_latest_descendant(resume)
        if latest_resume:
            resume = latest_resume
        env["HERMES_TUI_RESUME"] = resume

    if sidecar_url:
        env["HERMES_TUI_SIDECAR_URL"] = sidecar_url

    return list(argv), str(cwd) if cwd else None, env


def _build_sidecar_url(channel: str) -> Optional[str]:
    """ws:// URL the PTY child should publish events to, or None when unbound."""
    host = getattr(app.state, "bound_host", None)
    port = getattr(app.state, "bound_port", None)

    if not host or not port:
        return None

    netloc = f"[{host}]:{port}" if ":" in host and not host.startswith("[") else f"{host}:{port}"
    qs = urllib.parse.urlencode({"token": _SESSION_TOKEN, "channel": channel})

    return f"ws://{netloc}/api/pub?{qs}"


async def _broadcast_event(channel: str, payload: str) -> None:
    """Fan out one publisher frame to every subscriber on `channel`."""
    async with _event_lock:
        subs = list(_event_channels.get(channel, ()))

    for sub in subs:
        try:
            await sub.send_text(payload)
        except Exception:
            # Subscriber went away mid-send; the /api/events finally clause
            # will remove it from the registry on its next iteration.
            pass


def _channel_or_close_code(ws: WebSocket) -> Optional[str]:
    """Return the channel id from the query string or None if invalid."""
    channel = ws.query_params.get("channel", "")

    return channel if _VALID_CHANNEL_RE.match(channel) else None


@app.websocket("/api/pty")
async def pty_ws(ws: WebSocket) -> None:
    if not _DASHBOARD_EMBEDDED_CHAT_ENABLED:
        await ws.close(code=4403)
        return

    # --- auth + loopback check (before accept so we can close cleanly) ---
    token = ws.query_params.get("token", "")
    expected = _SESSION_TOKEN
    if not hmac.compare_digest(token.encode(), expected.encode()):
        await ws.close(code=4401)
        return

    if not _ws_client_is_allowed(ws):
        await ws.close(code=4403)
        return

    await ws.accept()

    # On native Windows, the POSIX PTY bridge can't be imported.  Tell the
    # client and close cleanly rather than pretending the feature works.
    if not _PTY_BRIDGE_AVAILABLE:
        await ws.send_text(
            "\r\n\x1b[31mChat unavailable: the embedded terminal requires a "
            "POSIX PTY, which native Windows Python doesn't provide.\x1b[0m\r\n"
            "\x1b[33mInstall Hermes inside WSL2 to use the dashboard's /chat "
            "tab — the rest of the dashboard works here.\x1b[0m\r\n"
        )
        await ws.close(code=1011)
        return

    # --- spawn PTY ------------------------------------------------------
    resume = ws.query_params.get("resume") or None
    channel = _channel_or_close_code(ws)
    sidecar_url = _build_sidecar_url(channel) if channel else None

    try:
        argv, cwd, env = _resolve_chat_argv(resume=resume, sidecar_url=sidecar_url)
    except SystemExit as exc:
        # _make_tui_argv calls sys.exit(1) when node/npm is missing.
        await ws.send_text(f"\r\n\x1b[31mChat unavailable: {exc}\x1b[0m\r\n")
        await ws.close(code=1011)
        return


    try:
        bridge = PtyBridge.spawn(argv, cwd=cwd, env=env)
    except PtyUnavailableError as exc:
        await ws.send_text(f"\r\n\x1b[31mChat unavailable: {exc}\x1b[0m\r\n")
        await ws.close(code=1011)
        return
    except (FileNotFoundError, OSError) as exc:
        await ws.send_text(f"\r\n\x1b[31mChat failed to start: {exc}\x1b[0m\r\n")
        await ws.close(code=1011)
        return

    loop = asyncio.get_running_loop()

    # --- reader task: PTY master → WebSocket ----------------------------
    async def pump_pty_to_ws() -> None:
        while True:
            chunk = await loop.run_in_executor(
                None, bridge.read, _PTY_READ_CHUNK_TIMEOUT
            )
            if chunk is None:  # EOF
                return
            if not chunk:  # no data this tick; yield control and retry
                await asyncio.sleep(0)
                continue
            try:
                await ws.send_bytes(chunk)
            except Exception:
                return

    reader_task = asyncio.create_task(pump_pty_to_ws())

    # --- writer loop: WebSocket → PTY master ----------------------------
    try:
        while True:
            msg = await ws.receive()
            msg_type = msg.get("type")
            if msg_type == "websocket.disconnect":
                break
            raw = msg.get("bytes")
            if raw is None:
                text = msg.get("text")
                raw = text.encode("utf-8") if isinstance(text, str) else b""
            if not raw:
                continue

            # Resize escape is consumed locally, never written to the PTY.
            match = _RESIZE_RE.match(raw)
            if match and match.end() == len(raw):
                cols = int(match.group(1))
                rows = int(match.group(2))
                bridge.resize(cols=cols, rows=rows)
                continue

            bridge.write(raw)
    except WebSocketDisconnect:
        pass
    finally:
        reader_task.cancel()
        try:
            await reader_task
        except (asyncio.CancelledError, Exception):
            pass
        bridge.close()


# ---------------------------------------------------------------------------
# /api/ws — JSON-RPC WebSocket sidecar for the dashboard "Chat" tab.
#
# Drives the same `tui_gateway.dispatch` surface Ink uses over stdio, so the
# dashboard can render structured metadata (model badge, tool-call sidebar,
# slash launcher, session info) alongside the xterm.js terminal that PTY
# already paints. Both transports bind to the same session id when one is
# active, so a tool.start emitted by the agent fans out to both sinks.
# ---------------------------------------------------------------------------


@app.websocket("/api/ws")
async def gateway_ws(ws: WebSocket) -> None:
    if not _DASHBOARD_EMBEDDED_CHAT_ENABLED:
        await ws.close(code=4403)
        return

    token = ws.query_params.get("token", "")
    if not hmac.compare_digest(token.encode(), _SESSION_TOKEN.encode()):
        await ws.close(code=4401)
        return

    if not _ws_client_is_allowed(ws):
        await ws.close(code=4403)
        return

    from tui_gateway.ws import handle_ws

    await handle_ws(ws)


# ---------------------------------------------------------------------------
# /api/pub + /api/events — chat-tab event broadcast.
#
# The PTY-side ``tui_gateway.entry`` opens /api/pub at startup (driven by
# HERMES_TUI_SIDECAR_URL set in /api/pty's PTY env) and writes every
# dispatcher emit through it.  The dashboard fans those frames out to any
# subscriber that opened /api/events on the same channel id.  This is what
# gives the React sidebar its tool-call feed without breaking the PTY
# child's stdio handshake with Ink.
# ---------------------------------------------------------------------------


@app.websocket("/api/pub")
async def pub_ws(ws: WebSocket) -> None:
    if not _DASHBOARD_EMBEDDED_CHAT_ENABLED:
        await ws.close(code=4403)
        return

    token = ws.query_params.get("token", "")
    if not hmac.compare_digest(token.encode(), _SESSION_TOKEN.encode()):
        await ws.close(code=4401)
        return

    if not _ws_client_is_allowed(ws):
        await ws.close(code=4403)
        return

    channel = _channel_or_close_code(ws)
    if not channel:
        await ws.close(code=4400)
        return

    await ws.accept()

    try:
        while True:
            await _broadcast_event(channel, await ws.receive_text())
    except WebSocketDisconnect:
        pass


@app.websocket("/api/events")
async def events_ws(ws: WebSocket) -> None:
    if not _DASHBOARD_EMBEDDED_CHAT_ENABLED:
        await ws.close(code=4403)
        return

    token = ws.query_params.get("token", "")
    if not hmac.compare_digest(token.encode(), _SESSION_TOKEN.encode()):
        await ws.close(code=4401)
        return

    if not _ws_client_is_allowed(ws):
        await ws.close(code=4403)
        return

    channel = _channel_or_close_code(ws)
    if not channel:
        await ws.close(code=4400)
        return

    await ws.accept()

    async with _event_lock:
        _event_channels.setdefault(channel, set()).add(ws)

    try:
        while True:
            # Subscribers don't speak — the receive() just blocks until
            # disconnect so the connection stays open as long as the
            # browser holds it.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with _event_lock:
            subs = _event_channels.get(channel)

            if subs is not None:
                subs.discard(ws)

                if not subs:
                    _event_channels.pop(channel, None)


def _normalise_prefix(raw: Optional[str]) -> str:
    """Normalise an X-Forwarded-Prefix header value.

    Returns a string like ``"/hermes"`` (no trailing slash) or ``""`` when
    no prefix is set / the header is malformed. We deliberately reject
    anything containing ``..`` or non-printable bytes so a hostile proxy
    can't inject HTML via the prefix.
    """
    if not raw:
        return ""
    p = raw.strip()
    if not p:
        return ""
    if not p.startswith("/"):
        p = "/" + p
    p = p.rstrip("/")
    if "//" in p or ".." in p or any(c in p for c in ('"', "'", "<", ">", " ", "\n", "\r", "\t")):
        return ""
    if len(p) > 64:
        return ""
    return p


def mount_spa(application: FastAPI):
    """Mount the built SPA. Falls back to index.html for client-side routing.

    The session token is injected into index.html via a ``<script>`` tag so
    the SPA can authenticate against protected API endpoints without a
    separate (unauthenticated) token-dispensing endpoint.

    When served behind a path-prefix reverse proxy (e.g.
    ``mission-control.tilos.com/hermes/*`` -> local Caddy -> :9119), the
    proxy injects ``X-Forwarded-Prefix: /hermes`` on every request. We
    rewrite the served ``index.html`` so absolute asset URLs (``/assets/...``)
    and the SPA's runtime ``__HERMES_BASE_PATH__`` honour that prefix
    without rebuilding the bundle.
    """
    if not WEB_DIST.exists():
        @application.get("/{full_path:path}")
        async def no_frontend(full_path: str):
            return JSONResponse(
                {"error": "Frontend not built. Run: cd web && npm run build"},
                status_code=404,
            )
        return

    _index_path = WEB_DIST / "index.html"

    def _serve_index(prefix: str = ""):
        """Return index.html with the session token + base-path injected.

        ``prefix`` is the normalised ``X-Forwarded-Prefix`` (e.g. ``/hermes``)
        or empty string when served at root.
        """
        html = _index_path.read_text()
        chat_js = "true" if _DASHBOARD_EMBEDDED_CHAT_ENABLED else "false"
        token_script = (
            f'<script>window.__HERMES_SESSION_TOKEN__="{_SESSION_TOKEN}";'
            f"window.__HERMES_DASHBOARD_EMBEDDED_CHAT__={chat_js};"
            f'window.__HERMES_BASE_PATH__="{prefix}";</script>'
        )
        if prefix:
            # Rewrite absolute asset URLs baked into the Vite build so the
            # browser fetches them through the same proxy prefix.
            html = html.replace('href="/assets/', f'href="{prefix}/assets/')
            html = html.replace('src="/assets/', f'src="{prefix}/assets/')
            html = html.replace('href="/favicon.ico"', f'href="{prefix}/favicon.ico"')
            html = html.replace('href="/fonts/', f'href="{prefix}/fonts/')
            html = html.replace('href="/ds-assets/', f'href="{prefix}/ds-assets/')
            html = html.replace('src="/ds-assets/', f'src="{prefix}/ds-assets/')
        html = html.replace("</head>", f"{token_script}</head>", 1)
        return HTMLResponse(
            html,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    # When served behind a path-prefix proxy, the built CSS contains
    # absolute ``url(/fonts/...)`` and ``url(/ds-assets/...)`` references.
    # Browsers resolve those against the document origin, which means
    # under ``/hermes`` they'd hit ``mission-control.tilos.com/fonts/...``
    # (the MC Pages app), not the Hermes backend. Intercept CSS asset
    # requests BEFORE the StaticFiles mount and rewrite the absolute paths
    # when a prefix is in play.
    @application.get("/assets/{filename}.css")
    async def serve_css(filename: str, request: Request):
        css_path = WEB_DIST / "assets" / f"{filename}.css"
        if not css_path.is_file() or not css_path.resolve().is_relative_to(
            WEB_DIST.resolve()
        ):
            return JSONResponse({"error": "not found"}, status_code=404)
        prefix = _normalise_prefix(request.headers.get("x-forwarded-prefix"))
        css = css_path.read_text()
        if prefix:
            for asset_dir in ("/fonts/", "/fonts-terminal/", "/ds-assets/", "/assets/"):
                css = css.replace(f"url({asset_dir}", f"url({prefix}{asset_dir}")
                css = css.replace(f"url(\"{asset_dir}", f"url(\"{prefix}{asset_dir}")
                css = css.replace(f"url('{asset_dir}", f"url('{prefix}{asset_dir}")
        return Response(content=css, media_type="text/css")

    application.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @application.get("/{full_path:path}")
    async def serve_spa(full_path: str, request: Request):
        prefix = _normalise_prefix(request.headers.get("x-forwarded-prefix"))
        file_path = WEB_DIST / full_path
        # Prevent path traversal via url-encoded sequences (%2e%2e/)
        if (
            full_path
            and file_path.resolve().is_relative_to(WEB_DIST.resolve())
            and file_path.exists()
            and file_path.is_file()
        ):
            return FileResponse(file_path)
        return _serve_index(prefix)


# ---------------------------------------------------------------------------
# Dashboard plugin system
# ---------------------------------------------------------------------------

def _discover_dashboard_plugins() -> list:
    """Scan plugins/*/dashboard/manifest.json for dashboard extensions.

    Checks three plugin sources (same as hermes_cli.plugins):
    1. User plugins:    ~/.hermes/plugins/<name>/dashboard/manifest.json
    2. Bundled plugins: <repo>/plugins/<name>/dashboard/manifest.json  (memory/, etc.)
    3. Project plugins: ./.hermes/plugins/  (only if HERMES_ENABLE_PROJECT_PLUGINS)
    """
    plugins = []
    seen_names: set = set()

    from hermes_cli.plugins import get_bundled_plugins_dir
    bundled_root = get_bundled_plugins_dir()
    search_dirs = [
        (get_hermes_home() / "plugins", "user"),
        (bundled_root / "memory", "bundled"),
        (bundled_root, "bundled"),
    ]
    if os.environ.get("HERMES_ENABLE_PROJECT_PLUGINS"):
        search_dirs.append((Path.cwd() / ".hermes" / "plugins", "project"))

    for plugins_root, source in search_dirs:
        if not plugins_root.is_dir():
            continue
        for child in sorted(plugins_root.iterdir()):
            if not child.is_dir():
                continue
            manifest_file = child / "dashboard" / "manifest.json"
            if not manifest_file.exists():
                continue
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                name = data.get("name", child.name)
                if name in seen_names:
                    continue
                seen_names.add(name)
                # Tab options: ``path`` + ``position`` for a new tab, optional
                # ``override`` to replace a built-in route, and ``hidden`` to
                # register the plugin component/slots without adding a tab
                # (useful for slot-only plugins like a header-crest injector).
                raw_tab = data.get("tab", {}) if isinstance(data.get("tab"), dict) else {}
                tab_info = {
                    "path": raw_tab.get("path", f"/{name}"),
                    "position": raw_tab.get("position", "end"),
                }
                override_path = raw_tab.get("override")
                if isinstance(override_path, str) and override_path.startswith("/"):
                    tab_info["override"] = override_path
                if bool(raw_tab.get("hidden")):
                    tab_info["hidden"] = True
                # Slots: list of named slot locations this plugin populates.
                # The frontend exposes ``registerSlot(pluginName, slotName, Component)``
                # on window; plugins with non-empty slots call it from their JS bundle.
                slots_src = data.get("slots")
                slots: List[str] = []
                if isinstance(slots_src, list):
                    slots = [s for s in slots_src if isinstance(s, str) and s]
                plugins.append({
                    "name": name,
                    "label": data.get("label", name),
                    "description": data.get("description", ""),
                    "icon": data.get("icon", "Puzzle"),
                    "version": data.get("version", "0.0.0"),
                    "tab": tab_info,
                    "slots": slots,
                    "entry": data.get("entry", "dist/index.js"),
                    "css": data.get("css"),
                    "has_api": bool(data.get("api")),
                    "source": source,
                    "_dir": str(child / "dashboard"),
                    "_api_file": data.get("api"),
                })
            except Exception as exc:
                _log.warning("Bad dashboard plugin manifest %s: %s", manifest_file, exc)
                continue
    return plugins


# Cache discovered plugins per-process (refresh on explicit re-scan).
_dashboard_plugins_cache: Optional[list] = None


def _get_dashboard_plugins(force_rescan: bool = False) -> list:
    global _dashboard_plugins_cache
    if _dashboard_plugins_cache is None or force_rescan:
        _dashboard_plugins_cache = _discover_dashboard_plugins()
    elif _dashboard_plugins_cache:
        if any(not Path(p["_dir"]).is_dir() for p in _dashboard_plugins_cache):
            _dashboard_plugins_cache = _discover_dashboard_plugins()
    return _dashboard_plugins_cache


@app.get("/api/dashboard/plugins")
async def get_dashboard_plugins():
    """Return discovered dashboard plugins (excludes user-hidden ones)."""
    plugins = _get_dashboard_plugins()
    # Read user's hidden plugins list from config.
    config = load_config()
    hidden: list = cfg_get(config, "dashboard", "hidden_plugins", default=[]) or []
    # Strip internal fields before sending to frontend and filter out hidden.
    return [
        {k: v for k, v in p.items() if not k.startswith("_")}
        for p in plugins
        if p["name"] not in hidden
    ]


@app.get("/api/dashboard/plugins/rescan")
async def rescan_dashboard_plugins():
    """Force re-scan of dashboard plugins."""
    plugins = _get_dashboard_plugins(force_rescan=True)
    return {"ok": True, "count": len(plugins)}


class _AgentPluginInstallBody(BaseModel):
    identifier: str
    force: bool = False
    enable: bool = True


def _strip_dashboard_manifest(p: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in p.items() if not k.startswith("_")}


def _merged_plugins_hub() -> Dict[str, Any]:
    """Agent discovery + dashboard manifests + optional provider picker metadata."""
    from hermes_cli.plugins_cmd import (
        _discover_all_plugins,
        _get_current_context_engine,
        _get_current_memory_provider,
        _discover_context_engines,
        _discover_memory_providers,
        _get_disabled_set,
        _get_enabled_set,
        _read_manifest as _read_plugin_manifest_at,
    )

    dashboard_list = _get_dashboard_plugins()
    dash_by_name = {str(p["name"]): p for p in dashboard_list}

    disabled_set = _get_disabled_set()
    enabled_set = _get_enabled_set()

    # Read user-hidden plugins from config for the user_hidden field.
    config = load_config()
    hidden_plugins: list = cfg_get(config, "dashboard", "hidden_plugins", default=[]) or []

    plugins_root_resolved = (get_hermes_home() / "plugins").resolve()
    rows: List[Dict[str, Any]] = []

    for name, version, description, source, dir_str in _discover_all_plugins():
        if name in disabled_set:
            runtime_status = "disabled"
        elif name in enabled_set:
            runtime_status = "enabled"
        else:
            runtime_status = "inactive"

        dir_path = Path(dir_str)
        dm = dash_by_name.get(name)
        has_dash_manifest = dm is not None or (dir_path / "dashboard" / "manifest.json").exists()

        under_user_tree = False
        try:
            dir_path.resolve().relative_to(plugins_root_resolved)
            under_user_tree = True
        except ValueError:
            pass

        can_remove_update = (
            source in {"user", "git"} and under_user_tree and Path(dir_str).is_dir()
        )

        # Check if this plugin provides tools that require auth
        auth_required = False
        auth_command = ""
        manifest_data = _read_plugin_manifest_at(dir_path)
        provides_tools = manifest_data.get("provides_tools") or []
        if provides_tools:
            try:
                from tools.registry import registry
                for tname in provides_tools:
                    entry = registry.get_entry(tname)
                    if entry and entry.check_fn and not entry.check_fn():
                        auth_required = True
                        auth_command = f"hermes auth {name}"
                        break
            except Exception:
                pass

        rows.append({
            "name": name,
            "version": version or "",
            "description": description or "",
            "source": source,
            "runtime_status": runtime_status,
            "has_dashboard_manifest": has_dash_manifest,
            "dashboard_manifest": _strip_dashboard_manifest(dm) if dm else None,
            "path": dir_str,
            "can_remove": can_remove_update,
            "can_update_git": can_remove_update and (Path(dir_str) / ".git").exists(),
            "auth_required": auth_required,
            "auth_command": auth_command,
            "user_hidden": name in hidden_plugins,
        })

    agent_names = {r["name"] for r in rows}
    orphan_dashboard = [
        _strip_dashboard_manifest(p)
        for p in dashboard_list
        if str(p["name"]) not in agent_names
    ]

    memory_providers: List[Dict[str, str]] = []
    try:
        for n, desc in _discover_memory_providers():
            memory_providers.append({"name": n, "description": desc})
    except Exception:
        memory_providers = []

    context_engines: List[Dict[str, str]] = []
    try:
        for n, desc in _discover_context_engines():
            context_engines.append({"name": n, "description": desc})
    except Exception:
        context_engines = []

    return {
        "plugins": rows,
        "orphan_dashboard_plugins": orphan_dashboard,
        "providers": {
            "memory_provider": _get_current_memory_provider() or "",
            "memory_options": memory_providers,
            "context_engine": _get_current_context_engine(),
            "context_options": context_engines,
        },
    }


@app.get("/api/dashboard/plugins/hub")
async def get_plugins_hub(request: Request):
    """Unified agent plugins + dashboard extension metadata (session protected)."""
    _require_token(request)
    try:
        return _merged_plugins_hub()
    except Exception as exc:
        _log.warning("plugins/hub failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to build plugins hub.") from exc


@app.post("/api/dashboard/agent-plugins/install")
async def post_agent_plugin_install(request: Request, body: _AgentPluginInstallBody):
    _require_token(request)
    from hermes_cli.plugins_cmd import dashboard_install_plugin

    result = dashboard_install_plugin(
        body.identifier.strip(),
        force=body.force,
        enable=body.enable,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=result.get("error") or "Install failed.",
        )
    _get_dashboard_plugins(force_rescan=True)
    # Strip internal paths from the response
    result.pop("after_install_path", None)
    return result


def _validate_plugin_name(name: str) -> str:
    """Reject path-traversal attempts in plugin name URL parameters."""
    if not name or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid plugin name.")
    return name


@app.post("/api/dashboard/agent-plugins/{name}/enable")
async def post_agent_plugin_enable(request: Request, name: str):
    _require_token(request)
    name = _validate_plugin_name(name)
    from hermes_cli.plugins_cmd import dashboard_set_agent_plugin_enabled

    result = dashboard_set_agent_plugin_enabled(name, enabled=True)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Enable failed.")
    return result


@app.post("/api/dashboard/agent-plugins/{name}/disable")
async def post_agent_plugin_disable(request: Request, name: str):
    _require_token(request)
    name = _validate_plugin_name(name)
    from hermes_cli.plugins_cmd import dashboard_set_agent_plugin_enabled

    result = dashboard_set_agent_plugin_enabled(name, enabled=False)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Disable failed.")
    return result


@app.post("/api/dashboard/agent-plugins/{name}/update")
async def post_agent_plugin_update(request: Request, name: str):
    _require_token(request)
    name = _validate_plugin_name(name)
    from hermes_cli.plugins_cmd import dashboard_update_user_plugin

    result = dashboard_update_user_plugin(name)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Update failed.")
    _get_dashboard_plugins(force_rescan=True)
    return result


@app.delete("/api/dashboard/agent-plugins/{name}")
async def delete_agent_plugin(request: Request, name: str):
    _require_token(request)
    name = _validate_plugin_name(name)
    from hermes_cli.plugins_cmd import dashboard_remove_user_plugin

    result = dashboard_remove_user_plugin(name)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Remove failed.")
    _get_dashboard_plugins(force_rescan=True)
    return result


class _PluginProvidersPutBody(BaseModel):
    memory_provider: Optional[str] = None
    context_engine: Optional[str] = None


@app.put("/api/dashboard/plugin-providers")
async def put_plugin_providers(request: Request, body: _PluginProvidersPutBody):
    """Persist memory provider / context engine selection (writes config.yaml)."""
    _require_token(request)
    from hermes_cli.plugins_cmd import (
        _save_context_engine,
        _save_memory_provider,
    )

    if body.memory_provider is not None:
        _save_memory_provider(body.memory_provider)
    if body.context_engine is not None:
        _save_context_engine(body.context_engine)
    return {"ok": True}


class _PluginVisibilityBody(BaseModel):
    hidden: bool


@app.post("/api/dashboard/plugins/{name}/visibility")
async def post_plugin_visibility(request: Request, name: str, body: _PluginVisibilityBody):
    """Toggle a plugin's sidebar visibility (persists to config.yaml dashboard.hidden_plugins)."""
    _require_token(request)
    name = _validate_plugin_name(name)

    config = load_config()
    if "dashboard" not in config or not isinstance(config.get("dashboard"), dict):
        config["dashboard"] = {}
    hidden_list: list = config["dashboard"].get("hidden_plugins") or []
    if not isinstance(hidden_list, list):
        hidden_list = []

    if body.hidden and name not in hidden_list:
        hidden_list.append(name)
    elif not body.hidden and name in hidden_list:
        hidden_list.remove(name)

    config["dashboard"]["hidden_plugins"] = hidden_list
    save_config(config)
    return {"ok": True, "name": name, "hidden": body.hidden}


@app.get("/dashboard-plugins/{plugin_name}/{file_path:path}")
async def serve_plugin_asset(plugin_name: str, file_path: str):
    """Serve static assets from a dashboard plugin directory.

    Only serves files from the plugin's ``dashboard/`` subdirectory.
    Path traversal is blocked by checking ``resolve().is_relative_to()``.
    """
    plugins = _get_dashboard_plugins()
    plugin = next((p for p in plugins if p["name"] == plugin_name), None)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    base = Path(plugin["_dir"])
    target = (base / file_path).resolve()

    if not target.is_relative_to(base.resolve()):
        raise HTTPException(status_code=403, detail="Path traversal blocked")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Guess content type
    suffix = target.suffix.lower()
    content_types = {
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".html": "text/html",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".woff2": "font/woff2",
        ".woff": "font/woff",
    }
    media_type = content_types.get(suffix, "application/octet-stream")
    return FileResponse(
        target,
        media_type=media_type,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


# ---------------------------------------------------------------------------
# Workspace file browser — list / read / upload / download / delete / rename
# / mkdir under the cwd that `sopify dashboard` was launched from. That cwd
# is also what `sbx_launcher` bind-mounts as /workspace inside the sandbox,
# so the host paths exposed here are exactly what the in-sandbox agent sees
# (and writes back to) as /workspace/...
#
# Path-traversal guard: every request is .resolve()d and re-checked against
# _FILES_ROOT. `.resolve()` follows symlinks, so a symlink in the workspace
# that points outside it (e.g. into ~/.ssh) is rejected — important since
# this UI is intended for non-technical users.
# ---------------------------------------------------------------------------

# Captured at import time: cwd at the moment `sopify dashboard` starts the
# uvicorn process. Stable for the lifetime of the dashboard.
_FILES_ROOT = Path.cwd().resolve()

# Two roots are exposed to the Files page:
#   - "workspace": the cwd dashboard launched from (bind-mounted into sbx).
#                  Same content the agent's shell sees as its workspace.
#   - "hermes":    HERMES_HOME (default ~/.hermes) which inside the sbx is
#                  /home/sopify/.hermes/ — holds vibe-projects/, state.db,
#                  logs/, dashboard-themes/, plugins/, etc. Container-local
#                  (vibe projects live here, NOT on the host filesystem),
#                  so this is the only way to inspect them via the dashboard.
# Frontend `?root=workspace|hermes`; defaults to workspace for back-compat
# with older clients.
_FILES_ROOTS: dict[str, Path] = {
    "workspace": _FILES_ROOT,
    "hermes": get_hermes_home().resolve(),
}

# Soft cap on inline text reads. Larger files surface a "too big — download
# instead" hint to the client so we don't blow up the browser tab.
_FILES_READ_INLINE_CAP = 5 * 1024 * 1024


def _resolve_root(root_name: str) -> tuple[str, Path]:
    """Return (canonical_root_name, root_path). Reject unknown names so a
    typo never silently degrades the path guard."""
    canonical = (root_name or "workspace").strip().lower()
    if canonical not in _FILES_ROOTS:
        raise HTTPException(status_code=400, detail=f"unknown root: {root_name!r}")
    return canonical, _FILES_ROOTS[canonical]


def _files_safe_path(rel: str, root_name: str = "workspace") -> Path:
    """Resolve `rel` under the named root, rejecting traversal + out-of-root
    symlinks. Caller passes ``root_name`` from the request's ``root`` query
    param. .resolve() follows symlinks, so a link pointing outside the root
    (e.g. into ~/.ssh) is rejected too."""
    _, root = _resolve_root(root_name)
    rel = (rel or "").lstrip("/").lstrip("\\")
    if rel == "":
        return root
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail=f"path outside {root_name} root")
    return candidate


@app.get("/api/files")
async def files_list(path: str = "", root: str = "workspace"):
    """List entries under `path` (relative to the named root)."""
    canonical_root, root_path = _resolve_root(root)
    target = _files_safe_path(path, canonical_root)
    if not target.exists():
        raise HTTPException(status_code=404, detail="path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="path is not a directory")

    entries = []
    try:
        children = sorted(
            target.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    for child in children:
        try:
            st = child.stat()
            is_dir = child.is_dir()
        except OSError:
            continue
        entries.append({
            "name": child.name,
            "path": str(child.relative_to(root_path)),
            "is_dir": is_dir,
            "size": st.st_size if not is_dir else None,
            "mtime": st.st_mtime,
        })

    rel_path = "" if target == root_path else str(target.relative_to(root_path))
    return {
        "root": str(root_path),
        "root_name": canonical_root,
        "path": rel_path,
        "entries": entries,
    }


@app.get("/api/files/read")
async def files_read(path: str, root: str = "workspace"):
    """Return text content of `path`, or a hint to download (binary / too big)."""
    target = _files_safe_path(path, root)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    size = target.stat().st_size
    if size > _FILES_READ_INLINE_CAP:
        return {"too_large": True, "size": size, "cap": _FILES_READ_INLINE_CAP}
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if b"\x00" in raw:
        return {"binary": True, "size": size}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"binary": True, "size": size}
    return {"binary": False, "size": size, "content": text}


@app.get("/api/files/download")
async def files_download(path: str, root: str = "workspace"):
    """Stream a file at `path` back as an attachment."""
    target = _files_safe_path(path, root)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    def iter_file(p: Path, chunk: int = 64 * 1024):
        with p.open("rb") as fh:
            while True:
                buf = fh.read(chunk)
                if not buf:
                    break
                yield buf

    encoded_name = urllib.parse.quote(target.name)
    return StreamingResponse(
        iter_file(target),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
            "Content-Length": str(target.stat().st_size),
        },
    )


# Click-to-select inspector injected into previewed HTML when ``?_inspect=1``.
# Runs in the sandboxed (opaque-origin) iframe; it stays dormant until the
# dashboard host posts ``set-inspect``, then reports the clicked element back
# via postMessage. postMessage works across the opaque origin, so no
# same-origin grant is needed. See web/src/components/canvas/PreviewFrame.tsx.
_CANVAS_INSPECTOR_JS = """
(function(){
  if (window.__sopifyInspector) return;
  window.__sopifyInspector = true;
  var enabled = false, last = null, OUTLINE = '2px solid #1D63ED';
  function cssPath(el){
    if (!(el instanceof Element)) return '';
    var path = [];
    while (el && el.nodeType === 1 && el !== document.body && path.length < 6){
      var sel = el.nodeName.toLowerCase();
      if (el.id){ path.unshift(sel + '#' + el.id); break; }
      var cls = (el.className && typeof el.className === 'string')
        ? el.className.trim().split(/\\s+/).slice(0,2).filter(Boolean).join('.') : '';
      if (cls) sel += '.' + cls;
      var parent = el.parentNode;
      if (parent && parent.children){
        var sibs = Array.prototype.filter.call(parent.children, function(c){ return c.nodeName === el.nodeName; });
        if (sibs.length > 1) sel += ':nth-of-type(' + (sibs.indexOf(el)+1) + ')';
      }
      path.unshift(sel);
      el = el.parentNode;
    }
    return path.join(' > ');
  }
  function clear(){ if (last){ last.style.outline = last.__sopifyO || ''; last = null; } }
  function send(el){
    var html = el.outerHTML || '';
    if (html.length > 1500) html = html.slice(0,1500) + '\\u2026';
    var text = (el.textContent || '').trim().replace(/\\s+/g,' ');
    if (text.length > 200) text = text.slice(0,200) + '\\u2026';
    window.parent.postMessage({ source:'sopify-canvas', type:'select', payload:{
      selector: cssPath(el), tag: el.nodeName.toLowerCase(), id: el.id || '',
      classes: (typeof el.className === 'string' ? el.className : ''),
      text: text, html: html
    }}, '*');
  }
  document.addEventListener('mouseover', function(e){
    if (!enabled) return;
    clear(); last = e.target; last.__sopifyO = last.style.outline; last.style.outline = OUTLINE;
  }, true);
  document.addEventListener('mouseout', function(){ if (enabled) clear(); }, true);
  document.addEventListener('click', function(e){
    if (!enabled) return;
    e.preventDefault(); e.stopPropagation(); send(e.target);
  }, true);
  window.addEventListener('message', function(e){
    var d = e.data || {};
    if (d.source === 'sopify-canvas-host' && d.type === 'set-inspect'){
      enabled = !!d.enabled;
      document.documentElement.style.cursor = enabled ? 'crosshair' : '';
      if (!enabled) clear();
    }
  });
  window.parent.postMessage({ source:'sopify-canvas', type:'ready' }, '*');
})();
"""


@app.get("/preview/{path:path}")
async def files_preview(path: str, request: Request):
    """Serve a workspace file inline for the Canvas iframe preview.

    Lives OUTSIDE ``/api/`` on purpose: the auth middleware only gates
    ``/api/`` paths, and HTML previewed in an iframe pulls in relative
    subresources (CSS/JS/images) that the browser fetches *without* the
    ``?_token=`` query param — those nested requests would be rejected by a
    token check they can't satisfy. Instead we authenticate the top-level
    navigation via ``?_token=`` (or the dashboard's session header) and set a
    ``/preview``-scoped cookie so the nested loads carry auth automatically.

    Only files under the workspace root are reachable (``_files_safe_path``
    rejects traversal and out-of-root symlinks), and the host-header
    middleware still restricts the bind to the loopback host by default.
    """
    token_ok = (
        _has_valid_session_token(request)
        or _has_valid_session_token_query(request)
        or hmac.compare_digest(
            request.cookies.get("hermes_preview", "").encode(),
            _SESSION_TOKEN.encode(),
        )
    )
    if not token_ok:
        raise HTTPException(status_code=401, detail="Unauthorized")

    target = _files_safe_path(path)
    if target.is_dir():
        index = target / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="no index.html in directory")
        target = index
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    media_type, _ = mimetypes.guess_type(str(target))
    is_html = (media_type or "").startswith("text/html") or target.suffix.lower() in (
        ".html",
        ".htm",
    )

    if is_html and request.query_params.get("_inspect") == "1":
        # Inject the click-to-select inspector just before </body> (falling
        # back to appending) so the host can drive component selection.
        try:
            html = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            html = None
        if html is not None:
            tag = f"<script>{_CANVAS_INSPECTOR_JS}</script>"
            lowered = html.lower()
            idx = lowered.rfind("</body>")
            html = html[:idx] + tag + html[idx:] if idx >= 0 else html + tag
            response: Response = HTMLResponse(
                html,
                headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
            )
        else:
            response = FileResponse(
                target,
                media_type=media_type or "application/octet-stream",
                headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
            )
    else:
        response = FileResponse(
            target,
            media_type=media_type or "application/octet-stream",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    # Propagate auth to nested subresource loads, which can't carry ?_token=.
    if request.query_params.get("_token"):
        response.set_cookie(
            "hermes_preview",
            _SESSION_TOKEN,
            path="/preview",
            httponly=True,
            samesite="strict",
        )
    return response


# ---------------------------------------------------------------------------
# Preview dev-server manager
#
# Lets the Panel start the project's dev server (e.g. `npm run dev`) so the
# user doesn't have to open a terminal — the Canvas Live mode then points an
# iframe at the printed localhost URL. One server at a time, host-only.
#
# This spawns an arbitrary command, so every endpoint requires the session
# token and the cwd is constrained to the workspace root (same guard as the
# file endpoints). The dashboard is loopback-bound by default; the trust
# posture matches the existing gateway-restart / hermes-update spawns.
# ---------------------------------------------------------------------------

# Preview servers are tracked per chat session so switching sessions doesn't
# kill an already-running dev server.  Each session has its own subprocess
# and its own log file; the only cross-session interaction is port-collision
# resolution (see `/status` below): when a newer session's server prints a
# localhost URL on a port that an older session was also tracked on, the OS
# only ever bound the most-recent process — the older entry is defunct and
# gets stopped so the newer one keeps the port.
_PREVIEW_SESSIONS: Dict[str, Dict[str, Any]] = {}

# session_id is interpolated into a filename, so guard it strictly.
_PREVIEW_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

# Common dev-server commands we accept. A free-form command is rejected to
# avoid turning this into a generic RCE surface beyond starting dev servers.
_PREVIEW_ALLOWED = {
    "npm run dev",
    "npm start",
    "npm run start",
    "yarn dev",
    "yarn start",
    "pnpm dev",
    "pnpm start",
    "bun dev",
}

# Default ports for common frontend dev servers (CRA 3000, Vite 5173/4173,
# webpack/other 8080). `npm run dev` often boots an API server too, so prefer
# a frontend URL over whichever process printed first.
_PREVIEW_FRONTEND_PORTS = ("3000", "5173", "4173", "3001", "8080")


def _preview_validate_session(session_id: Optional[str]) -> str:
    if not isinstance(session_id, str) or not _PREVIEW_SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="invalid or missing session_id")
    return session_id


def _preview_log_path(session_id: str) -> Path:
    return _ACTION_LOG_DIR / f"preview-server-{session_id}.log"


def _preview_running_for(session_id: str) -> bool:
    info = _PREVIEW_SESSIONS.get(session_id)
    return info is not None and info["proc"].poll() is None


def _preview_detect_url_at(log_path: Path) -> Optional[str]:
    """Find a dev server's localhost URL in its log, preferring frontend ports."""
    if not log_path.exists():
        return None
    tail = _tail_lines(log_path, 400)
    pattern = re.compile(r"https?://(?:localhost|127\.0\.0\.1):(\d+)")
    found: list[tuple[str, str]] = []
    for line in tail:
        for m in pattern.finditer(line):
            found.append((m.group(0), m.group(1)))
    if not found:
        return None
    for url, port in found:
        if port in _PREVIEW_FRONTEND_PORTS:
            return url
    return found[-1][0]


def _port_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    m = re.search(r":(\d+)", url)
    return m.group(1) if m else None


def _preview_stop_session(session_id: str) -> bool:
    """Terminate one session's dev-server process group. Returns True if a
    running entry was found and signalled."""
    info = _PREVIEW_SESSIONS.pop(session_id, None)
    if info is None:
        return False
    proc = info["proc"]
    if proc.poll() is not None:
        return False
    try:
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if sys.platform != "win32":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    return True


def _preview_prune_dead() -> None:
    """Drop registry entries whose process already exited."""
    for sid in [s for s, info in _PREVIEW_SESSIONS.items() if info["proc"].poll() is not None]:
        _PREVIEW_SESSIONS.pop(sid, None)


@app.post("/api/preview-server/start")
async def preview_server_start(request: Request):
    """Start the project's dev server (default `npm run dev`) under `cwd` for
    the given chat session.  Other sessions' servers are left running."""
    _require_token(request)

    try:
        body = await request.json()
    except Exception:
        body = {}
    session_id = _preview_validate_session(body.get("session_id"))
    command = str(body.get("command") or "npm run dev").strip()
    cwd_rel = str(body.get("cwd") or "")

    if command not in _PREVIEW_ALLOWED:
        raise HTTPException(
            status_code=400,
            detail=f"command not allowed; choose one of: {sorted(_PREVIEW_ALLOWED)}",
        )

    cwd = _files_safe_path(cwd_rel)
    if not cwd.is_dir():
        raise HTTPException(status_code=400, detail="cwd is not a directory")
    if not (cwd / "package.json").is_file():
        raise HTTPException(status_code=400, detail="no package.json in cwd")

    # Replace any running server for THIS session — leave other sessions alone.
    _preview_stop_session(session_id)
    _preview_prune_dead()

    _ACTION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _preview_log_path(session_id)
    log_file = open(log_path, "wb", buffering=0)
    log_file.write(
        f"=== preview `{command}` in {cwd} for session {session_id} started "
        f"{time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode()
    )

    popen_kwargs: Dict[str, Any] = {
        "cwd": str(cwd),
        "stdin": subprocess.DEVNULL,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
        # BROWSER=none stops CRA from opening a tab on the server host;
        # CI=true keeps it non-interactive without failing on warnings.
        "env": {**os.environ, "BROWSER": "none", "FORCE_COLOR": "0"},
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(shlex.split(command), **popen_kwargs)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"command not found: {exc}")
    except Exception as exc:
        _log.exception("Failed to start preview server")
        raise HTTPException(status_code=500, detail=f"failed to start: {exc}")

    _PREVIEW_SESSIONS[session_id] = {
        "proc": proc,
        "command": command,
        "cwd": str(cwd.relative_to(_FILES_ROOT)) if cwd != _FILES_ROOT else "",
        "started_at": time.time(),
        "pid": proc.pid,
        "log_path": log_path,
    }
    return {"ok": True, "pid": proc.pid, "command": command, "session_id": session_id}


@app.get("/api/preview-server/status")
async def preview_server_status(request: Request, session_id: str, lines: int = 200):
    """Report the named session's dev server, plus URL and log tail.

    Also resolves port collisions: if this session's detected port matches
    another session's tracked port, the older entry is killed (newer wins).
    """
    _require_token(request)
    _preview_validate_session(session_id)
    _preview_prune_dead()

    info = _PREVIEW_SESSIONS.get(session_id)
    running = info is not None and info["proc"].poll() is None
    log_path = _preview_log_path(session_id)
    tail = _tail_lines(log_path, min(max(lines, 1), 2000)) if log_path.exists() else []
    detected_url = _preview_detect_url_at(log_path) if running else None

    # Collision resolution — newer (this) session wins the port.
    this_port = _port_from_url(detected_url) if running else None
    if this_port:
        for other_sid in list(_PREVIEW_SESSIONS.keys()):
            if other_sid == session_id:
                continue
            other = _PREVIEW_SESSIONS.get(other_sid)
            if other is None or other["proc"].poll() is not None:
                continue
            other_port = _port_from_url(_preview_detect_url_at(other["log_path"]))
            if other_port == this_port:
                _preview_stop_session(other_sid)

    return {
        "running": running,
        "pid": info["pid"] if running and info else None,
        "command": info["command"] if info else None,
        "cwd": info["cwd"] if info else None,
        "url": detected_url,
        "logs": tail,
    }


@app.post("/api/preview-server/stop")
async def preview_server_stop_endpoint(request: Request):
    """Stop one session's dev server."""
    _require_token(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    session_id = _preview_validate_session(body.get("session_id"))
    _preview_stop_session(session_id)
    return {"ok": True}


@app.post("/api/files/upload")
async def files_upload(request: Request):
    """Stream uploaded files into the directory named by the `path` form field.
    `root` form field selects the root (defaults to workspace)."""
    _require_token(request)
    form = await request.form()
    root_name = str(form.get("root", "workspace") or "workspace")
    canonical_root, root_path = _resolve_root(root_name)
    target_dir_rel = str(form.get("path", "") or "")
    target_dir = _files_safe_path(target_dir_rel, canonical_root)
    if not target_dir.exists():
        raise HTTPException(status_code=404, detail="target directory not found")
    if not target_dir.is_dir():
        raise HTTPException(status_code=400, detail="target is not a directory")

    saved = []
    for key, value in form.multi_items():
        if key in ("path", "root"):
            continue
        # UploadFile values carry .filename + .read(); skip plain text fields.
        filename = getattr(value, "filename", None)
        if not filename:
            continue
        # Strip directory components — only allow uploads directly into target_dir.
        safe_name = Path(filename).name
        if not safe_name or safe_name in (".", ".."):
            continue
        dest = target_dir / safe_name
        # Defense-in-depth re-check against symlink shenanigans.
        dest_check = (target_dir.resolve() / safe_name)
        try:
            dest_check.relative_to(root_path)
        except ValueError:
            raise HTTPException(status_code=403, detail=f"upload target outside {canonical_root}")
        try:
            with dest.open("wb") as fh:
                while True:
                    chunk = await value.read(1024 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
        finally:
            await value.close()
        saved.append({
            "name": safe_name,
            "path": str(dest.relative_to(root_path)),
            "size": dest.stat().st_size,
        })

    if not saved:
        raise HTTPException(status_code=400, detail="no files in upload")
    _log.info("files upload: root=%s dir=%s count=%d", canonical_root, target_dir_rel, len(saved))
    return {"ok": True, "root_name": canonical_root, "saved": saved}


class FileRenameBody(BaseModel):
    src: str
    dst: str
    root: str = "workspace"


@app.post("/api/files/rename")
async def files_rename(body: FileRenameBody, request: Request):
    """Move/rename a file or directory within the named root."""
    _require_token(request)
    canonical_root, root_path = _resolve_root(body.root)
    src = _files_safe_path(body.src, canonical_root)
    if src == root_path:
        raise HTTPException(status_code=400, detail="cannot rename root")
    if not src.exists():
        raise HTTPException(status_code=404, detail="source not found")
    # For dst, we want to allow the parent to exist but the dst itself to be new.
    dst_rel = (body.dst or "").lstrip("/").lstrip("\\")
    if not dst_rel:
        raise HTTPException(status_code=400, detail="dst is empty")
    dst = (root_path / dst_rel).resolve()
    try:
        dst.relative_to(root_path)
    except ValueError:
        raise HTTPException(status_code=403, detail=f"dst outside {canonical_root}")
    if dst.exists():
        raise HTTPException(status_code=409, detail="destination already exists")
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.rename(dst)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    _log.info("files rename: root=%s %s -> %s", canonical_root, body.src, body.dst)
    return {"ok": True}


class FileMkdirBody(BaseModel):
    path: str
    root: str = "workspace"


@app.post("/api/files/mkdir")
async def files_mkdir(body: FileMkdirBody, request: Request):
    """Create a (possibly nested) directory within the named root."""
    _require_token(request)
    canonical_root, root_path = _resolve_root(body.root)
    rel = (body.path or "").lstrip("/").lstrip("\\")
    if not rel:
        raise HTTPException(status_code=400, detail="path is empty")
    target = (root_path / rel).resolve()
    try:
        target.relative_to(root_path)
    except ValueError:
        raise HTTPException(status_code=403, detail=f"path outside {canonical_root}")
    if target == root_path:
        raise HTTPException(status_code=400, detail="cannot mkdir on root")
    if target.exists():
        raise HTTPException(status_code=409, detail="path already exists")
    try:
        target.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    _log.info("files mkdir: root=%s %s", canonical_root, body.path)
    return {"ok": True, "path": str(target.relative_to(root_path))}


@app.delete("/api/files")
async def files_delete(path: str, request: Request, root: str = "workspace"):
    """Delete a file or (recursively) a directory within the named root."""
    _require_token(request)
    canonical_root, root_path = _resolve_root(root)
    target = _files_safe_path(path, canonical_root)
    if target == root_path:
        raise HTTPException(status_code=400, detail="cannot delete root")
    if not target.exists():
        raise HTTPException(status_code=404, detail="path not found")
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    _log.info("files delete: %s", path)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Vibe Code — AI-DLC project scaffolding flow (see SPECIFICATION_ADD_ON_FLOW.md).
#
# The frontend at /vibe-code lets a user pick an example mode (dashboard,
# form-registration, landing-page, web-app) and a set of add-ons, then names
# the project. On submit we create a folder under <hermes_home>/vibe-projects/
# and write a project.json marker that downstream phases (brainstorm →
# requirements → planning → dev) will read/append to.
# ---------------------------------------------------------------------------


_VIBE_EXAMPLES_DIR: Path = PROJECT_ROOT / "example"
_VIBE_PROJECTS_ROOT: Path = get_hermes_home() / "vibe-projects"
_VIBE_PROMPTS_DIR: Path = PROJECT_ROOT / "prompts" / "vibe"

# Display labels for the four built-in example modes. Folder name → user-
# facing label (English; UI can localize separately).
_VIBE_EXAMPLE_LABELS: dict[str, str] = {
    "dashboard": "Dashboard",
    "form-registration": "Form / Registration",
    "landing-page": "Landing Page",
    "web-app": "Web App",
}

# Available add-on keys. Selected ones are stored on the project; later
# phases (brainstorm / dev) splice the matching prompt-template snippet
# into the agent's system prompt.
_VIBE_ADDON_KEYS: set[str] = {
    "auth-jwt",
    "database-supabase",
    "file-upload",
    "schedule-job",
    "qr-scan",
    "dark-mode",
}

# Slug rule for project names: lowercase letters/digits + dash/underscore,
# 1-64 chars, must start with a letter or digit. Matches the existing
# `profiles` naming convention.
_VIBE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class VibeQuestions(BaseModel):
    """User answers from the CreateForm scoping questions (Q1-Q4).

    The frontend sends already-human-readable labels for inputs/outputs/
    exclusions (e.g. "Type it manually" rather than "manual") because they
    land verbatim in brief.md — keeps the agent prompt human-readable and
    decouples backend from label wording.
    """
    purpose: str
    access_mode: str  # "solo" | "team-shared" | "team-isolated"
    inputs: List[str] = []
    outputs: List[str] = []
    exclusions: List[str] = []


_VIBE_ACCESS_LABELS = {
    "solo": "Single user — no login, no per-user isolation.",
    "team-shared": "Team — everyone sees the same data, gated behind a login.",
    "team-isolated": "Team — each person sees only their own data (per-user isolation).",
}


class VibeProjectCreate(BaseModel):
    name: str
    mode: str
    add_ons: List[str] = []
    questions: Optional[VibeQuestions] = None


@app.get("/api/vibe/examples")
async def vibe_list_examples(request: Request):
    """List built-in example modes with display labels and image URLs."""
    _require_token(request)
    out = []
    for slug, label in _VIBE_EXAMPLE_LABELS.items():
        d = _VIBE_EXAMPLES_DIR / slug
        if not d.is_dir():
            continue
        has_image = (d / "image.png").is_file()
        out.append({
            "name": slug,
            "label": label,
            "has_image": has_image,
            "image_url": f"/api/vibe/examples/{slug}/image.png" if has_image else None,
        })
    return {"examples": out}


@app.get("/api/vibe/examples/{name}/image.png")
async def vibe_example_image(name: str):
    """Serve image.png from sopify-harness/example/<name>/image.png.

    The handler itself doesn't call `_require_token` — the global
    auth_middleware already gates this under /api/, and accepts a
    `?_token=<token>` query string for <img src=...> requests that
    can't carry the X-Hermes-Session-Token header.
    """
    if name not in _VIBE_EXAMPLE_LABELS:
        raise HTTPException(status_code=404, detail="unknown example")
    img = _VIBE_EXAMPLES_DIR / name / "image.png"
    if not img.is_file():
        raise HTTPException(status_code=404, detail="image missing")
    return FileResponse(img, media_type="image/png")


@app.get("/preview/vibe/{name}")
@app.get("/preview/vibe/{name}/")
@app.get("/preview/vibe/{name}/{path:path}")
async def vibe_preview(name: str, request: Request, path: str = ""):
    """Serve a file from a vibe project for the Building-phase iframe.

    Lives under ``/preview/`` so the existing ``hermes_preview`` cookie auth
    (set by the canvas preview flow at ``/preview/{path}``) covers nested
    subresource loads — themes ship ``app/`` and ``assets/`` folders that
    relative-link from the entry HTML and can't carry a ``?_token=`` of
    their own. Top-level navigations still authenticate via header /
    query string before the cookie is set.

    When ``path`` is empty or names a directory we resolve a sensible
    entry file: ``index.html`` if present, otherwise the first ``.html``
    found in that directory (themes ship a single named entry like
    ``Production Overview.html``).
    """
    token_ok = (
        _has_valid_session_token(request)
        or _has_valid_session_token_query(request)
        or hmac.compare_digest(
            request.cookies.get("hermes_preview", "").encode(),
            _SESSION_TOKEN.encode(),
        )
    )
    if not token_ok:
        raise HTTPException(status_code=401, detail="Unauthorized")

    project_dir = _vibe_project_dir(name)
    rel = (path or "").lstrip("/").lstrip("\\")
    candidate = (project_dir / rel).resolve() if rel else project_dir
    try:
        candidate.relative_to(project_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="path outside project")

    if not candidate.exists():
        raise HTTPException(status_code=404, detail="file not found")

    if candidate.is_dir():
        entry = candidate / "index.html"
        if not entry.is_file():
            html_files = sorted(p for p in candidate.iterdir() if p.is_file() and p.suffix.lower() == ".html")
            if not html_files:
                raise HTTPException(status_code=404, detail="no html entry in directory")
            entry = html_files[0]
        candidate = entry

    media_type, _ = mimetypes.guess_type(str(candidate))
    response: Response = FileResponse(
        candidate,
        media_type=media_type or "application/octet-stream",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )
    if request.query_params.get("_token"):
        response.set_cookie(
            "hermes_preview",
            _SESSION_TOKEN,
            path="/preview",
            httponly=True,
            samesite="strict",
        )
    return response


@app.post("/api/vibe/projects")
async def vibe_create_project(body: VibeProjectCreate, request: Request):
    """Create a new Vibe Code project folder + project.json marker.

    Refuses to clobber an existing folder (409) so a user retrying with the
    same name gets a clear failure rather than silently merging.
    """
    from datetime import datetime, timezone

    _require_token(request)
    name = (body.name or "").strip().lower()
    if not _VIBE_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="invalid name: use lowercase letters, digits, _ or - (1-64 chars, start with letter/digit)",
        )
    if body.mode not in _VIBE_EXAMPLE_LABELS:
        raise HTTPException(status_code=400, detail=f"unknown mode: {body.mode}")
    unknown_addons = [a for a in body.add_ons if a not in _VIBE_ADDON_KEYS]
    if unknown_addons:
        raise HTTPException(
            status_code=400,
            detail=f"unknown add-ons: {', '.join(unknown_addons)}",
        )

    _VIBE_PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
    project_dir = _VIBE_PROJECTS_ROOT / name
    if project_dir.exists():
        raise HTTPException(status_code=409, detail="project already exists")

    try:
        project_dir.mkdir(parents=False, exist_ok=False)
        # Seed the project with the chosen theme's starter files so the agent
        # has something to work from on the very first turn. image.png is the
        # picker thumbnail — skip it.
        example_src = _VIBE_EXAMPLES_DIR / body.mode
        if example_src.is_dir():
            for entry in example_src.iterdir():
                if entry.name == "image.png":
                    continue
                dest = project_dir / entry.name
                if entry.is_dir():
                    shutil.copytree(entry, dest)
                else:
                    shutil.copy2(entry, dest)
        marker = {
            "name": name,
            "mode": body.mode,
            "add_ons": sorted(set(body.add_ons)),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "phase": "brainstorm",
        }
        (project_dir / "project.json").write_text(
            json.dumps(marker, indent=2) + "\n", encoding="utf-8",
        )
        if body.questions:
            (project_dir / "brief.md").write_text(
                _vibe_render_brief(body.questions), encoding="utf-8",
            )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    _log.info("vibe project created: %s (mode=%s, add_ons=%s, brief=%s)",
              name, body.mode, marker["add_ons"], bool(body.questions))
    return {"ok": True, "name": name, "path": str(project_dir), "project": marker}


def _vibe_render_brief(q: VibeQuestions) -> str:
    """Render the user's CreateForm answers as a markdown brief the
    brainstorm agent reads as initial context (see prompts/vibe/phases/
    brainstorm.md). Lives alongside REQUIREMENTS.md but does NOT replace
    it — REQUIREMENTS.md stays the agent-curated source of truth, brief.md
    is the user's raw answers preserved verbatim."""
    access_line = _VIBE_ACCESS_LABELS.get(
        q.access_mode, f"({q.access_mode})",
    )

    def _bullet_list(items: List[str], empty_note: str) -> str:
        if not items:
            return f"_{empty_note}_"
        return "\n".join(f"- {it}" for it in items)

    return (
        "# Project brief\n"
        "\n"
        "> Generated from the user's answers in the Create Project form.\n"
        "> The brainstorm agent reads this as initial context — refine via\n"
        "> chat, then write the final scope into REQUIREMENTS.md.\n"
        "\n"
        "## Purpose\n"
        "\n"
        f"{q.purpose.strip()}\n"
        "\n"
        "## Users & access\n"
        "\n"
        f"{access_line}\n"
        "\n"
        "## How data gets in\n"
        "\n"
        f"{_bullet_list(q.inputs, 'No input modalities selected.')}\n"
        "\n"
        "## How data comes back out\n"
        "\n"
        f"{_bullet_list(q.outputs, 'No output modalities selected.')}\n"
        "\n"
        "## Explicit non-goals (NOT v1)\n"
        "\n"
        f"{_bullet_list(q.exclusions, 'No explicit non-goals declared — derive scope from the chat.')}\n"
    )


# Ordered phase machine, per-phase model defaults, and the available-model
# catalog live in ``hermes_cli.vibe_models`` so the WebSocket gateway can
# import the same constants without dragging in this FastAPI module. The
# ``_VIBE_*`` aliases below are kept for the rest of this file plus the
# PR-002 test suite, which references the underscore-prefixed names.
from hermes_cli.vibe_models import (
    VIBE_PHASES as _VIBE_PHASES,
    VIBE_PHASE_MODEL_DEFAULTS as _VIBE_PHASE_MODEL_DEFAULTS,
    VIBE_AVAILABLE_MODELS as _VIBE_AVAILABLE_MODELS,
    resolve_vibe_phase_model,
)

# Skills auto-injected into the system prompt when the project is in the
# matching phase. The SKILL.md body is inlined so the agent has the
# methodology in scope without an extra `skill_view` round-trip.
_VIBE_PHASE_SKILLS: dict[str, tuple[str, ...]] = {
    # Design phase: generic taste/aesthetic skill from Anthropic +
    # GS Battery brand/component conventions.
    "design":      ("frontend-design", "sopify-sdlc-design"),
    # Backend phase covers both schema design and API + wiring. Load
    # database conventions FIRST so the agent leads with schema, then
    # backend API rules so the API shape derives from the locked schema.
    "backend":     ("sopify-sdlc-database", "sopify-sdlc-backend"),
    # Improvement phase: free-form iteration. Keep all three SDLC
    # skills loaded so the agent can't drift outside GS Battery's
    # frontend OR backend conventions while making tweaks. The user's
    # explicit non-goals (Q4 in brief.md) are the scope anchor.
    "improvement": ("sopify-sdlc-design", "sopify-sdlc-database", "sopify-sdlc-backend"),
    "security":    ("red-teaming/claude-code-security-review",),
}

def _vibe_project_dir(name: str) -> Path:
    """Resolve a project dir, rejecting traversal / unknown names."""
    if not _VIBE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="invalid name")
    d = (_VIBE_PROJECTS_ROOT / name).resolve()
    try:
        d.relative_to(_VIBE_PROJECTS_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="path outside vibe-projects root")
    if not d.is_dir():
        raise HTTPException(status_code=404, detail="project not found")
    return d


def _vibe_read_marker(project_dir: Path) -> dict:
    f = project_dir / "project.json"
    if not f.is_file():
        raise HTTPException(status_code=500, detail="project.json missing")
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"bad project.json: {exc}")


def _vibe_write_marker(project_dir: Path, marker: dict) -> None:
    from datetime import datetime, timezone
    marker["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (project_dir / "project.json").write_text(
        json.dumps(marker, indent=2) + "\n", encoding="utf-8",
    )


@app.get("/api/vibe/projects")
async def vibe_list_projects(request: Request):
    """List all vibe projects on disk (newest first)."""
    _require_token(request)
    _VIBE_PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
    out = []
    for child in _VIBE_PROJECTS_ROOT.iterdir():
        if not child.is_dir():
            continue
        marker_file = child / "project.json"
        if not marker_file.is_file():
            continue
        try:
            data = json.loads(marker_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        out.append({
            "name": data.get("name", child.name),
            "mode": data.get("mode", "unknown"),
            "add_ons": data.get("add_ons", []),
            "phase": data.get("phase", "brainstorm"),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        })
    # Newest first by created_at fallback name.
    out.sort(key=lambda p: (p.get("created_at") or "", p["name"]), reverse=True)
    return {"projects": out}


def _read_if_exists(path: Path) -> Optional[str]:
    return path.read_text(encoding="utf-8") if path.is_file() else None


@app.get("/api/vibe/projects/{name}")
async def vibe_get_project(name: str, request: Request):
    """Return project marker + content of artifact files if present."""
    _require_token(request)
    d = _vibe_project_dir(name)
    marker = _vibe_read_marker(d)
    return {
        "project": marker,
        "path": str(d),
        "requirements_md": _read_if_exists(d / "REQUIREMENTS.md"),
        "design_md": _read_if_exists(d / "DESIGN.md"),
        "database_md": _read_if_exists(d / "DATABASE.md"),
        "api_md": _read_if_exists(d / "API.md"),
        # Retained so the legacy 3-pane UI keeps compiling; new 6-phase
        # projects do not write PLANNING.md, so this is null for them.
        "planning_md": _read_if_exists(d / "PLANNING.md"),
        "security_review_md": _read_if_exists(d / "SECURITY_REVIEW.md"),
    }


def _vibe_compose_system_prompt(marker: dict) -> str:
    """Concatenate the system prompt for a vibe project's current phase.

    Order: project preamble → base → mode → add-ons → phase skill(s) → phase.
    The phase prompt is last so its immediate-action guidance is freshest
    in the agent's attention. Missing files are silently skipped so a
    minimal install still works.
    """
    parts: list[str] = []
    project_name = marker.get("name", "")
    mode = marker.get("mode", "")
    add_ons = marker.get("add_ons", []) or []
    phase = marker.get("phase", "brainstorm")

    if project_name:
        project_dir = _VIBE_PROJECTS_ROOT / project_name
        parts.append(
            f"# Project: {project_name}\n\n"
            f"**Project folder:** `{project_dir}`\n\n"
            f"All files for this project — including `REQUIREMENTS.md`, "
            f"`DESIGN.md`, `DATABASE.md`, `API.md`, source code, etc. — "
            f"live under that absolute path. Use it directly when reading "
            f"or writing project files; do not assume the current working "
            f"directory.\n"
        )

    base = _VIBE_PROMPTS_DIR / "base.md"
    if base.is_file():
        parts.append(base.read_text(encoding="utf-8").rstrip())

    mode_file = _VIBE_PROMPTS_DIR / "modes" / f"{mode}.md"
    if mode_file.is_file():
        parts.append(mode_file.read_text(encoding="utf-8").rstrip())

    for addon in add_ons:
        f = _VIBE_PROMPTS_DIR / "add-ons" / f"{addon}.md"
        if f.is_file():
            parts.append(f.read_text(encoding="utf-8").rstrip())

    for skill_rel in _VIBE_PHASE_SKILLS.get(phase, ()):
        skill_file = PROJECT_ROOT / "skills" / skill_rel / "SKILL.md"
        if skill_file.is_file():
            body = skill_file.read_text(encoding="utf-8").rstrip()
            parts.append(f"## Pre-loaded skill: `{skill_rel}`\n\n{body}")

    phase_file = _VIBE_PROMPTS_DIR / "phases" / f"{phase}.md"
    if phase_file.is_file():
        parts.append(phase_file.read_text(encoding="utf-8").rstrip())

    return "\n\n".join(parts).strip() + "\n"


@app.get("/api/vibe/projects/{name}/system-prompt")
async def vibe_get_system_prompt(name: str, request: Request):
    """Return the composed system prompt the frontend can send as the
    kickoff message in the brainstorm chat. Kept as a separate endpoint
    so prompt edits don't require a project re-create."""
    _require_token(request)
    d = _vibe_project_dir(name)
    marker = _vibe_read_marker(d)
    return {"prompt": _vibe_compose_system_prompt(marker)}


class VibeProjectPatch(BaseModel):
    summary: Optional[str] = None
    session_id: Optional[str] = None
    phase: Optional[str] = None


@app.patch("/api/vibe/projects/{name}")
async def vibe_update_project(name: str, body: VibeProjectPatch, request: Request):
    """Update mutable fields on project.json: running summary, chat session id, phase."""
    _require_token(request)
    d = _vibe_project_dir(name)
    marker = _vibe_read_marker(d)
    if body.summary is not None:
        marker["summary"] = body.summary
    if body.session_id is not None:
        marker["session_id"] = body.session_id
    if body.phase is not None:
        if body.phase not in _VIBE_PHASES:
            raise HTTPException(status_code=400, detail=f"unknown phase: {body.phase}")
        marker["phase"] = body.phase
    _vibe_write_marker(d, marker)
    return {"ok": True, "project": marker}


class VibeModelUpdate(BaseModel):
    """Single-phase override. Empty/omitted ``model`` resets to default."""
    phase: str
    model: Optional[str] = None


@app.get("/api/vibe/projects/{name}/models")
async def vibe_get_models(name: str, request: Request):
    """Return the per-phase model assignment for a project.

    Shape::

        {
            "defaults":  {phase: "<provider>/<model>", ...},
            "overrides": {phase: "<provider>/<model>", ...},   # subset of phases
            "effective": {phase: "<provider>/<model>", ...},   # override > default
            "available": [{"id", "provider", "label"}, ...]
        }

    Frontend (PR-003) renders ``effective`` next to each step in the rail and
    offers ``available`` as the picker dropdown options.
    """
    _require_token(request)
    d = _vibe_project_dir(name)
    marker = _vibe_read_marker(d)
    overrides = marker.get("model_per_phase") or {}
    effective = {
        phase: overrides.get(phase) or _VIBE_PHASE_MODEL_DEFAULTS.get(phase, "")
        for phase in _VIBE_PHASES
    }
    return {
        "defaults": _VIBE_PHASE_MODEL_DEFAULTS,
        "overrides": overrides,
        "effective": effective,
        "available": _VIBE_AVAILABLE_MODELS,
    }


@app.put("/api/vibe/projects/{name}/models")
async def vibe_set_model(name: str, body: VibeModelUpdate, request: Request):
    """Override one phase's model, or reset to default by passing empty model.

    No model-catalog validation here — keeping the picker flexible to add new
    SKUs in MODEL_SELECTION.md without code changes. The agent will surface
    a clear error on first call if the SKU is bogus.
    """
    _require_token(request)
    if body.phase not in _VIBE_PHASES:
        raise HTTPException(status_code=400, detail=f"unknown phase: {body.phase}")
    d = _vibe_project_dir(name)
    marker = _vibe_read_marker(d)
    overrides = dict(marker.get("model_per_phase") or {})
    model = (body.model or "").strip()
    if model:
        overrides[body.phase] = model
    else:
        # Empty value = explicit reset → drop from overrides so the default wins.
        overrides.pop(body.phase, None)
    marker["model_per_phase"] = overrides
    _vibe_write_marker(d, marker)
    effective = {
        phase: overrides.get(phase) or _VIBE_PHASE_MODEL_DEFAULTS.get(phase, "")
        for phase in _VIBE_PHASES
    }
    _log.info("vibe project %s: model_per_phase[%s] = %s", name, body.phase, model or "<default>")
    return {"ok": True, "overrides": overrides, "effective": effective}


class VibeRequirementsAccept(BaseModel):
    content: str


@app.post("/api/vibe/projects/{name}/requirements")
async def vibe_write_requirements(
    name: str, body: VibeRequirementsAccept, request: Request,
):
    """Write REQUIREMENTS.md and advance phase to 'requirements'.

    The frontend sends the agreed-on summary text; this just persists it.
    Subsequent phases read this file as the source of truth.
    """
    _require_token(request)
    d = _vibe_project_dir(name)
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="requirements content is empty")
    (d / "REQUIREMENTS.md").write_text(content + "\n", encoding="utf-8")
    marker = _vibe_read_marker(d)
    marker["phase"] = "requirements"
    _vibe_write_marker(d, marker)
    _log.info("vibe project %s: REQUIREMENTS.md written, phase -> requirements", name)
    return {"ok": True, "project": marker}


class VibePlanningAccept(BaseModel):
    content: str


@app.post("/api/vibe/projects/{name}/planning")
async def vibe_write_planning(
    name: str, body: VibePlanningAccept, request: Request,
):
    """Write PLANNING.md and advance phase to 'development'."""
    _require_token(request)
    d = _vibe_project_dir(name)
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="planning content is empty")
    (d / "PLANNING.md").write_text(content + "\n", encoding="utf-8")
    marker = _vibe_read_marker(d)
    marker["phase"] = "development"
    _vibe_write_marker(d, marker)
    _log.info("vibe project %s: PLANNING.md written, phase -> development", name)
    return {"ok": True, "project": marker}


# Hard ceiling on how long the security-review subprocess may run before
# we give up and 504 the request. Thorough scans on bigger Vibe-Code
# projects (form-registration with file upload, lots of pages) genuinely
# take a few minutes; small ones finish in well under a minute.
_VIBE_SECURITY_REVIEW_TIMEOUT_S: int = 900


@app.post("/api/vibe/projects/{name}/security-review")
async def vibe_security_review(name: str, request: Request):
    """Run the claude-code-security-review skill against the project and
    persist the resulting markdown to SECURITY_REVIEW.md.

    Implementation: spawns `hermes --oneshot` as a subprocess scoped to the
    project directory, passing it a prompt that embeds the vendored
    SKILL.md plus a short task brief. The agent uses its own file-reading
    tools (Glob / Read) against the project tree, then writes the
    findings to SECURITY_REVIEW.md per the skill's REQUIRED OUTPUT FORMAT.
    Subprocess isolation keeps the web_server process clean (no global
    YOLO/logging side effects) and gives us a hard timeout.

    The endpoint does NOT advance the phase past `security` — the user
    reads the report in the SecurityPane and approves through to `done`
    (or rolls back to `improvement` to fix issues and re-run).
    """
    _require_token(request)
    d = _vibe_project_dir(name)
    marker = _vibe_read_marker(d)

    skill_path = (
        PROJECT_ROOT
        / "skills"
        / "red-teaming"
        / "claude-code-security-review"
        / "SKILL.md"
    )
    if not skill_path.is_file():
        raise HTTPException(
            status_code=500,
            detail="claude-code-security-review skill not vendored at "
            "skills/red-teaming/claude-code-security-review/SKILL.md",
        )
    skill_body = skill_path.read_text(encoding="utf-8")

    prompt = (
        f"You are running a security review of the Sopify Vibe Code project "
        f"located at `{d}`.\n\n"
        f"## Skill: claude-code-security-review\n\n"
        f"{skill_body}\n\n"
        f"## Task for this run\n\n"
        f"1. Use Glob + Read to walk every relevant source file under "
        f"`{d}` (`.ts`, `.tsx`, `.js`, `.py`, `.sql`, and configs). Do not "
        f"run shell commands to reproduce vulnerabilities; reading is enough.\n"
        f"2. Apply the skill methodology above to find HIGH and MEDIUM "
        f"severity findings at confidence ≥ 8. Apply the HARD EXCLUSIONS.\n"
        f"3. Write the markdown report to `{d}/SECURITY_REVIEW.md` using "
        f"the skill's REQUIRED OUTPUT FORMAT exactly (one `# Vuln N: ...` "
        f"heading per finding, severity / description / exploit / fix).\n"
        f"4. After writing the file, your final reply must be a single line "
        f"in this exact shape: `Done — wrote SECURITY_REVIEW.md with N findings.`\n"
    )

    hermes_bin = shutil.which("hermes")
    if not hermes_bin:
        raise HTTPException(
            status_code=500,
            detail="`hermes` binary not on PATH; cannot spawn the oneshot agent",
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            hermes_bin,
            "--oneshot",
            prompt,
            cwd=str(d),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"failed to spawn hermes --oneshot: {exc}",
        )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=_VIBE_SECURITY_REVIEW_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        proc.kill()
        try:
            await proc.wait()
        except Exception:
            pass
        raise HTTPException(
            status_code=504,
            detail=(
                f"security review timed out after "
                f"{_VIBE_SECURITY_REVIEW_TIMEOUT_S}s"
            ),
        )

    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        # Hermes oneshot already silences stdout/stderr from the agent for
        # display purposes, so a non-zero exit usually means a startup or
        # provider error rather than an in-tool failure. Surface a slice of
        # stderr (and stdout as fallback) for the UI to render.
        snippet = (stderr_text or stdout_text or "<no output>")[:800]
        raise HTTPException(
            status_code=500,
            detail=f"hermes --oneshot exit {proc.returncode}: {snippet}",
        )

    report_file = d / "SECURITY_REVIEW.md"
    if report_file.is_file():
        report = report_file.read_text(encoding="utf-8")
    else:
        # Agent finished cleanly but didn't write the report — usually means
        # the model decided there was nothing to flag and just printed a
        # short status line. Persist that as the report so the UI has
        # something to display and the file exists for the Done summary.
        body = stdout_text.strip() or "_(no findings reported)_"
        report = (
            "# Security Review\n\n"
            "_The agent finished without writing a structured report. Raw "
            "final output below — re-run if you expected findings._\n\n"
            f"```\n{body[:8000]}\n```\n"
        )
        report_file.write_text(report, encoding="utf-8")

    if marker.get("phase") != "security":
        marker["phase"] = "security"
        _vibe_write_marker(d, marker)

    _log.info(
        "vibe project %s: security review complete (%d bytes, exit %d)",
        name,
        len(report),
        proc.returncode,
    )
    return {"ok": True, "project": marker, "report": report}


class _SecurityFindingAck(BaseModel):
    addressed: bool


@app.put("/api/vibe/projects/{name}/security-findings/{vuln_id}")
async def vibe_set_security_finding_ack(
    name: str,
    vuln_id: str,
    body: _SecurityFindingAck,
    request: Request,
):
    """Mark / unmark a single security finding as addressed.

    PR-010 — the security checklist UI calls this when the user ticks a
    finding's checkbox. State lives on the project marker so it survives
    re-opens and reloads. ``vuln_id`` matches the IDs the frontend parser
    derives from ``SECURITY_REVIEW.md`` headings (category + location);
    re-running the review with the same finding text keeps the same ID
    so the user's acks aren't lost. The endpoint is idempotent: ticking
    an already-ticked finding is a no-op.
    """
    _require_token(request)
    if not vuln_id or len(vuln_id) > 256:
        raise HTTPException(status_code=400, detail="invalid vuln_id")
    d = _vibe_project_dir(name)
    marker = _vibe_read_marker(d)
    current = marker.get("addressed_security_findings") or []
    if not isinstance(current, list):
        current = []
    addressed: set[str] = {str(x) for x in current if isinstance(x, str)}
    if body.addressed:
        addressed.add(vuln_id)
    else:
        addressed.discard(vuln_id)
    marker["addressed_security_findings"] = sorted(addressed)
    _vibe_write_marker(d, marker)
    return {
        "ok": True,
        "vuln_id": vuln_id,
        "addressed": body.addressed,
        "addressed_security_findings": marker["addressed_security_findings"],
    }


_VIBE_UPLOADS_DIRNAME = "uploads"
_VIBE_UPLOADS_MAX_BYTES = 50 * 1024 * 1024  # 50 MB per file
_VIBE_UPLOADS_ALLOWED_EXTS = frozenset({
    ".csv", ".xlsx", ".xls",                       # tabular data
    ".md", ".markdown",                             # spec markdown
    ".png", ".jpg", ".jpeg", ".webp", ".gif",       # images
})


@app.post("/api/vibe/projects/{name}/uploads")
async def vibe_upload_files(name: str, request: Request):
    """Save user-provided context files into `<project>/uploads/`.

    Accepts multipart form-data; every file part (any field name) is written
    flat into the uploads dir, dropping any path components from the
    client-supplied filename. The brainstorm agent reads this directory as
    additional context (see brainstorm phase prompt).

    Validation: extension must be in `_VIBE_UPLOADS_ALLOWED_EXTS`, each file
    must be ≤ 50 MB. Existing files with the same name are overwritten so the
    UI can show a stable filename when the user re-uploads.
    """
    _require_token(request)
    d = _vibe_project_dir(name)
    uploads_dir = d / _VIBE_UPLOADS_DIRNAME
    uploads_dir.mkdir(parents=True, exist_ok=True)
    project_root = d.resolve()

    form = await request.form()
    saved: list[dict] = []
    for _key, value in form.multi_items():
        filename = getattr(value, "filename", None)
        if not filename:
            continue
        safe_name = Path(filename).name
        if not safe_name or safe_name in (".", ".."):
            continue
        ext = Path(safe_name).suffix.lower()
        if ext not in _VIBE_UPLOADS_ALLOWED_EXTS:
            raise HTTPException(
                status_code=400,
                detail=f"file type not allowed: {safe_name}",
            )
        # Defense-in-depth: re-resolve and ensure dest still inside project dir
        dest = uploads_dir / safe_name
        try:
            (uploads_dir.resolve() / safe_name).relative_to(project_root)
        except ValueError:
            raise HTTPException(
                status_code=403,
                detail="upload target outside project dir",
            )
        written = 0
        try:
            with dest.open("wb") as fh:
                while True:
                    chunk = await value.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > _VIBE_UPLOADS_MAX_BYTES:
                        fh.close()
                        dest.unlink(missing_ok=True)
                        raise HTTPException(
                            status_code=413,
                            detail=f"file too large: {safe_name}",
                        )
                    fh.write(chunk)
        finally:
            await value.close()
        saved.append({
            "name": safe_name,
            "size": dest.stat().st_size,
        })
    _log.info("vibe project %s: %d upload(s) saved", name, len(saved))
    return {"ok": True, "uploaded": saved}


@app.get("/api/vibe/projects/{name}/uploads")
async def vibe_list_uploads(name: str, request: Request):
    """List files currently stored in `<project>/uploads/`."""
    _require_token(request)
    d = _vibe_project_dir(name)
    uploads_dir = d / _VIBE_UPLOADS_DIRNAME
    if not uploads_dir.is_dir():
        return {"files": []}
    files = []
    for p in sorted(uploads_dir.iterdir()):
        if not p.is_file():
            continue
        files.append({
            "name": p.name,
            "size": p.stat().st_size,
        })
    return {"files": files}


@app.delete("/api/vibe/projects/{name}")
async def vibe_delete_project(name: str, request: Request):
    """Remove a vibe project directory."""
    _require_token(request)
    d = _vibe_project_dir(name)
    try:
        shutil.rmtree(d)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    _log.info("vibe project deleted: %s", name)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Dev-server lifecycle — per-chat-session port owner tracking.
#
# Vibe Code's Building view and /panel's canvas iframe both want to show
# the agent's running dev server (Vite / Next / etc.). Multiple sessions
# can't share port 5173, so we treat the dev server as a per-session
# resource: switching the active session pauses one and revives the other.
#
# State + lifecycle live in hermes_cli/dev_server_manager.py. Detection
# happens in tui_gateway/server.py when a tool's stdout prints a localhost
# URL.
# ---------------------------------------------------------------------------


class _SetActiveSessionBody(BaseModel):
    session_key: str


@app.get("/api/vibe/runtimes")
async def vibe_runtimes(request: Request):
    """Snapshot of every dev-server runtime grouped by Vibe Code project.

    PR-007 — the dashboard polls this to decide which projects have a
    running 517x port in the background. Switching projects in the UI is
    a state change only; the runtime keeps going and shows up here until
    the user explicitly stops it (POST /api/dev-server/stop) or the
    sandbox tears down.

    Response shape::

        {
          "projects": {
            "my-cool-app": [
              {
                "session_key": "...",
                "port": 5174,
                "url": "http://localhost:5174/",
                "status": "running",
                "pid": 1234,
                "vibe_project": "my-cool-app",
                "command": "vite --port 5174",
                "cwd": "/workspace/my-cool-app",
                "first_seen": 17xx, "last_seen": 17xx, "last_error": null
              }
            ]
          }
        }
    """
    _require_token(request)
    from hermes_cli import dev_server_manager as _dsm
    return {"projects": _dsm.list_runtimes_by_project()}


@app.get("/api/dev-server")
async def dev_server_list(request: Request, session_key: str = ""):
    """List known dev servers for a session (or all running servers when
    no session_key passed)."""
    _require_token(request)
    from hermes_cli import dev_server_manager as _dsm

    if session_key:
        return {
            "session_key": session_key,
            "active_session_key": _dsm.get_active_session_key(),
            "servers": _dsm.list_for_session(session_key),
        }
    return {
        "active_session_key": _dsm.get_active_session_key(),
        "servers": _dsm.list_all_active_running(),
    }


@app.post("/api/sessions/set-active")
async def sessions_set_active(body: _SetActiveSessionBody, request: Request):
    """Mark `session_key` as the active session: pause every running dev
    server tied to a different session, revive paused servers in this one.
    Returns a summary of what changed."""
    _require_token(request)
    from hermes_cli import dev_server_manager as _dsm

    return _dsm.set_active_session(body.session_key)


class _StopServerBody(BaseModel):
    session_key: str
    port: int


class _KillPortBody(BaseModel):
    port: int


@app.post("/api/dev-server/kill-port")
async def dev_server_kill_port(body: _KillPortBody, request: Request):
    """Kill every registered spec on ``port`` (any session) + best-effort
    SIGTERM of an orphan listener if nothing's registered.

    PR-008 — the Panel preview is fixed to port 5173 and the Panel UI
    calls this on every Static→Live transition so a stale runtime from a
    prior session can't bleed through. Idempotent. See
    ``dev_server_manager.stop_servers_on_port`` for the response shape.
    """
    _require_token(request)
    from hermes_cli import dev_server_manager as _dsm
    return _dsm.stop_servers_on_port(int(body.port))


@app.post("/api/dev-server/stop")
async def dev_server_stop(body: _StopServerBody, request: Request):
    """Manual kill button — pause one specific server without changing
    active session."""
    _require_token(request)
    from hermes_cli import dev_server_manager as _dsm

    ok = _dsm.stop_server(body.session_key, body.port)
    return {"ok": ok}


# ---------------------------------------------------------------------------
# ENCM proxy — forwards /api/encm/<path> to the local Sopify daemon at
# 127.0.0.1:7777/api/v1/<path>. The dashboard keeps its existing
# X-Hermes-Session-Token auth; the bearer secret stays server-side. See
# hermes_cli/encm_client.py and SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md §1.5.
# ---------------------------------------------------------------------------


@app.api_route(
    "/api/encm/{daemon_path:path}",
    methods=["GET", "POST", "PUT", "DELETE"],
)
async def proxy_encm(daemon_path: str, request: Request):
    from hermes_cli.encm_client import proxy as encm_proxy

    query = dict(request.query_params) or None
    body: Optional[Any] = None
    if request.method in ("POST", "PUT", "DELETE"):
        ct = request.headers.get("content-type", "")
        if "application/json" in ct:
            raw = await request.body()
            if raw:
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    raise HTTPException(400, detail="invalid JSON body")

    status_code, payload = await encm_proxy(
        request.method, daemon_path, query=query, body=body
    )
    if status_code == 204:
        return Response(status_code=204)
    return JSONResponse(content=payload, status_code=status_code)


def _mount_plugin_api_routes():
    """Import and mount backend API routes from plugins that declare them.

    Each plugin's ``api`` field points to a Python file that must expose
    a ``router`` (FastAPI APIRouter).  Routes are mounted under
    ``/api/plugins/<name>/``.
    """
    for plugin in _get_dashboard_plugins():
        api_file_name = plugin.get("_api_file")
        if not api_file_name:
            continue
        api_path = Path(plugin["_dir"]) / api_file_name
        if not api_path.exists():
            _log.warning("Plugin %s declares api=%s but file not found", plugin["name"], api_file_name)
            continue
        try:
            module_name = f"hermes_dashboard_plugin_{plugin['name']}"
            spec = importlib.util.spec_from_file_location(module_name, api_path)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            # Register in sys.modules BEFORE exec_module so pydantic/FastAPI
            # can resolve forward references (e.g. models defined in a file
            # that uses `from __future__ import annotations`). Without this,
            # TypeAdapter lazy-build fails at first request with
            # "is not fully defined" because the module namespace isn't
            # reachable by name for string-annotation resolution.
            sys.modules[module_name] = mod
            try:
                spec.loader.exec_module(mod)
            except Exception:
                sys.modules.pop(module_name, None)
                raise
            router = getattr(mod, "router", None)
            if router is None:
                _log.warning("Plugin %s api file has no 'router' attribute", plugin["name"])
                continue
            app.include_router(router, prefix=f"/api/plugins/{plugin['name']}")
            _log.info("Mounted plugin API routes: /api/plugins/%s/", plugin["name"])
        except Exception as exc:
            _log.warning("Failed to load plugin %s API routes: %s", plugin["name"], exc)


# Mount plugin API routes before the SPA catch-all.
_mount_plugin_api_routes()

mount_spa(app)


def start_server(
    host: str = "127.0.0.1",
    port: int = 9119,
    open_browser: bool = True,
    allow_public: bool = False,
    *,
    embedded_chat: bool = False,
):
    """Start the web UI server."""
    import uvicorn

    global _DASHBOARD_EMBEDDED_CHAT_ENABLED
    _DASHBOARD_EMBEDDED_CHAT_ENABLED = embedded_chat

    _LOCALHOST = ("127.0.0.1", "localhost", "::1")
    if host not in _LOCALHOST and not allow_public:
        raise SystemExit(
            f"Refusing to bind to {host} — the dashboard exposes API keys "
            f"and config without robust authentication.\n"
            f"Use --insecure to override (NOT recommended on untrusted networks)."
        )
    if host not in _LOCALHOST:
        _log.warning(
            "Binding to %s with --insecure — the dashboard has no robust "
            "authentication. Only use on trusted networks.", host,
        )

    # Record the bound host so host_header_middleware can validate incoming
    # Host headers against it. Defends against DNS rebinding (GHSA-ppp5-vxwm-4cf7).
    # bound_port is also stashed so /api/pty can build the back-WS URL the
    # PTY child uses to publish events to the dashboard sidebar.
    app.state.bound_host = host
    app.state.bound_port = port

    if open_browser:
        import webbrowser

        # On headless Linux (no DISPLAY or WAYLAND_DISPLAY) some registered
        # browsers are TUI programs (links, lynx, www-browser) that try to
        # take over the terminal.  That can send SIGHUP to the server process
        # and cause an immediate exit even though uvicorn bound successfully.
        # Skip the auto-open attempt on headless systems and let the user
        # open the URL manually.  macOS and Windows are always considered
        # display-capable.
        _has_display = (
            sys.platform != "linux"
            or bool(os.environ.get("DISPLAY"))
            or bool(os.environ.get("WAYLAND_DISPLAY"))
        )

        if _has_display:
            def _open():
                try:
                    time.sleep(1.0)
                    webbrowser.open(f"http://{host}:{port}")
                except Exception:
                    pass

            threading.Thread(target=_open, daemon=True).start()
        else:
            _log.debug(
                "Skipping browser-open: no DISPLAY or WAYLAND_DISPLAY detected "
                "(headless Linux). Pass --no-open to suppress this detection."
            )

    print(f"  Sopify Dashboard → http://{host}:{port}")
    # proxy_headers=False so _ws_client_is_allowed sees the real connection peer
    # rather than X-Forwarded-For's rewritten value (which would defeat the
    # loopback gate when behind a reverse proxy).
    uvicorn.run(app, host=host, port=port, log_level="warning", proxy_headers=False)

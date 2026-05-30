"""Per-session dev-server lifecycle manager.

Sopify's Vibe Code Building view + the /panel canvas iframe both want to show
whatever the agent's `npm run dev` (or similar) is serving. That dev server
lives in the same network namespace as every other session running in the
same sandbox — port 5173 can only be bound by one process at a time. So the
UX model is:

    active session A: Vite on 5173, Node on 3000  ← running
    user switches to session B:
       1. SIGTERM PGIDs of A's running servers
       2. wait for ports to free
       3. respawn B's previously-paused servers (sequential, in stable order)
       4. update iframe src in browser

Module state lives in a single process (the FastAPI dashboard, which also
hosts the in-process gateway when /api/ws is used). The gateway pushes
detected URLs in here via `register_detected_url`; the web_server proxies
list / set-active / stop requests here.

Subprocess gateway (PTY-mode chat) does NOT share memory with this module —
the per-session feature is intentionally scoped to /api/ws clients (Vibe
Code + /panel). PTY chat sees no detected servers; not a regression because
that mode has no preview iframe anyway.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_log = logging.getLogger("sopify.dev_server")

# ---------------------------------------------------------------------------
# Detection — regex + ANSI strip
# ---------------------------------------------------------------------------

# Strip CSI / OSC / SGR escape sequences before regex matching so colorized
# Vite output like `Local:\x1b[36m  http://localhost:5173/ \x1b[39m` matches.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")

# Catches http://localhost:5173 / http://0.0.0.0:5173 / http://127.0.0.1:5173
# with optional path. Captures port.
_URL_RE = re.compile(
    r"https?://(?:localhost|0\.0\.0\.0|127\.0\.0\.1|\[::1?\])(?::(?P<port>\d+))?(?:/[^\s]*)?",
    re.IGNORECASE,
)

# Reserved — don't claim these as dev-server ports.
_RESERVED_PORTS = frozenset({9119, 7777})

# Range of ports we treat as dev-server candidates (must match the launcher's
# publish list in `sopify`). Sets the upper bound for /proc scanning too.
DEV_PORT_CANDIDATES = frozenset({5173, 4173, 3000, 4321, 8000, 8080})


def extract_dev_url(text: str) -> Optional[tuple[int, str]]:
    """Return (port, canonical_url) if `text` contains a recognizable localhost
    dev URL on a candidate port. Strips ANSI first."""
    if not text:
        return None
    cleaned = _ANSI_RE.sub("", text)
    for m in _URL_RE.finditer(cleaned):
        port_str = m.group("port")
        if not port_str:
            continue
        try:
            port = int(port_str)
        except ValueError:
            continue
        if port in _RESERVED_PORTS:
            continue
        if port not in DEV_PORT_CANDIDATES:
            # Out-of-band ports (e.g. Vite auto-incremented to 5175) — surface
            # them anyway; the launcher's publish list is the limit for what
            # reaches the user's browser, but we still register so the UI can
            # warn / iframe will fail gracefully.
            pass
        return port, f"http://localhost:{port}/"
    return None


# ---------------------------------------------------------------------------
# Port introspection — /proc/net/tcp{,6}
# ---------------------------------------------------------------------------


def is_port_listening(port: int) -> bool:
    """True if any process in this network namespace is LISTEN on `port`."""
    return _scan_listen_ports().get(port) is not None


def _scan_listen_ports() -> dict[int, int]:
    """Return {port: inode} for every LISTEN socket. State 0A = LISTEN."""
    out: dict[int, int] = {}
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path, "r") as f:
                next(f)  # header
                for line in f:
                    parts = line.split()
                    if len(parts) < 10:
                        continue
                    if parts[3] != "0A":  # LISTEN
                        continue
                    try:
                        port = int(parts[1].rsplit(":", 1)[1], 16)
                        inode = int(parts[9])
                    except (ValueError, IndexError):
                        continue
                    # Last write wins — fine for our purpose (any PID owning it)
                    out[port] = inode
        except (FileNotFoundError, PermissionError):
            continue
    return out


def find_pid_for_port(port: int) -> Optional[int]:
    """Resolve PID listening on `port` by cross-referencing /proc/net/tcp
    inode with /proc/*/fd/* socket symlinks. Returns None on Linux/Mac
    (Mac has no /proc), or when not found."""
    ports = _scan_listen_ports()
    inode = ports.get(port)
    if inode is None:
        return None
    target = f"socket:[{inode}]"
    proc = Path("/proc")
    if not proc.is_dir():
        return None
    for pid_dir in proc.iterdir():
        if not pid_dir.name.isdigit():
            continue
        fd_dir = pid_dir / "fd"
        try:
            entries = list(fd_dir.iterdir())
        except (PermissionError, FileNotFoundError):
            continue
        for fd in entries:
            try:
                if os.readlink(fd) == target:
                    return int(pid_dir.name)
            except OSError:
                continue
    return None


def find_pgid(pid: int) -> Optional[int]:
    """Return the process group id of `pid`, or None if it's gone."""
    try:
        return os.getpgid(pid)
    except (ProcessLookupError, PermissionError):
        return None


def wait_for_port_free(port: int, timeout: float = 5.0, interval: float = 0.2) -> bool:
    """Block until `port` has no LISTEN owner, or `timeout` elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_port_listening(port):
            return True
        time.sleep(interval)
    return not is_port_listening(port)


def wait_for_port_listening(
    port: int, timeout: float = 20.0, interval: float = 0.3
) -> bool:
    """Block until `port` is LISTEN, or `timeout` elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_port_listening(port):
            return True
        # On macOS /proc may not exist — fall back to a connect probe.
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except OSError:
            pass
        time.sleep(interval)
    return False


def kill_process_group(pgid: int, term_timeout: float = 3.0) -> bool:
    """SIGTERM the group, wait up to `term_timeout`, then SIGKILL.

    Returns True if the group is gone after the call. Idempotent — already-
    dead groups return True silently.
    """
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return True  # gone or not ours
    except OSError as e:
        _log.warning("SIGTERM failed for pgid=%d: %s", pgid, e)

    deadline = time.time() + term_timeout
    while time.time() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return True
        time.sleep(0.1)

    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return True
    except OSError as e:
        _log.warning("SIGKILL failed for pgid=%d: %s", pgid, e)
        return False
    return True


# ---------------------------------------------------------------------------
# Per-session registry
# ---------------------------------------------------------------------------


@dataclass
class DevServerSpec:
    """One dev server tied to one chat session.

    `command` / `cwd` are intent — what was run to start this. Used for
    revive on session re-activation. Both come from the agent's tool call
    args at first detection (parsed in `register_detected_url`).

    ``vibe_project`` (PR-007) is the Vibe Code project name that owns this
    session, or None for Panel / non-Vibe sessions. Used by
    ``GET /api/vibe/runtimes`` to group running servers by project so the
    UI can show which projects have backgrounded runtimes when the user
    switches projects.
    """

    session_key: str
    port: int
    url: str
    status: str = "running"  # running | paused | failed | unknown
    pid: Optional[int] = None
    pgid: Optional[int] = None
    command: Optional[str] = None
    cwd: Optional[str] = None
    env: Optional[dict[str, str]] = None
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    last_error: Optional[str] = None
    vibe_project: Optional[str] = None


# session_key → list of specs. Most-recent first.
_registry: dict[str, list[DevServerSpec]] = {}
_registry_lock = threading.RLock()

# session_key currently "active" — the one whose servers should be running.
# None at startup (no session opened yet).
_active_session_key: Optional[str] = None
_active_lock = threading.RLock()


def get_active_session_key() -> Optional[str]:
    with _active_lock:
        return _active_session_key


def list_for_session(session_key: str) -> list[dict]:
    """Snapshot view of session's specs as plain dicts (for JSON serialization)."""
    with _registry_lock:
        specs = _registry.get(session_key, [])
        return [_spec_to_dict(s) for s in specs]


def list_all_active_running() -> list[dict]:
    """All specs currently running, across sessions. For the global
    `/api/dev-ports` fallback used when chat parsing didn't catch a URL."""
    out: list[dict] = []
    with _registry_lock:
        for specs in _registry.values():
            for s in specs:
                if s.status == "running":
                    out.append(_spec_to_dict(s))
    return out


def _spec_to_dict(s: DevServerSpec) -> dict:
    return {
        "session_key": s.session_key,
        "port": s.port,
        "url": s.url,
        "status": s.status,
        "pid": s.pid,
        "command": s.command,
        "cwd": s.cwd,
        "first_seen": s.first_seen,
        "last_seen": s.last_seen,
        "last_error": s.last_error,
        "vibe_project": s.vibe_project,
    }


def list_runtimes_by_project() -> dict[str, list[dict]]:
    """Group every spec (any status) by its ``vibe_project`` name.

    Used by ``GET /api/vibe/runtimes`` (PR-007) so the dashboard can show
    which Vibe Code projects have backgrounded runtimes. Specs with no
    project (Panel chat, PTY sessions) are omitted from the result.
    """
    out: dict[str, list[dict]] = {}
    with _registry_lock:
        for specs in _registry.values():
            for s in specs:
                if not s.vibe_project:
                    continue
                out.setdefault(s.vibe_project, []).append(_spec_to_dict(s))
    return out


def register_detected_url(
    session_key: str,
    port: int,
    url: str,
    *,
    command_hint: Optional[str] = None,
    cwd_hint: Optional[str] = None,
    vibe_project: Optional[str] = None,
) -> DevServerSpec:
    """Called from the gateway's tool-output watcher when we see a localhost
    URL printed by the agent. Resolves PID/PGID via /proc; if process is on
    a foreign Python process (e.g. PTY subprocess gateway), we still record
    the spec but pid/pgid stay None — kill() will be a no-op for that case.

    Idempotent: same (session, port) → updates last_seen, doesn't dupe.

    ``vibe_project`` (PR-007) attributes this runtime to a Vibe Code project
    so the /api/vibe/runtimes endpoint can group servers by project. Once
    set, subsequent registrations DON'T overwrite to a falsy value — a
    session that later loses its project binding (rare) keeps the original
    attribution so background runtimes don't disappear from the registry.
    """
    if not session_key:
        return _make_orphan_spec(port, url)
    pid = find_pid_for_port(port)
    pgid = find_pgid(pid) if pid is not None else None
    with _registry_lock:
        specs = _registry.setdefault(session_key, [])
        for existing in specs:
            if existing.port == port:
                existing.last_seen = time.time()
                existing.url = url
                existing.status = "running"
                if pid is not None:
                    existing.pid = pid
                    existing.pgid = pgid
                if command_hint and not existing.command:
                    existing.command = command_hint
                if cwd_hint and not existing.cwd:
                    existing.cwd = cwd_hint
                if vibe_project and not existing.vibe_project:
                    existing.vibe_project = vibe_project
                return existing
        spec = DevServerSpec(
            session_key=session_key,
            port=port,
            url=url,
            status="running",
            pid=pid,
            pgid=pgid,
            command=command_hint,
            cwd=cwd_hint,
            vibe_project=vibe_project,
        )
        specs.append(spec)
        return spec


def _make_orphan_spec(port: int, url: str) -> DevServerSpec:
    return DevServerSpec(session_key="", port=port, url=url, status="unknown")


def remove_session(session_key: str) -> None:
    """Forget everything about a session (e.g. on session.delete)."""
    with _registry_lock:
        _registry.pop(session_key, None)


# ---------------------------------------------------------------------------
# Lifecycle — switch / pause / revive
# ---------------------------------------------------------------------------

_switch_lock = threading.Lock()


def set_active_session(session_key: Optional[str]) -> dict:
    """Atomic switch: pause all running specs whose session_key != target,
    revive paused specs in target (sequential, 5173 first). Returns a
    summary dict for the API caller."""
    summary = {
        "active_session_key": session_key,
        "paused": [],
        "revived": [],
        "failed": [],
        "skipped": [],
    }
    with _switch_lock:
        global _active_session_key
        with _active_lock:
            prev = _active_session_key
            if prev == session_key:
                # Already active — still re-verify state in case servers died
                # between switches. Cheap idempotent check.
                if session_key is not None:
                    _refresh_status(session_key)
                return summary
            _active_session_key = session_key

        # 1. Pause everything in other sessions
        with _registry_lock:
            other_specs = []
            for k, specs in _registry.items():
                if k == session_key:
                    continue
                for s in specs:
                    if s.status == "running":
                        other_specs.append(s)

        for spec in other_specs:
            ok = _pause_spec(spec)
            (summary["paused"] if ok else summary["failed"]).append(_spec_to_dict(spec))

        if session_key is None:
            return summary

        # 2. Revive specs in target. Sort: 5173 first, then ascending.
        with _registry_lock:
            target_specs = list(_registry.get(session_key, []))
        target_specs.sort(key=lambda s: (s.port != 5173, s.port))

        for spec in target_specs:
            if spec.status == "running":
                # Already up — verify, otherwise mark paused for retry
                if is_port_listening(spec.port):
                    summary["skipped"].append(_spec_to_dict(spec))
                    continue
                spec.status = "paused"
            if spec.status != "paused":
                continue
            if not spec.command or not spec.cwd:
                spec.status = "failed"
                spec.last_error = "no command/cwd recorded — cannot revive"
                summary["failed"].append(_spec_to_dict(spec))
                continue
            ok = _revive_spec(spec)
            (summary["revived"] if ok else summary["failed"]).append(
                _spec_to_dict(spec)
            )

    return summary


def _pause_spec(spec: DevServerSpec) -> bool:
    """SIGTERM the spec's process group, wait for port to free, update state."""
    if spec.pgid is None and spec.pid is not None:
        spec.pgid = find_pgid(spec.pid)
    if spec.pgid is not None:
        kill_process_group(spec.pgid)
    elif spec.pid is not None:
        try:
            os.kill(spec.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    spec.pid = None
    spec.pgid = None
    spec.status = "paused"
    if not wait_for_port_free(spec.port, timeout=5):
        spec.last_error = f"port {spec.port} still in use after kill"
        return False
    spec.last_error = None
    return True


def _revive_spec(spec: DevServerSpec) -> bool:
    """Re-spawn the spec's command in its cwd. Wait for port to come up."""
    if not spec.command or not spec.cwd:
        spec.status = "failed"
        spec.last_error = "no command/cwd to revive"
        return False
    if not wait_for_port_free(spec.port, timeout=3):
        spec.status = "failed"
        spec.last_error = f"port {spec.port} still busy"
        return False
    try:
        proc = subprocess.Popen(
            spec.command,
            shell=True,
            cwd=spec.cwd,
            env=spec.env,
            preexec_fn=os.setsid,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        spec.status = "failed"
        spec.last_error = f"spawn failed: {e}"
        return False
    spec.pid = proc.pid
    spec.pgid = proc.pid  # setsid → pgid == pid
    if not wait_for_port_listening(spec.port, timeout=20):
        spec.status = "failed"
        spec.last_error = f"port {spec.port} did not come up within 20s"
        # Kill the half-spawned process so we don't leak.
        kill_process_group(proc.pid)
        spec.pid = None
        spec.pgid = None
        return False
    spec.status = "running"
    spec.last_seen = time.time()
    spec.last_error = None
    return True


def stop_server(session_key: str, port: int) -> bool:
    """Manual stop button — pause this one spec without touching others."""
    with _registry_lock:
        specs = _registry.get(session_key, [])
        for s in specs:
            if s.port == port:
                if s.status == "running":
                    return _pause_spec(s)
                return True
    return False


def stop_servers_on_port(port: int) -> dict:
    """Kill ANY spec listening on ``port``, across all sessions.

    PR-008 — the Panel preview locks port 5173; when the user opens Live
    mode the UI calls this so a stale runtime from a prior session can't
    serve into the new preview. Idempotent: returns the list of specs
    that were paused (may be empty when nothing was registered on the
    port). Best-effort kill of an orphan listener (no spec, but the port
    is bound) is reported via ``orphan_killed`` so callers can log it.
    """
    stopped: list[dict] = []
    with _registry_lock:
        for specs in _registry.values():
            for s in specs:
                if s.port == port and s.status == "running":
                    _pause_spec(s)
                    stopped.append(_spec_to_dict(s))

    # Orphan: the port is still listening but isn't in our registry. Best-
    # effort PID lookup + SIGTERM so the new Live mode gets a clean port.
    orphan_killed = False
    if is_port_listening(port):
        pid = find_pid_for_port(port)
        if pid is not None:
            pgid = find_pgid(pid)
            try:
                if pgid is not None:
                    kill_process_group(pgid)
                else:
                    os.kill(pid, signal.SIGTERM)
                orphan_killed = True
            except (ProcessLookupError, PermissionError):
                pass

    return {
        "port": port,
        "stopped": stopped,
        "orphan_killed": orphan_killed,
        "still_listening": is_port_listening(port),
    }


def _refresh_status(session_key: str) -> None:
    """Cheap probe — if a spec marked running has no listener, downgrade."""
    with _registry_lock:
        specs = _registry.get(session_key, [])
        for s in specs:
            if s.status == "running" and not is_port_listening(s.port):
                s.status = "paused"
                s.pid = None
                s.pgid = None


# ---------------------------------------------------------------------------
# Background poller — detects dev servers the agent's tool output didn't
# announce (background `&`, deferred prints, format we don't regex-match).
# ---------------------------------------------------------------------------

# Callable that pushes a dev_server.detected event to whichever WS client
# is wired to the given session_key. Set by the gateway at startup; left
# None when running in subprocess mode (PTY chat) — poller still updates
# the registry but doesn't emit live events.
DetectCallback = "Callable[[str, dict], None]"
_emit_callback: Optional[object] = None

# PR-007 — the poller doesn't see gateway state directly, so the gateway
# wires a lookup callback here at startup: session_key → vibe_project
# (or None). Used to backfill the project attribution for runtimes the
# poller discovers (background `&`, deferred prints, etc.). When unset
# the poller registers with vibe_project=None, which is correct for
# Panel / pre-PR-004 callers.
_project_lookup_callback: Optional[object] = None

# Snapshot of "ports we've already announced" so each poll iteration only
# reacts to NEW listeners. Reset when the active session changes.
_poller_known_ports: set[int] = set()
_poller_thread: Optional[threading.Thread] = None
_poller_stop = threading.Event()


def set_detect_callback(cb) -> None:
    """Gateway wires its own per-sid emit helper here so the poller can
    push `dev_server.detected` events to the right WS client. Called once
    at FastAPI startup. Subprocess-mode gateways skip this — poller still
    runs, registry still updates, just no live event."""
    global _emit_callback
    _emit_callback = cb


def set_project_lookup_callback(cb) -> None:
    """Gateway wires a ``session_key → vibe_project | None`` lookup here so
    the poller can attribute newly-discovered runtimes to the right Vibe
    Code project. Called once at FastAPI startup; subprocess-mode gateways
    skip this (poller registers vibe_project=None, harmless for Panel)."""
    global _project_lookup_callback
    _project_lookup_callback = cb


def start_poller(interval: float = 2.0) -> None:
    """Start the background /proc scan loop. Idempotent — second call is
    a no-op. Stopped automatically when the process exits (daemon thread)."""
    global _poller_thread
    if _poller_thread is not None and _poller_thread.is_alive():
        return
    _poller_stop.clear()
    _poller_thread = threading.Thread(
        target=_poll_loop,
        name="dev-server-poller",
        args=(interval,),
        daemon=True,
    )
    _poller_thread.start()
    _log.info("dev-server-poller started (interval=%.1fs)", interval)


def stop_poller() -> None:
    _poller_stop.set()


def _poll_loop(interval: float) -> None:
    """Every `interval` seconds:
      1. Scan /proc/net/tcp{,6} for LISTEN sockets.
      2. Skip reserved (dashboard, ENCM) and non-candidate ports.
      3. For ports we haven't seen before, register against the active
         session_key (if any) and emit `dev_server.detected`.
      4. For ports that disappeared from LISTEN, downgrade matching specs
         to "paused" so the iframe drops the URL.
    """
    global _poller_known_ports
    while not _poller_stop.is_set():
        try:
            ports = set(_scan_listen_ports().keys())
        except Exception as e:
            _log.warning("dev-server-poller scan failed: %s", e)
            ports = set()

        candidates = {p for p in ports if p not in _RESERVED_PORTS}
        active_key = get_active_session_key()

        # New listeners → register + emit
        new_ports = candidates - _poller_known_ports
        for port in new_ports:
            if active_key is None:
                continue
            # Don't double-register if a tool-output detection already
            # claimed this port for the active session.
            already = False
            with _registry_lock:
                for s in _registry.get(active_key, []):
                    if s.port == port and s.status == "running":
                        already = True
                        break
            if already:
                continue
            url = f"http://localhost:{port}/"
            # PR-007 — attribute poller-discovered runtimes to a project
            # when the gateway has registered a lookup callback.
            project = None
            if _project_lookup_callback is not None:
                try:
                    project = _project_lookup_callback(active_key)  # type: ignore[misc]
                except Exception as e:
                    _log.debug("project lookup callback failed: %s", e)
            spec = register_detected_url(active_key, port, url, vibe_project=project)
            if _emit_callback is not None:
                try:
                    _emit_callback(  # type: ignore[misc]
                        active_key,
                        {
                            "port": spec.port,
                            "url": spec.url,
                            "session_key": spec.session_key,
                            "status": spec.status,
                            "pid": spec.pid,
                            "source": "proc-poll",
                        },
                    )
                except Exception as e:
                    _log.debug("emit failed: %s", e)

        # Disappearing listeners → mark paused so iframe drops the URL
        gone_ports = _poller_known_ports - candidates
        for port in gone_ports:
            _downgrade_port(port)

        _poller_known_ports = candidates
        _poller_stop.wait(interval)


def _downgrade_port(port: int) -> None:
    """A port that was LISTEN last tick but isn't now → mark the matching
    running spec as paused (process exited, was killed, etc.). Emit so
    the iframe removes its URL."""
    with _registry_lock:
        for key, specs in _registry.items():
            for s in specs:
                if s.port == port and s.status == "running":
                    s.status = "paused"
                    s.pid = None
                    s.pgid = None
                    if _emit_callback is not None:
                        try:
                            _emit_callback(  # type: ignore[misc]
                                key,
                                {
                                    "port": s.port,
                                    "url": s.url,
                                    "session_key": s.session_key,
                                    "status": "paused",
                                    "source": "proc-poll",
                                },
                            )
                        except Exception:
                            pass

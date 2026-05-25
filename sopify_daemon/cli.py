"""CLI thin client — every subcommand is one authenticated HTTP call.

The CLI never reads YAML rule files itself, never touches sandboxd
directly, and never spawns reconciler logic. All it does is:

  1. Resolve the daemon's URL + bearer token from ``~/.sopify/config.yaml``
  2. Call ``/api/v1/...`` over HTTP
  3. Render JSON to stdout (pretty by default, ``--json`` for raw)

If the daemon isn't running, every command prints a hint to run
``sopify start``. No fallback path — the daemon is the single source
of truth.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Optional

import httpx

from . import config as daemon_config


def _client(*, timeout: float = 15.0) -> httpx.Client:
    """Build an httpx client targeting the local daemon."""
    cfg = daemon_config.load(create_if_missing=False)
    return httpx.Client(
        base_url=f"http://{cfg.bind}:{cfg.port}",
        timeout=timeout,
        headers={"Authorization": f"Bearer {cfg.token}"},
    )


def _print(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _err(msg: str, code: int = 1) -> int:
    print(f"sopify: {msg}", file=sys.stderr)
    return code


def _connection_error_hint() -> int:
    return _err(
        "daemon not reachable — start it with `sopify start` first "
        "(or check ~/.sopify/config.yaml for the right port)"
    )


# ── Lifecycle ───────────────────────────────────────────────────────────


def cmd_start(argv: list[str]) -> int:
    """Foreground daemon launch. Mirrors `jupyter lab` / `ollama serve` UX.

    Refuses to start if another sopify daemon is already running — would
    otherwise hit the uvicorn "address already in use" error after the
    config + PID file are touched, leaving the system in a half-state.
    """
    from . import app, paths as daemon_paths
    try:
        cfg = daemon_config.load(create_if_missing=True)
    except Exception as exc:  # noqa: BLE001
        return _err(f"config error: {exc}")

    # Refuse if a live daemon owns the port — friendlier than uvicorn's
    # OSError + cleaner than letting it half-init then crash.
    existing = _existing_daemon_pid(cfg.port)
    if existing is not None:
        return _err(
            f"daemon already running (pid={existing}) on {cfg.bind}:{cfg.port}\n"
            f"        run `sopify stop` first, or `kill -9 {existing}` if it's wedged"
        )

    print(
        f"sopify daemon → http://{cfg.bind}:{cfg.port}\n"
        f"  bearer token: ~/.sopify/config.yaml  (Authorization: Bearer …)\n"
        f"  rules dir   : {os.path.expanduser('~/.sopify/encm/rules/')}\n"
        f"  audit dir   : {os.path.expanduser('~/.sopify/encm/audit/')}\n"
        f"  pid file    : {daemon_paths.pid_file()}\n"
    )
    app.run()
    return 0


def cmd_stop(argv: list[str]) -> int:
    """SIGTERM the running daemon. Falls back to SIGKILL after 5s."""
    import signal
    import time
    from . import paths as daemon_paths
    try:
        cfg = daemon_config.load(create_if_missing=False)
    except FileNotFoundError:
        return _err("config not found — nothing to stop", code=0)

    pid = _existing_daemon_pid(cfg.port)
    if pid is None:
        # Cleanup stale pid file if any
        daemon_paths.pid_file().unlink(missing_ok=True)
        print("sopify: daemon not running")
        return 0

    print(f"sopify: stopping daemon (pid={pid}) …")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        daemon_paths.pid_file().unlink(missing_ok=True)
        print("sopify: process already gone")
        return 0
    except PermissionError:
        return _err(f"permission denied sending SIGTERM to pid {pid}")

    # Wait up to 5s for clean shutdown
    for _ in range(50):
        time.sleep(0.1)
        if _existing_daemon_pid(cfg.port) is None:
            print("sopify: stopped cleanly")
            return 0

    # Still alive → SIGKILL
    print(f"sopify: SIGTERM didn't take after 5s — sending SIGKILL")
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    daemon_paths.pid_file().unlink(missing_ok=True)
    return 0


def _existing_daemon_pid(port: int) -> int | None:
    """Find the PID owning ``port`` on 127.0.0.1, or read the pid file.

    Prefer reading from the PID file (fast); cross-check by probing the
    port to avoid trusting a stale pid file. If the pid file is missing
    but something is bound on the port, surface that PID via lsof so
    `sopify stop` can still clean up after a crash.
    """
    import subprocess
    from . import paths as daemon_paths
    pid_path = daemon_paths.pid_file()
    candidate: int | None = None
    if pid_path.exists():
        try:
            candidate = int(pid_path.read_text().strip())
        except (ValueError, OSError):
            candidate = None
    # Verify the PID still owns the port. lsof costs ~50ms — fine on a
    # control-plane command path.
    try:
        out = subprocess.check_output(
            ["lsof", "-nP", "-iTCP:" + str(port), "-sTCP:LISTEN", "-t"],
            text=True,
            timeout=2,
        ).strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return candidate if candidate and _pid_alive(candidate) else None
    if not out:
        return None
    pids = [int(p) for p in out.splitlines() if p.strip().isdigit()]
    if candidate and candidate in pids:
        return candidate
    return pids[0] if pids else None


def _pid_alive(pid: int) -> bool:
    """signal 0 = "does this PID exist?" without affecting it."""
    import signal
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def cmd_status(argv: list[str]) -> int:
    try:
        with _client() as c:
            r = c.get("/api/v1/status")
    except httpx.ConnectError:
        return _connection_error_hint()
    if r.status_code != 200:
        return _err(f"status {r.status_code}: {r.text}")
    _print(r.json())
    return 0


# ── Rules ───────────────────────────────────────────────────────────────


def cmd_rules(argv: list[str]) -> int:
    if not argv:
        return _err("usage: sopify rules <list|add|show|remove|disable> ...")
    sub = argv[0]
    rest = argv[1:]
    if sub == "list":
        return _rules_list(rest)
    if sub == "add":
        return _rules_add(rest)
    if sub == "show":
        return _rules_show(rest)
    if sub == "remove":
        return _rules_remove(rest)
    if sub == "disable":
        return _rules_disable(rest)
    return _err(f"unknown rules subcommand: {sub}")


def _rules_list(argv: list[str]) -> int:
    try:
        with _client() as c:
            r = c.get("/api/v1/rules")
    except httpx.ConnectError:
        return _connection_error_hint()
    if r.status_code != 200:
        return _err(f"list failed ({r.status_code}): {r.text}")
    _print(r.json())
    return 0


def _rules_add(argv: list[str]) -> int:
    """Usage: sopify rules add <name> --pattern <p> [--pattern <p2>]
    [--decision allow|deny] [--type domain|cidr|port]
    [--scope global|sandbox] [--sandbox-id <id>] [--ttl <sec>]"""
    if not argv:
        return _err(
            "usage: sopify rules add <name> --pattern <p> "
            "[--decision allow|deny] [--type domain|cidr|port] "
            "[--scope global|sandbox] [--sandbox-id <id>]"
        )
    name = argv[0]
    body: dict = {
        "name": name,
        "patterns": [],
        "decision": "allow",
        "rule_type": "domain",
        "scope": "global",
        "created_by": os.environ.get("USER", "user"),
    }
    i = 1
    while i < len(argv):
        flag = argv[i]
        if flag == "--pattern" and i + 1 < len(argv):
            body["patterns"].append(argv[i + 1])
            i += 2
        elif flag == "--decision" and i + 1 < len(argv):
            body["decision"] = argv[i + 1]
            i += 2
        elif flag == "--type" and i + 1 < len(argv):
            body["rule_type"] = argv[i + 1]
            i += 2
        elif flag == "--scope" and i + 1 < len(argv):
            body["scope"] = argv[i + 1]
            i += 2
        elif flag == "--sandbox-id" and i + 1 < len(argv):
            body["sandbox_id"] = argv[i + 1]
            i += 2
        elif flag == "--ttl" and i + 1 < len(argv):
            body["ttl_seconds"] = int(argv[i + 1])
            i += 2
        else:
            return _err(f"unknown flag: {flag!r}")
    if not body["patterns"]:
        return _err("at least one --pattern required")
    try:
        with _client() as c:
            r = c.post("/api/v1/rules", json=body)
    except httpx.ConnectError:
        return _connection_error_hint()
    if r.status_code >= 300:
        return _err(f"create failed ({r.status_code}): {r.text}")
    _print(r.json())
    return 0


def _rules_show(argv: list[str]) -> int:
    if not argv:
        return _err("usage: sopify rules show <name> [--scope global|sandbox] [--sandbox-id <id>]")
    name = argv[0]
    params: dict[str, str] = {}
    i = 1
    while i < len(argv):
        if argv[i] == "--scope" and i + 1 < len(argv):
            params["scope"] = argv[i + 1]; i += 2
        elif argv[i] == "--sandbox-id" and i + 1 < len(argv):
            params["sandbox_id"] = argv[i + 1]; i += 2
        else:
            i += 1
    try:
        with _client() as c:
            r = c.get(f"/api/v1/rules/{name}", params=params)
    except httpx.ConnectError:
        return _connection_error_hint()
    if r.status_code == 404:
        return _err(f"rule {name!r} not found", code=2)
    if r.status_code != 200:
        return _err(f"show failed ({r.status_code}): {r.text}")
    _print(r.json())
    return 0


def _rules_remove(argv: list[str]) -> int:
    if not argv:
        return _err("usage: sopify rules remove <name> [--scope ...] [--sandbox-id ...]")
    name = argv[0]
    params: dict[str, str] = {}
    i = 1
    while i < len(argv):
        if argv[i] == "--scope" and i + 1 < len(argv):
            params["scope"] = argv[i + 1]; i += 2
        elif argv[i] == "--sandbox-id" and i + 1 < len(argv):
            params["sandbox_id"] = argv[i + 1]; i += 2
        else:
            i += 1
    try:
        with _client() as c:
            r = c.delete(f"/api/v1/rules/{name}", params=params)
    except httpx.ConnectError:
        return _connection_error_hint()
    if r.status_code == 404:
        return _err(f"rule {name!r} not found", code=2)
    if r.status_code >= 300:
        return _err(f"remove failed ({r.status_code}): {r.text}")
    print(f"removed: {name}")
    return 0


def _rules_disable(argv: list[str]) -> int:
    if not argv:
        return _err("usage: sopify rules disable <name> [--scope ...] [--sandbox-id ...]")
    name = argv[0]
    params: dict[str, str] = {}
    i = 1
    while i < len(argv):
        if argv[i] == "--scope" and i + 1 < len(argv):
            params["scope"] = argv[i + 1]; i += 2
        elif argv[i] == "--sandbox-id" and i + 1 < len(argv):
            params["sandbox_id"] = argv[i + 1]; i += 2
        else:
            i += 1
    try:
        with _client() as c:
            r = c.post(f"/api/v1/rules/{name}/disable", params=params)
    except httpx.ConnectError:
        return _connection_error_hint()
    if r.status_code != 200:
        return _err(f"disable failed ({r.status_code}): {r.text}")
    _print(r.json())
    return 0


# ── Audit / reconcile / drift ───────────────────────────────────────────


def cmd_audit(argv: list[str]) -> int:
    """Usage: sopify audit [--since <ISO>] [--limit N] [--decision allow|deny] [--src <sandbox>]"""
    params: dict[str, str] = {}
    i = 0
    while i < len(argv):
        f = argv[i]
        if f == "--since" and i + 1 < len(argv):
            params["since"] = argv[i + 1]; i += 2
        elif f == "--limit" and i + 1 < len(argv):
            params["limit"] = argv[i + 1]; i += 2
        elif f == "--decision" and i + 1 < len(argv):
            params["decision"] = argv[i + 1]; i += 2
        elif f == "--src" and i + 1 < len(argv):
            params["src"] = argv[i + 1]; i += 2
        else:
            return _err(f"unknown flag: {f}")
    try:
        with _client() as c:
            r = c.get("/api/v1/audit", params=params)
    except httpx.ConnectError:
        return _connection_error_hint()
    if r.status_code != 200:
        return _err(f"audit query failed ({r.status_code}): {r.text}")
    _print(r.json())
    return 0


def cmd_reconcile(argv: list[str]) -> int:
    try:
        with _client(timeout=60.0) as c:
            r = c.post("/api/v1/reconcile")
    except httpx.ConnectError:
        return _connection_error_hint()
    if r.status_code != 200:
        return _err(f"reconcile failed ({r.status_code}): {r.text}")
    _print(r.json())
    return 0


def cmd_drift(argv: list[str]) -> int:
    try:
        with _client() as c:
            r = c.get("/api/v1/drift")
    except httpx.ConnectError:
        return _connection_error_hint()
    if r.status_code != 200:
        return _err(f"drift query failed ({r.status_code}): {r.text}")
    _print(r.json())
    return 0


# ── Router ──────────────────────────────────────────────────────────────


COMMANDS = {
    "start": cmd_start,
    "stop": cmd_stop,
    "status": cmd_status,
    "rules": cmd_rules,
    "audit": cmd_audit,
    "reconcile": cmd_reconcile,
    "drift": cmd_drift,
}


def dispatch(argv: list[str]) -> int:
    if not argv:
        return _err("usage: sopify <start|status|rules|audit|reconcile|drift> ...")
    cmd, rest = argv[0], argv[1:]
    fn = COMMANDS.get(cmd)
    if fn is None:
        return _err(f"unknown command: {cmd}")
    return fn(rest)

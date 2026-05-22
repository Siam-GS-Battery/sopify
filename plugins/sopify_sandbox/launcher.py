"""sopify-sandbox launcher.

Spawns `sopify-sandbox:latest`, forwards stdio, cleans up on exit.
The launcher runs on the HOST (it's what makes the sandbox exist); every
subsequent module that calls into here runs INSIDE the sandbox.

REQ traceability:
  REQ-1.2.1 — entire sopify runtime lives in container (host has launcher only)
  REQ-1.2.2 — launcher: spawn, mount, forward stdin/stdout/stderr
  REQ-1.2.3 — uses sopify-sandbox:latest image
  REQ-1.2.4 — `--rm` ensures cleanup on exit (no orphans)
  REQ-1.2.5 — cwd mounted to /workspace (rw)
  REQ-1.2.6 — auth.json mounted to /sopify-auth (ro)
  REQ-1.2.7 — settings.json mounted to /sopify-config (ro)
  REQ-1.2.8 — sessions/ mounted to /sopify-sessions (rw)
  REQ-1.3.* — --no-sandbox guard (dev role only, logged)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import List

SANDBOX_IMAGE = "sopify-sandbox:latest"
SANDBOX_NETWORK = "sopify-net"
WORKSPACE = "/workspace"


def _sopify_home() -> str:
    return os.environ.get("SOPIFY_HOME") or os.path.expanduser("~/.sopify")


def _role() -> str:
    """Read role from profile.json. Default = 'user'. REQ-6.3.1."""
    import json
    try:
        with open(os.path.join(_sopify_home(), "profile.json")) as f:
            return json.load(f).get("role", "user")
    except Exception:
        return "user"


def _emit_no_sandbox_event(reason: str) -> None:
    """REQ-1.3.2 — sandbox disabled must be OTel-logged with reason."""
    try:
        from importlib import import_module
        emit = import_module("plugins.sopify_otel.emit")  # type: ignore[attr-defined]
        emit.emit("tool_decision", decision="sandbox_disabled", reason=reason)
    except Exception:
        pass  # fire-and-forget (REQ-7.2.4)


def _build_docker_argv(argv: List[str]) -> List[str]:
    home = _sopify_home()
    cwd = os.getcwd()
    cmd = [
        "docker", "run", "--rm", "-i",
        "--network", SANDBOX_NETWORK,
        "--name", f"sopify-{os.getpid()}",
        "-v", f"{cwd}:{WORKSPACE}:rw",                         # REQ-1.2.5
        "-v", f"{home}/auth.json:/sopify-auth/auth.json:ro",   # REQ-1.2.6
        "-v", f"{home}/settings.json:/sopify-config/settings.json:ro",  # REQ-1.2.7
        "-v", f"{home}/sessions:/sopify-sessions:rw",          # REQ-1.2.8
        "-w", WORKSPACE,
        "-e", "SOPIFY_IN_SANDBOX=1",
    ]
    if sys.stdin.isatty():
        cmd.append("-t")
    cmd.append(SANDBOX_IMAGE)
    cmd.extend(argv)
    return cmd


def spawn(argv: List[str]) -> int:
    """Run argv inside the sandbox. Returns the exit code."""
    if "--no-sandbox" in argv:
        # REQ-1.3.1 — dev-role-only override.
        if _role() != "dev":
            # REQ-1.3.3 — role:user has no path to --no-sandbox.
            print(
                "sopify: --no-sandbox is restricted to dev role. "
                "Contact IT to escalate. (REQ-1.3.3)",
                file=sys.stderr,
            )
            return 13  # EACCES vibe
        argv = [a for a in argv if a != "--no-sandbox"]
        _emit_no_sandbox_event("dev override via --no-sandbox")
        # Fall through to direct exec of the Hermes CLI on host.
        hermes = shutil.which("hermes") or "hermes"
        return subprocess.call([hermes, *argv])

    if not shutil.which("docker"):
        print(
            "sopify: Docker is not installed on this host.\n"
            "        Install Docker and re-run `sopify install`.\n"
            "        Guide: https://docs.docker.com/engine/install/",
            file=sys.stderr,
        )
        return 127  # REQ-1.1.2 — clear error + guide

    cmd = _build_docker_argv(argv)
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        # REQ-1.2.4 — `--rm` handles cleanup; this just acknowledges Ctrl-C.
        return 130

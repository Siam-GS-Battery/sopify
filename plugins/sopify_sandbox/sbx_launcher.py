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


def spawn(argv: List[str], *, with_kit: bool = True,
          publish_ports: Optional[List[int]] = None) -> int:
    """Run argv inside an sbx microVM. Returns the exit code.

    Args:
      argv: command + args to run inside the sandbox (e.g. ["chat"]).
      with_kit: apply the sopify kit on first launch.
      publish_ports: port numbers to publish from sandbox to host (for dashboard).
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

    cwd = str(Path.cwd())
    app_root = str(_sopify_app_root())
    sandbox = _sandbox_name_for_cwd()

    # The kit applies on `sbx kit add` for an existing sandbox; for a
    # fresh one we ship it via the spec at first run by using `sbx create`
    # plus `sbx kit add` then `sbx exec`. Simpler path: use `sbx run shell`
    # with workspace mounts + post-create kit add.

    # Build the inner command: invoke /usr/local/bin/sopify (set up by the
    # kit's startup script) with the user's argv.
    inner_cmd = "/usr/local/bin/sopify " + " ".join(_shellquote(a) for a in argv)

    # Mount the sopify-app dir read-only as /workspaces/sopify-app so the
    # startup script can find it. The user's cwd becomes the primary
    # workspace (/workspaces/<basename>).
    sbx_argv = [
        SBX_BINARY, "run",
        "shell",
        cwd,
        f"{app_root}:ro",
    ]

    # Port publishing for the dashboard.
    if publish_ports:
        for p in publish_ports:
            sbx_argv.extend(["--publish", f"{p}:{p}"])

    # Sandbox name so subsequent runs reuse the same microVM.
    sbx_argv.extend(["--name", sandbox])

    # Pass the actual command via `--` separator.
    sbx_argv.extend(["--", "-c", inner_cmd])

    try:
        # Apply the kit once (idempotent: sbx skips if already applied).
        if with_kit and _kit_path().exists():
            subprocess.run(
                [SBX_BINARY, "kit", "add", sandbox, str(_kit_path())],
                capture_output=True, text=True, timeout=30,
            )  # ignore errors — first-time sandboxes don't exist yet
        return subprocess.call(sbx_argv)
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
        v = subprocess.check_output([SBX_BINARY, "version"], text=True, timeout=1)
        for line in v.splitlines():
            if "Client Version" in line:
                return f"sbx OK ({line.split(':',1)[1].strip().split()[0]})"
        return "sbx OK"
    except Exception as exc:
        return f"sbx error: {exc}"

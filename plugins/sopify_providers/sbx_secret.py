"""Thin wrapper around the `sbx secret` CLI.

The sbx (Docker Sandboxes) secret store lets the MCP gateway proxy
substitute real API keys at outbound-request time, so sandboxed code
never sees the raw credential. Sopify writes to both stores from the
dashboard:
  - `~/.hermes/.env` (always) — for local Hermes calls outside the
    sandbox, and as a fallback when sbx isn't available
  - sbx secret store (when sbx is on PATH and the provider has a
    matching service) — the canonical path for sandbox-routed traffic

Subprocess calls never put the key on the command line; we pipe it
through stdin so it can't show up in shell history or `ps` output.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

_SBX_BIN = "sbx"
_TIMEOUT = 10.0


def is_available() -> bool:
    """True only when the sbx CLI is on PATH AND we're running on the host.

    Inside the microVM (SOPIFY_IN_SANDBOX=1) the sbx binary doesn't exist —
    sbx is a host-side controller, not a sandbox-resident tool. Calling
    set/rm from inside the sandbox would always fail; this guard lets the
    web API short-circuit cleanly with `sbx_available=False` so the UI can
    say "stored in .env (sync from host to also store in sbx)".
    """
    if os.environ.get("SOPIFY_IN_SANDBOX") == "1":
        return False
    return shutil.which(_SBX_BIN) is not None


def set_secret(service: str, value: str) -> tuple[bool, str]:
    """Pipe `value` to `sbx secret set -g <service> --force` via stdin.

    Returns (ok, error_message). On success error_message is "".
    """
    if not is_available():
        return False, "sbx CLI not installed"
    if not value:
        return False, "empty value"
    try:
        r = subprocess.run(
            [_SBX_BIN, "secret", "set", "-g", service, "--force"],
            input=value,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, "sbx secret set timed out"
    except Exception as exc:
        return False, f"sbx secret set failed: {exc}"
    if r.returncode != 0:
        # stderr typically has a one-line message like "service not found".
        err = (r.stderr or r.stdout or "").strip().splitlines()
        msg = err[0] if err else f"exit {r.returncode}"
        return False, msg
    return True, ""


def remove_secret(service: str) -> tuple[bool, str]:
    """Run `sbx secret rm -g <service>`. Returns (ok, error)."""
    if not is_available():
        return False, "sbx CLI not installed"
    try:
        r = subprocess.run(
            [_SBX_BIN, "secret", "rm", "-g", service],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, "sbx secret rm timed out"
    except Exception as exc:
        return False, f"sbx secret rm failed: {exc}"
    if r.returncode != 0:
        err = (r.stderr or "").strip().splitlines()
        msg = err[0] if err else f"exit {r.returncode}"
        return False, msg
    return True, ""


def list_services() -> set[str]:
    """Parse `sbx secret ls` and return the set of services that have a
    global secret stored. Returns the empty set if sbx is unavailable or
    the output can't be parsed (we never raise — the caller still has
    `~/.hermes/.env` as ground truth)."""
    if not is_available():
        return set()
    try:
        r = subprocess.run(
            [_SBX_BIN, "secret", "ls"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        logger.debug("sbx secret ls failed: %s", exc)
        return set()
    if r.returncode != 0:
        return set()

    # Output format (no public --format flag, so parse the table):
    #   SCOPE     SERVICE     ...
    #   global    anthropic   ...
    #   sandbox   openai      ...
    out: set[str] = set()
    for raw in r.stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith(("SCOPE", "No secrets")):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0].lower() == "global":
            out.add(parts[1].lower())
    return out

"""TUI dialogs — kept terminal-only (no Ink dep) for testability.

REQ-10.3 — dangerous-command confirmation has visible warning.
REQ-10.4 — network-permission dialog: domain + reason + Allow/Deny choices.
REQ-10.6 — Thai display: we always emit UTF-8; tests cover Thai chars.
"""
from __future__ import annotations

import sys
from typing import Optional


RED = "\x1b[31m"
YELLOW = "\x1b[33m"
BOLD = "\x1b[1m"
RESET = "\x1b[0m"

# When false (set by tests / non-TTY), strip ANSI escape codes.
COLOR = sys.stdout.isatty()


def _wrap(color: str, s: str) -> str:
    if not COLOR:
        return s
    return f"{color}{s}{RESET}"


def _input(prompt: str) -> str:
    """Indirected so tests can monkeypatch."""
    try:
        return input(prompt)
    except EOFError:
        return ""


def confirm_destructive(command: str, reason: str) -> bool:
    """REQ-10.3 + REQ-6.2.3 dev-confirm dialog."""
    print()
    print(_wrap(RED + BOLD, "⚠  DESTRUCTIVE COMMAND — DEV CONFIRMATION"))
    print(_wrap(YELLOW, f"   Reason: {reason}"))
    print(f"   Command: {command}")
    print()
    ans = _input("Execute? [y/N]: ").strip().lower()
    return ans in ("y", "yes")


def ask_network_permission(host: str, reason: str = "") -> str:
    """REQ-10.4 — Allow once / Allow always / Deny.

    Returns: 'once' | 'always' | 'deny'.
    """
    print()
    print(_wrap(BOLD, "🌐  Network permission requested"))
    print(f"   Domain: {host}")
    if reason:
        print(f"   Reason: {reason}")
    print("   [1] Allow once")
    print("   [2] Allow always")
    print("   [3] Deny")
    ans = _input("Choice [1/2/3]: ").strip()
    return {"1": "once", "2": "always", "3": "deny"}.get(ans, "deny")


def confirm_step(tool_name: str, args: dict, explanation: str) -> tuple[str, Optional[dict]]:
    """REQ-5.1.3 / REQ-10.3 — code-with-you four-option dialog."""
    print()
    print(_wrap(BOLD, "👣  Next step"))
    print(f"   Tool: {tool_name}")
    print(f"   Args: {args}")
    print(f"   Plan: {explanation}")
    print("   [e] Execute")
    print("   [s] Skip")
    print("   [m] Modify before execute")
    print("   [x] Stop session")
    ans = _input("Choice [e/s/m/x]: ").strip().lower()
    if ans == "e":
        return "execute", None
    if ans == "s":
        return "skip", None
    if ans == "m":
        # very small inline modification — replace 'command' or 'path'.
        new = _input("   Enter modified arg (key=value): ").strip()
        if "=" in new:
            k, _, v = new.partition("=")
            updated = dict(args)
            updated[k.strip()] = v.strip()
            return "modify", updated
        return "execute", None  # malformed → just execute
    if ans == "x":
        return "stop", None
    return "skip", None

"""Egress network policy.

The sandbox container uses `sopify-net` (a custom bridge — REQ-1.2.1). On every
attempted outbound connection by an AI tool (e.g. fetch_url, web_search), this
module evaluates the destination against:

  1. IT-managed whitelist from ~/.sopify/settings.json `allowed_domains`
  2. The plugin's static defaults (Anthropic, OTel collector)
  3. User-added entries (Allow-always) persisted to network-policy.json

REQ traceability:
  REQ-1.2.2 — default whitelist (Anthropic + OTel)
  REQ-1.2.3 — new domain triggers Allow/Deny dialog
  REQ-1.2.4 — dialog options: Allow once / Allow always / Deny
  REQ-1.2.5 — Allow always persists to network-policy.json
  REQ-1.2.6 — IT pre-approval via managed settings
  REQ-1.2.7 — Deny emits OTel tool_decision (blocked)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Set, Tuple
from urllib.parse import urlparse

DEFAULTS = {"api.anthropic.com", "otel-collector.gsbattery.local"}


@dataclass
class Decision:
    allow: bool
    reason: str
    persist: bool = False  # True if user picked "Allow always"


def _sopify_home() -> str:
    return os.environ.get("SOPIFY_HOME") or os.path.expanduser("~/.sopify")


def _load_policy() -> Tuple[Set[str], Set[str]]:
    """Return (whitelist, user_added)."""
    f = os.path.join(_sopify_home(), "network-policy.json")
    if not os.path.exists(f):
        return set(DEFAULTS), set()
    try:
        data = json.loads(open(f).read())
    except Exception:
        return set(DEFAULTS), set()
    whitelist = set(data.get("whitelist", []) or [])
    user_added = set(data.get("user_added", []) or [])
    return whitelist or set(DEFAULTS), user_added


def _load_managed_allowed() -> Set[str]:
    """REQ-1.2.6 / REQ-9.1.2 — IT-pushed allowed_domains in settings.json."""
    f = os.path.join(_sopify_home(), "settings.json")
    if not os.path.exists(f):
        return set()
    try:
        return set(json.loads(open(f).read()).get("allowed_domains", []) or [])
    except Exception:
        return set()


def _host_of(url_or_host: str) -> str:
    if "://" in url_or_host:
        return urlparse(url_or_host).hostname or ""
    return url_or_host.split(":", 1)[0].lower()


def evaluate(url_or_host: str, ask_user=None) -> Decision:
    """Return Decision for a destination.

    `ask_user(host) -> "once"|"always"|"deny"` is injected so this module
    stays UI-agnostic. In production it's a TUI dialog (sopify-tui); in tests
    it's a stub.
    """
    host = _host_of(url_or_host)
    if not host:
        return Decision(allow=False, reason="empty host")
    whitelist, user_added = _load_policy()
    managed = _load_managed_allowed()
    allowed = whitelist | user_added | managed
    if host in allowed or any(host.endswith("." + d) for d in allowed):
        return Decision(allow=True, reason="whitelisted")

    if ask_user is None:
        # No UI available — default-deny (safer than default-allow).
        return Decision(allow=False, reason="not whitelisted and no UI to ask")

    choice = ask_user(host)
    if choice == "deny":
        return Decision(allow=False, reason="user denied")
    if choice == "once":
        return Decision(allow=True, reason="user allowed once")
    if choice == "always":
        return Decision(allow=True, reason="user allowed always", persist=True)
    return Decision(allow=False, reason=f"unknown choice {choice!r}")


def persist_allow_always(host: str) -> None:
    """REQ-1.2.5 — write user_added entry."""
    f = os.path.join(_sopify_home(), "network-policy.json")
    try:
        data = json.loads(open(f).read()) if os.path.exists(f) else {}
    except Exception:
        data = {}
    data.setdefault("user_added", [])
    if host not in data["user_added"]:
        data["user_added"].append(host)
    data.setdefault("whitelist", list(DEFAULTS))
    data["version"] = 1
    open(f, "w").write(json.dumps(data, indent=2))

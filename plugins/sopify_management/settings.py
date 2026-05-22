"""IT-managed settings.

REQ-9.1.1 — file at 0444 (user can read, not write).
REQ-9.1.2 — keys: provider_chain, otel_endpoint, allowed_domains,
            daily_token_budgets, log_user_prompts, sandbox_enabled.
REQ-9.1.3 — settings change picked up by next session without restart
            (we use mtime + reload broadcast).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

DEFAULTS: Dict[str, Any] = {
    "provider_chain": ["anthropic", "openrouter"],
    "otel_endpoint": "",
    "allowed_domains": [],
    "daily_token_budgets": {"living": 300_000, "vibe": 200_000,
                            "code-with-you": 50_000},
    "log_user_prompts": False,
    "sandbox_enabled": True,
    "org_id": "gsbattery",
    "phase": 1,
}

# Subscribers — `reload_router`, `reload_otel_settings`, etc.
_subscribers: List[Callable[[Dict[str, Any]], None]] = []
_mtime_seen: float = 0.0
_lock = threading.Lock()


def settings_path() -> Path:
    home = os.environ.get("SOPIFY_HOME") or os.path.expanduser("~/.sopify")
    return Path(home) / "settings.json"


def load() -> Dict[str, Any]:
    p = settings_path()
    if not p.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(p.read_text())
    except Exception:
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update(data or {})
    return merged


def write_managed(data: Dict[str, Any]) -> None:
    """Used by `sopify admin set-setting`. Forces mode 0444."""
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.chmod(0o444)  # REQ-9.1.1
    tmp.replace(p)
    broadcast()


def subscribe(fn: Callable[[Dict[str, Any]], None]) -> None:
    _subscribers.append(fn)


def broadcast() -> None:
    data = load()
    for fn in list(_subscribers):
        try:
            fn(data)
        except Exception:
            pass


def poll_for_changes(interval_seconds: int = 5) -> None:
    """REQ-9.1.3 — pick up changes mid-session via mtime polling."""
    global _mtime_seen

    def loop():
        global _mtime_seen
        while True:
            p = settings_path()
            if p.exists():
                m = p.stat().st_mtime
                with _lock:
                    if m != _mtime_seen:
                        _mtime_seen = m
                        broadcast()
            time.sleep(interval_seconds)

    t = threading.Thread(target=loop, name="sopify-settings-poll", daemon=True)
    t.start()

"""TUI footer — mode badge, provider/quota, sandbox status.

REQ-10.1 — show active mode, provider, quota remaining, session info.
REQ-2.1.5 — provider + quota always visible.
REQ-10.8 — `/status` extended version.
"""
from __future__ import annotations

from typing import Dict


def render() -> str:
    parts: Dict[str, str] = {}

    try:
        from importlib import import_module
        modes = import_module("plugins.sopify_modes")
        parts["mode"] = modes.active_mode()
    except Exception:
        parts["mode"] = "chat"

    try:
        from importlib import import_module
        providers = import_module("plugins.sopify_providers")
        parts["provider"] = providers.ROUTER.status_summary()
    except Exception:
        parts["provider"] = "?"

    try:
        from importlib import import_module
        q = import_module("plugins.sopify_management.quota")
        used = q.usage("anthropic")  # primary provider
        budget = q._budget("anthropic")
        if budget:
            pct = int(used * 100 / budget)
            parts["quota"] = f"{used:,}/{budget:,} ({pct}%)"
    except Exception:
        parts["quota"] = "?"

    parts["sandbox"] = "ON" if _sandbox_on() else "OFF"

    return " | ".join(f"{k}={v}" for k, v in parts.items())


def _sandbox_on() -> bool:
    import os
    return bool(os.environ.get("SOPIFY_IN_SANDBOX"))


def render_status() -> str:
    """REQ-10.8 — `/status` shows everything."""
    lines = ["sopify status"]
    lines.append(f"  {render()}")
    try:
        from importlib import import_module
        living = import_module("plugins.sopify_modes.living")
        s = living.status()
        lines.append(f"  living: running={s.running} pid={s.pid} uptime={s.uptime_seconds}s")
    except Exception:
        pass
    return "\n".join(lines)

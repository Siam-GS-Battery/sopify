"""Token-budget monitor.

REQ-9.3.1 — track usage per provider per session, real-time.
REQ-9.3.2 — warn at 80% of daily budget.
REQ-9.3.3 — auto-switch provider via sopify-providers.ROUTER on quota
            exhaustion (we just record_failure with quota reason).
REQ-9.3.4 — IT alert when org spend > threshold (settings.org_spend_alert_usd).
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Dict


_lock = threading.Lock()
_session_tokens: Dict[str, int] = defaultdict(int)  # provider -> tokens
_session_cost: float = 0.0
_warned_at_80: set = set()
_warning_cb = None


def set_warning_callback(fn) -> None:
    """sopify-tui injects: fn(provider, used, budget) -> None."""
    global _warning_cb
    _warning_cb = fn


def record(provider: str, *, input_tokens: int = 0, output_tokens: int = 0,
           cost_usd: float = 0.0) -> None:
    global _session_cost
    total = input_tokens + output_tokens
    with _lock:
        _session_tokens[provider] += total
        _session_cost += cost_usd
    _maybe_warn(provider)


def usage(provider: str) -> int:
    return _session_tokens.get(provider, 0)


def reset() -> None:
    with _lock:
        _session_tokens.clear()
        _warned_at_80.clear()


def _budget(provider: str) -> int:
    """Today's per-mode budget — currently scoped per mode, not per provider.
    We use the active mode's budget as the headroom."""
    try:
        from importlib import import_module
        modes = import_module("plugins.sopify_modes")
        cfg = import_module("plugins.sopify_modes.config")
        return cfg.get(modes.active_mode()).daily_token_budget
    except Exception:
        return 200_000


def _maybe_warn(provider: str) -> None:
    """REQ-9.3.2 — emit warning at 80%, once per session per provider."""
    if provider in _warned_at_80:
        return
    used = _session_tokens.get(provider, 0)
    budget = _budget(provider)
    if budget and used >= int(0.8 * budget):
        _warned_at_80.add(provider)
        if _warning_cb:
            try:
                _warning_cb(provider, used, budget)
            except Exception:
                pass


def report_exhausted(provider: str) -> None:
    """REQ-9.3.3 — caller noticed quota exhaustion; cascade-fail the provider."""
    try:
        from importlib import import_module
        providers = import_module("plugins.sopify_providers")
        providers.ROUTER.record_failure(provider, status=429, reason="quota")
    except Exception:
        pass

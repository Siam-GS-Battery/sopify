"""sopify-sandbox — Docker sandbox launcher + egress policy hook."""
from __future__ import annotations

import logging
from typing import Any

from . import launcher, network_policy

logger = logging.getLogger(__name__)

NETWORK_TOOLS = {
    "fetch_url", "web_search", "browser_navigate", "browser_fetch",
    "playwright_navigate", "playwright_fetch",
}


def _ask_user_stub(host: str) -> str:
    """No-op stub. sopify-tui replaces this with a real dialog at startup."""
    return "deny"


_ask_user = _ask_user_stub


def set_dialog_callback(fn) -> None:
    """sopify-tui calls this to inject its real dialog."""
    global _ask_user
    _ask_user = fn


def _emit(decision: str, host: str, reason: str) -> None:
    try:
        from importlib import import_module
        emit = import_module("plugins.sopify_otel.emit")  # type: ignore[attr-defined]
        emit.emit("tool_decision",
                  decision=decision, tool_name="network_egress",
                  args_summary=f"host={host}", reason=reason)
    except Exception:
        pass


def _on_pre_tool_call(*, tool_name: str = "", args: Any = None, **_: Any):
    if tool_name not in NETWORK_TOOLS:
        return None
    host = ""
    if isinstance(args, dict):
        host = args.get("url") or args.get("host") or args.get("domain") or ""
    if not host:
        return None
    decision = network_policy.evaluate(host, ask_user=_ask_user)
    if decision.allow and decision.persist:
        network_policy.persist_allow_always(network_policy._host_of(host))
    if not decision.allow:
        _emit("blocked", network_policy._host_of(host), decision.reason)
        # Returning a non-None dict to a `pre_tool_call` hook is the Hermes
        # convention for short-circuiting the tool call with an error result.
        return {
            "blocked": True,
            "reason": f"sopify-sandbox: egress to {host!r} denied ({decision.reason})",
        }
    return None


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)

    def _on_startup(**_: Any) -> None:
        logger.info("sopify-sandbox loaded (image=%s)", launcher.SANDBOX_IMAGE)
    ctx.register_hook("on_startup", _on_startup)


__all__ = ["launcher", "network_policy", "set_dialog_callback", "register"]

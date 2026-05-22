"""sopify-modes — three slash commands.

Provides /living, /vibe, /code-with-you. Each command:
  1. Activates a `ModeProfile` (config.py).
  2. Tells sopify-otel the current mode (so events carry sopify_mode).
  3. Asks sopify-skills to inject the right bundles.
  4. Wires mode-specific guards (e.g. /code-with-you confirm-every-step).
"""
from __future__ import annotations

import logging
from typing import Any

from . import code_with_you, config, living, vibe

logger = logging.getLogger(__name__)

_active_mode: str = "chat"


def active_mode() -> str:
    return _active_mode


def _activate(mode: str) -> dict:
    global _active_mode
    _active_mode = mode
    profile = config.get(mode)
    # Tell sopify-otel.
    try:
        from importlib import import_module
        emit = import_module("plugins.sopify_otel.emit")  # type: ignore[attr-defined]
        emit.set_mode(mode)
    except Exception:
        pass
    return {
        "mode": mode,
        "profile": {
            "daily_token_budget": profile.daily_token_budget,
            "deny_list_level": profile.deny_list_level,
            "parallel_tool_execution": profile.parallel_tool_execution,
            "confirm_every_step": profile.confirm_every_step,
        },
    }


def _on_slash_command(*, command: str = "", args: str = "", **_: Any):
    """Sopify hands us /<command> <args>. Return a dict to short-circuit."""
    cmd = command.lstrip("/")
    if cmd in ("living", "vibe", "code-with-you"):
        result = _activate(cmd)
        result["render"] = (
            f"Activated mode: {cmd}\n"
            f"  token budget: {result['profile']['daily_token_budget']}\n"
            f"  deny-list:    {result['profile']['deny_list_level']}\n"
            f"  parallel:     {result['profile']['parallel_tool_execution']}\n"
            f"  confirm-step: {result['profile']['confirm_every_step']}"
        )
        return result
    if cmd == "living" and args.strip() == "status":
        s = living.status()
        return {"render": f"living: running={s.running} pid={s.pid} uptime={s.uptime_seconds}s"}
    if cmd == "living" and args.strip() == "stop":
        ok = living.stop()
        return {"render": "living: stopped" if ok else "living: not running"}
    return None


def _on_pre_tool_call(*, tool_name: str = "", args: Any = None, **_: Any):
    """Mode-specific guards.

    /code-with-you (REQ-5.1.1) — confirm every tool call.
    """
    if _active_mode == "code-with-you":
        return code_with_you.gate(tool_name, args)
    return None


def register(ctx) -> None:
    ctx.register_hook("on_slash_command", _on_slash_command)
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)


__all__ = ["config", "living", "vibe", "code_with_you",
           "active_mode", "register"]

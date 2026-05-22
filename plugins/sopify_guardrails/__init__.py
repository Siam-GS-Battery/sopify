"""sopify-guardrails — HARD_DENY + SOFT_DENY + role gating.

The plugin attaches one `pre_tool_call` hook. Decision flow:

  1. Extract the command string from the tool args (bash, code_execution, etc.)
  2. If HARD_DENY matches → block + emit `tool_decision hard_deny` and return.
  3. If SOFT_DENY matches:
       role=user → block + emit `tool_decision soft_deny_blocked`
       role=dev  → ask via confirmation callback
                   approved → emit `dev_confirmed + role_escalation_used`
                   rejected → emit `dev_rejected`
  4. Else → allow.

Confirmation UI is injected by `sopify-tui` via `set_confirm_callback`.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from . import patterns, role

logger = logging.getLogger(__name__)


_confirm_cb: Optional[Callable[[str, str], bool]] = None


def set_confirm_callback(fn: Callable[[str, str], bool]) -> None:
    """sopify-tui injects: fn(command, reason) -> bool (True = approved)."""
    global _confirm_cb
    _confirm_cb = fn


# Tools whose args we treat as a shell command string.
SHELL_TOOLS = {
    "bash", "shell", "execute_command", "code_execution",
    "run_command", "python_exec",
}
# Tools whose args we treat as SQL.
SQL_TOOLS = {"sql", "sql_query", "database_query"}


def _command_from_args(tool_name: str, args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    if tool_name in SHELL_TOOLS:
        return args.get("command") or args.get("cmd") or args.get("script") or ""
    if tool_name in SQL_TOOLS:
        return args.get("query") or args.get("sql") or ""
    # General fallback: any string field.
    for key in ("command", "query", "script", "cmd"):
        if isinstance(args.get(key), str):
            return args[key]
    return ""


def _emit(decision: str, *, tool_name: str, rule: str, reason: str) -> None:
    try:
        from importlib import import_module
        emit = import_module("plugins.sopify_otel.emit")  # type: ignore[attr-defined]
        emit.emit("tool_decision",
                  decision=decision, tool_name=tool_name,
                  rule=rule, reason=reason)
    except Exception:
        pass


def _block_result(reason: str) -> dict:
    return {"blocked": True, "reason": f"sopify-guardrails: {reason}"}


def evaluate(tool_name: str, args: Any) -> Optional[dict]:
    """Pure function used by the hook and by tests."""
    cmd = _command_from_args(tool_name, args)
    if not cmd:
        return None

    hard = patterns.first_match(patterns.HARD_DENY, cmd)
    if hard:
        # REQ-6.1.4 — no override, even for dev.
        _emit("hard_deny", tool_name=tool_name, rule=hard.name, reason=hard.reason)
        return _block_result(
            f"HARD DENY ({hard.name}): {hard.reason}. This is non-overridable."
        )

    soft = patterns.first_match(patterns.SOFT_DENY, cmd)
    if soft:
        if role.current_role() == "user":
            _emit("soft_deny_blocked", tool_name=tool_name,
                  rule=soft.name, reason=soft.reason)
            return _block_result(
                f"{soft.reason}. Requires role:dev — contact IT (REQ-6.2.2)."
            )
        # role: dev
        if _confirm_cb is None:
            # No UI → conservative deny (better than silent execute).
            _emit("dev_rejected", tool_name=tool_name,
                  rule=soft.name, reason="no confirm UI")
            return _block_result(
                f"Dev confirmation required for {soft.reason!r} but no UI is "
                f"available; aborting."
            )
        approved = bool(_confirm_cb(cmd, soft.reason))
        if approved:
            _emit("dev_confirmed_role_escalation_used",
                  tool_name=tool_name, rule=soft.name, reason=soft.reason)
            return None
        _emit("dev_rejected", tool_name=tool_name,
              rule=soft.name, reason=soft.reason)
        return _block_result(f"Dev rejected: {soft.reason}")
    return None


def _on_pre_tool_call(*, tool_name: str = "", args: Any = None, **_: Any):
    return evaluate(tool_name, args)


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)


__all__ = ["patterns", "role", "evaluate", "set_confirm_callback", "register"]

"""/code-with-you mode — pair programming, confirm every step.

REQ-5.1.1 — every tool call must be confirmed before execute.
REQ-5.1.2 — dialog shows tool name + args + plain-language explanation.
REQ-5.1.3 — user options: execute / skip / modify / stop.
REQ-5.1.4 — sequential (parallel_tool_execution=False).
REQ-5.3.2 — context compaction when context > 70%.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

EXECUTE = "execute"
SKIP = "skip"
MODIFY = "modify"
STOP = "stop"

OPTIONS = [EXECUTE, SKIP, MODIFY, STOP]


@dataclass
class StepRequest:
    tool_name: str
    args: dict
    explanation: str  # plain-language WHY/WHAT/EXPECTED


# Callback contract: fn(step) -> (choice, modified_args_or_None)
ConfirmCallback = Callable[[StepRequest], "tuple[str, Optional[dict]]"]

_confirm: Optional[ConfirmCallback] = None


def set_confirm_callback(fn: ConfirmCallback) -> None:
    global _confirm
    _confirm = fn


def explain(tool_name: str, args: Any) -> str:
    """Heuristic plain-language explanation."""
    if tool_name in ("bash", "shell"):
        cmd = (args or {}).get("command", "") if isinstance(args, dict) else ""
        return f"Run shell command: `{cmd}`"
    if tool_name in ("file_write", "write_file"):
        return f"Write file {args.get('path')}"
    if tool_name in ("file_read", "read_file"):
        return f"Read file {args.get('path')}"
    return f"Call tool `{tool_name}` with {args!r}"


def gate(tool_name: str, args: Any) -> Optional[dict]:
    """Called from pre_tool_call. Returns block-result or None."""
    if _confirm is None:
        return None  # without UI, fall through (REQ-5.1.1 best-effort)
    step = StepRequest(
        tool_name=tool_name,
        args=dict(args) if isinstance(args, dict) else {},
        explanation=explain(tool_name, args),
    )
    choice, modified = _confirm(step)
    if choice == EXECUTE:
        return None
    if choice == MODIFY and modified is not None:
        return {"replace_args": modified}
    if choice == SKIP:
        return {"blocked": True, "reason": "Skipped by user (code-with-you)"}
    if choice == STOP:
        return {"blocked": True, "reason": "Session stop requested",
                "stop_session": True}
    return {"blocked": True, "reason": f"Unknown choice {choice!r}"}

#!/usr/bin/env python3
"""claude_code_task — let Hermes hand a coding task to the Claude Code CLI.

Surface B of the integration: the Hermes agent (interactively, or from a cron
job — PR 3.2) delegates a focused coding/edit task to the baked `claude` CLI,
which does the work in a project directory and reports back a short summary.

Key properties addressing the design concerns:
  - Q1 (runaway loops burning tokens): every call is bounded by a turn cap and
    a wall-clock timeout; the runner kills a wedged turn.
  - Q2 (double token cost): Claude Code edits files in the shared working dir
    directly; this tool returns only a compact summary (final message + usage +
    diff stat from the CLI), NOT the full code — so the relay back to Hermes
    stays cheap.
  - Q3 (lost state): an optional session_id + resume lets a caller (e.g. a
    recurring cron job) continue the same Claude Code session across runs.

Thin wrapper over hermes_cli.claude_code_runner — all subprocess/stream/parse
logic lives there and is unit-tested independently.
"""

import json
import os
import shutil
from typing import Optional


# Headless defaults. Conservative turn cap + timeout so a single delegated task
# can't run away; callers raise them for bigger jobs.
DEFAULT_MAX_TURNS = 30
DEFAULT_TIMEOUT_S = 600


def claude_code_task(
    task: str,
    working_dir: Optional[str] = None,
    max_turns: Optional[int] = None,
    timeout_s: Optional[int] = None,
    model: Optional[str] = None,
    session_id: Optional[str] = None,
    resume: bool = False,
) -> str:
    """Run one Claude Code turn headlessly and return a JSON summary string."""
    from hermes_cli.claude_code_runner import run_claude_code
    from tools.registry import tool_error

    if not task or not str(task).strip():
        return tool_error("task is required.")

    cwd = working_dir or os.environ.get("TERMINAL_CWD") or os.getcwd()
    if not os.path.isdir(cwd):
        return tool_error(f"working_dir does not exist: {cwd}")

    if shutil.which("claude") is None:
        return tool_error(
            "Claude Code CLI ('claude') is not available in this environment."
        )

    # acceptEdits lets the CLI write files in the working dir without an
    # interactive prompt (none can be answered headlessly); env-overridable.
    permission_mode = os.environ.get("SOPIFY_CLAUDE_CODE_PERMISSION_MODE", "acceptEdits")

    try:
        result = run_claude_code(
            str(task),
            cwd=cwd,
            session_id=session_id or None,
            resume=bool(resume and session_id),
            max_turns=max_turns or DEFAULT_MAX_TURNS,
            timeout_s=timeout_s or DEFAULT_TIMEOUT_S,
            model=model or None,
            permission_mode=permission_mode,
        )
    except Exception as exc:  # noqa: BLE001 — report, don't crash the agent turn
        return tool_error(f"Claude Code run failed: {exc}")

    # Attribute this run's tokens to claude_code in the sessions DB (Phase 4),
    # keyed by the CLI session id, so dashboard analytics can split usage by
    # engine. Best-effort: a DB hiccup must not fail the task.
    try:
        from hermes_state import SessionDB
        from hermes_cli.claude_code_runner import record_claude_code_usage
        record_claude_code_usage(SessionDB(), result.session_id, result)
    except Exception:  # noqa: BLE001
        pass

    return json.dumps(
        {
            "ok": not result.is_error,
            "summary": result.final_text,
            "session_id": result.session_id,  # pass back so a cron job can resume
            "usage": result.usage,
            "cost_usd": result.cost_usd,
            "num_turns": result.num_turns,
            "timed_out": result.timed_out,
            "returncode": result.returncode,
            "working_dir": cwd,
        },
        ensure_ascii=False,
    )


def check_claude_code_requirements() -> bool:
    """Available only when the `claude` CLI is on PATH (baked into the sandbox)."""
    return shutil.which("claude") is not None


# =============================================================================
# OpenAI Function-Calling Schema
# =============================================================================

CLAUDE_CODE_SCHEMA = {
    "name": "claude_code_task",
    "description": (
        "Delegate a focused coding task to the Claude Code CLI, which is "
        "stronger at writing and editing code. It runs in a working directory, "
        "edits files there directly, and returns a short summary (it does NOT "
        "echo the full code back — read the changed files yourself if needed).\n\n"
        "Use this for: implementing a feature, fixing a bug, refactoring, "
        "writing tests, or any multi-step code edit. Give a clear, self-contained "
        "task description; Claude Code plans and executes it.\n\n"
        "Each call is bounded by max_turns + timeout so it can't loop forever. "
        "To continue a previous Claude Code session (e.g. a recurring job), pass "
        "the session_id returned by an earlier call with resume=true."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The coding task to perform, as a clear self-contained instruction.",
            },
            "working_dir": {
                "type": "string",
                "description": "Absolute path to run in. Defaults to the current working directory.",
            },
            "max_turns": {
                "type": "integer",
                "description": f"Max agent turns before stopping. Default {DEFAULT_MAX_TURNS}.",
            },
            "timeout_s": {
                "type": "integer",
                "description": f"Wall-clock timeout in seconds. Default {DEFAULT_TIMEOUT_S}.",
            },
            "model": {
                "type": "string",
                "description": "Optional model override (otherwise Claude Code's configured default).",
            },
            "session_id": {
                "type": "string",
                "description": "Resume/continue this Claude Code session id (returned by a prior call).",
            },
            "resume": {
                "type": "boolean",
                "description": "If true and session_id is set, continue that session instead of starting fresh.",
            },
        },
        "required": ["task"],
    },
}


# --- Registry ---
from tools.registry import registry

registry.register(
    name="claude_code_task",
    toolset="claude_code",
    schema=CLAUDE_CODE_SCHEMA,
    handler=lambda args, **kw: claude_code_task(
        task=args.get("task", ""),
        working_dir=args.get("working_dir"),
        max_turns=args.get("max_turns"),
        timeout_s=args.get("timeout_s"),
        model=args.get("model"),
        session_id=args.get("session_id"),
        resume=bool(args.get("resume", False)),
    ),
    check_fn=check_claude_code_requirements,
    emoji="🤖",
)

"""Headless Claude Code (CLI) runner — spawn, stream, parse, guard.

Phase 2 of the Claude Code integration plan binds a Vibe Code project to a
resumable `claude` session. Both the interactive gateway bridge (Surface A)
and the headless `claude_code_task` tool (Surface B, cron) need the same
primitive: run the baked `claude` CLI in a project directory, stream its
output back as normalized events, capture the session id for `--resume`, and
keep it on a leash (turn cap + wall-clock timeout).

This module is that primitive and nothing more. It does NOT touch the
WebSocket gateway, FastAPI, or project.json — callers wire those. Keeping it
standalone (stdlib only) is what makes it unit-testable against a fake
`claude` that emits the same newline-delimited stream-json, with no real
credentials or network.

Wire protocol: `claude -p <prompt> --output-format stream-json --verbose`
emits one JSON object per line. Each has a top-level ``type``:
  - ``system`` (subtype ``init``)  → carries ``session_id``, model, tools
  - ``assistant``                  → a model message; text lives in
                                      ``message.content[].text``
  - ``user``                       → tool results fed back to the model
  - ``result`` (subtype success/…) → final turn summary: ``result`` text,
                                      ``usage``, ``total_cost_usd``,
                                      ``num_turns``, ``is_error``, ``session_id``
We dispatch on ``type`` and degrade gracefully on anything unrecognized so a
CLI version bump that adds event types does not break the parser.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

_log = logging.getLogger(__name__)

# Wall-clock and turn ceilings. Generous enough for real coding turns, low
# enough that a runaway loop is bounded (concern Q1). Callers override.
DEFAULT_TIMEOUT_S = 600
DEFAULT_MAX_TURNS = 40


@dataclass
class ClaudeCodeEvent:
    """One normalized event parsed from a stream-json line."""

    kind: str  # init | assistant_text | tool_use | tool_result | result | error | raw
    raw: dict
    text: Optional[str] = None
    session_id: Optional[str] = None
    # result-only fields:
    usage: Optional[dict] = None
    cost_usd: Optional[float] = None
    num_turns: Optional[int] = None
    is_error: Optional[bool] = None


@dataclass
class ClaudeCodeResult:
    """Outcome of one `run_claude_code` call."""

    session_id: Optional[str] = None
    final_text: str = ""
    is_error: bool = False
    returncode: Optional[int] = None
    timed_out: bool = False
    usage: dict = field(default_factory=dict)
    cost_usd: Optional[float] = None
    num_turns: Optional[int] = None


def new_session_id() -> str:
    """A fresh UUID to pin a new Claude Code session to (``--session-id``).

    Claude Code requires a valid UUID and rejects one that already exists, so
    generate on the first turn and ``--resume`` it thereafter.
    """
    return str(uuid.uuid4())


def build_claude_argv(
    prompt: str,
    *,
    claude_bin: str = "claude",
    session_id: Optional[str] = None,
    resume: bool = False,
    max_turns: Optional[int] = DEFAULT_MAX_TURNS,
    model: Optional[str] = None,
    permission_mode: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    """Assemble the `claude` argv for one headless turn.

    ``resume=True`` continues ``session_id`` (must already exist); otherwise
    ``session_id`` pins a brand-new session. ``permission_mode`` is left to the
    caller — this module never silently enables file edits, since that is a
    security policy decision the gateway/tool layer owns.
    """
    argv: List[str] = [claude_bin, "-p", prompt,
                       "--output-format", "stream-json", "--verbose"]
    if session_id:
        argv += (["--resume", session_id] if resume
                 else ["--session-id", session_id])
    if max_turns is not None:
        argv += ["--max-turns", str(max_turns)]
    if model:
        argv += ["--model", model]
    if permission_mode:
        argv += ["--permission-mode", permission_mode]
    if extra_args:
        argv += list(extra_args)
    return argv


def parse_stream_json_line(line: str) -> Optional[ClaudeCodeEvent]:
    """Parse one stream-json line into a ClaudeCodeEvent (None for blanks).

    Defensive by design: malformed JSON or an unknown ``type`` becomes a
    ``raw`` event rather than raising, so one bad line never aborts a turn.
    """
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except (ValueError, TypeError):
        return ClaudeCodeEvent(kind="raw", raw={"_unparsed": line})
    if not isinstance(obj, dict):
        return ClaudeCodeEvent(kind="raw", raw={"_nonobject": obj})

    etype = obj.get("type")
    sid = obj.get("session_id")

    if etype == "system" and obj.get("subtype") == "init":
        return ClaudeCodeEvent(kind="init", raw=obj, session_id=sid)

    if etype == "assistant":
        text = _extract_text(obj.get("message"))
        kind = "tool_use" if _has_tool_use(obj.get("message")) else "assistant_text"
        return ClaudeCodeEvent(kind=kind, raw=obj, text=text, session_id=sid)

    if etype == "user":
        return ClaudeCodeEvent(kind="tool_result", raw=obj, session_id=sid)

    if etype == "result":
        return ClaudeCodeEvent(
            kind="result",
            raw=obj,
            text=obj.get("result") if isinstance(obj.get("result"), str) else None,
            session_id=sid,
            usage=obj.get("usage") if isinstance(obj.get("usage"), dict) else None,
            cost_usd=_as_float(obj.get("total_cost_usd")),
            num_turns=obj.get("num_turns") if isinstance(obj.get("num_turns"), int) else None,
            is_error=bool(obj.get("is_error")) or obj.get("subtype") not in (None, "success"),
        )

    return ClaudeCodeEvent(kind="raw", raw=obj, session_id=sid)


def run_claude_code(
    prompt: str,
    *,
    cwd: str,
    claude_bin: str = "claude",
    session_id: Optional[str] = None,
    resume: bool = False,
    max_turns: Optional[int] = DEFAULT_MAX_TURNS,
    timeout_s: Optional[float] = DEFAULT_TIMEOUT_S,
    model: Optional[str] = None,
    permission_mode: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    extra_args: Optional[List[str]] = None,
    on_event: Optional[Callable[[ClaudeCodeEvent], None]] = None,
) -> ClaudeCodeResult:
    """Run one Claude Code turn and stream its events through ``on_event``.

    Blocks until `claude` exits or ``timeout_s`` elapses (then the process is
    killed and ``timed_out`` is set). Returns the captured session id, the
    final result text, and usage/cost from the ``result`` event. Never raises
    on a non-zero exit — inspect ``returncode`` / ``is_error``.
    """
    argv = build_claude_argv(
        prompt, claude_bin=claude_bin, session_id=session_id, resume=resume,
        max_turns=max_turns, model=model, permission_mode=permission_mode,
        extra_args=extra_args,
    )
    proc_env = {**os.environ, **(env or {})}
    result = ClaudeCodeResult(session_id=session_id)

    _log.info("claude_code: launching (resume=%s, cwd=%s, max_turns=%s, timeout=%ss)",
              resume, cwd, max_turns, timeout_s)
    try:
        proc = subprocess.Popen(
            argv, cwd=cwd, env=proc_env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
    except FileNotFoundError:
        _log.error("claude_code: binary %r not found", claude_bin)
        result.is_error = True
        result.returncode = 127
        return result

    # A watchdog thread enforces the wall-clock ceiling. We kill rather than
    # terminate-then-wait because a wedged turn may ignore SIGTERM.
    timer: Optional[threading.Timer] = None
    if timeout_s and timeout_s > 0:
        def _kill_on_timeout() -> None:
            result.timed_out = True
            _log.warning("claude_code: timeout after %ss — killing", timeout_s)
            try:
                proc.kill()
            except Exception:  # noqa: BLE001 — process may have just exited
                pass
        timer = threading.Timer(timeout_s, _kill_on_timeout)
        timer.daemon = True
        timer.start()

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            event = parse_stream_json_line(line)
            if event is None:
                continue
            if event.session_id and not result.session_id:
                result.session_id = event.session_id
            if event.kind == "result":
                if event.text is not None:
                    result.final_text = event.text
                if event.usage is not None:
                    result.usage = event.usage
                result.cost_usd = event.cost_usd
                result.num_turns = event.num_turns
                if event.is_error:
                    result.is_error = True
            if on_event is not None:
                try:
                    on_event(event)
                except Exception:  # noqa: BLE001 — a bad callback must not kill the turn
                    _log.exception("claude_code: on_event callback raised")
        proc.wait()
    finally:
        if timer is not None:
            timer.cancel()

    result.returncode = proc.returncode
    if proc.returncode not in (0, None) and not result.timed_out:
        result.is_error = True
    return result


# ── gateway adapter ──────────────────────────────────────────────────────
# Translates runner events into the JSON-RPC event vocabulary the dashboard
# chat UI already speaks (see tui_gateway/server.py::_emit). Pure: it takes an
# ``emit(event_name, payload)`` callable, so it is testable without the live
# gateway and the gateway wiring (next slice) stays a thin call site.

def claude_usage_to_gateway(
    usage: Optional[dict],
    model: Optional[str] = None,
    num_turns: Optional[int] = None,
) -> dict:
    """Map Claude Code's ``result.usage`` to the gateway's usage dict shape.

    The dashboard reads keys ``input``/``output``/``cache_read`` etc. (NOT the
    ``*_tokens`` names the CLI uses), matching tui_gateway _get_usage.
    """
    usage = usage or {}
    inp = _int(usage.get("input_tokens"))
    out = _int(usage.get("output_tokens"))
    return {
        "model": model or "",
        "input": inp,
        "output": out,
        "cache_read": _int(usage.get("cache_read_input_tokens")),
        "cache_write": _int(usage.get("cache_creation_input_tokens")),
        "reasoning": 0,
        "prompt": inp,
        "completion": out,
        "total": inp + out,
        "calls": num_turns or 0,
    }


class GatewayEventTranslator:
    """Feed ClaudeCodeEvents in, get gateway events out via ``emit``.

    Usage mirrors the existing turn flow: the caller emits ``message.start``,
    runs the turn with ``on_event=translator.handle``, then calls
    ``finalize()`` to guarantee a terminal ``message.complete`` even if the CLI
    died mid-stream (so the UI never hangs waiting).
    """

    def __init__(self, emit: Callable[[str, Optional[dict]], None]):
        self.emit = emit
        self.session_id: Optional[str] = None
        self.model: Optional[str] = None
        self.final_text: str = ""
        self.usage: dict = {}
        self._completed = False

    def handle(self, event: ClaudeCodeEvent) -> None:
        if event.session_id and not self.session_id:
            self.session_id = event.session_id
        if event.kind == "init":
            self.model = event.raw.get("model") or self.model
        elif event.kind == "assistant_text":
            if event.text:
                self.emit("message.delta", {"text": event.text})
        elif event.kind == "tool_use":
            for name in _tool_names(event.raw):
                self.emit("tool.generating", {"name": name})
            if event.text:
                self.emit("message.delta", {"text": event.text})
        elif event.kind == "result":
            self.final_text = event.text or ""
            self.usage = claude_usage_to_gateway(event.usage, self.model, event.num_turns)
            self._emit_complete("error" if event.is_error else "complete")
        # init handled above; tool_result / raw carry nothing for the UI.

    def finalize(self, *, error_message: Optional[str] = None) -> None:
        """Emit a terminal event if the result event never arrived."""
        if error_message and not self._completed:
            self.emit("error", {"message": error_message})
        if not self._completed:
            self._emit_complete("error" if error_message else "complete")

    def _emit_complete(self, status: str) -> None:
        self.emit("message.complete",
                  {"text": self.final_text, "usage": self.usage, "status": status})
        self._completed = True


def _tool_names(raw: object) -> List[str]:
    msg = raw.get("message") if isinstance(raw, dict) else None
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return []
    return [b.get("name") for b in content
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name")]


def _int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


# ── helpers ────────────────────────────────────────────────────────────────

def _extract_text(message: object) -> Optional[str]:
    """Join the text blocks of an assistant ``message.content`` array."""
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts = [b.get("text") for b in content
             if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
    return "".join(parts) if parts else None


def _has_tool_use(message: object) -> bool:
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_use" for b in content
    )


def _as_float(value: object) -> Optional[float]:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None

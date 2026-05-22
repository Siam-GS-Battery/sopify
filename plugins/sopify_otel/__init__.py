"""sopify-otel — emit 5 event types to OTel.

Hooks attach to Sopify's lifecycle; each hook just calls `emit.emit(...)`.
"""
from __future__ import annotations

import logging
from typing import Any

from . import emit, redact

logger = logging.getLogger(__name__)


def _on_user_prompt(*, prompt: str = "", **_: Any):
    emit.emit("user_prompt", prompt=prompt)


def _on_pre_api_request(*, model: str = "", provider: str = "", **_: Any):
    # We emit the request snapshot here; the response side fills in tokens.
    emit.emit("api_request_started", model=model, provider=provider)


def _on_post_api_request(*, model: str = "", provider: str = "",
                        input_tokens: int = 0, output_tokens: int = 0,
                        cost_usd: float = 0.0, latency_ms: int = 0, **_: Any):
    emit.emit("api_request",
              model=model, provider=provider,
              input_tokens=input_tokens, output_tokens=output_tokens,
              cost_usd=cost_usd, latency_ms=latency_ms)


def _on_post_tool_call(*, tool_name: str = "", args: Any = None,
                      success: bool = True, duration_ms: int = 0, **_: Any):
    summary = ""
    if isinstance(args, dict):
        try:
            import json as _j
            summary = _j.dumps(args, default=str)
        except Exception:
            summary = str(args)
    emit.emit("tool_result",
              tool_name=tool_name, success=success,
              duration_ms=duration_ms, args_summary=summary)


def _on_api_error(*, error_type: str = "", status_code: int = 0,
                 message: str = "", **_: Any):
    emit.emit("api_error",
              error_type=error_type, status_code=status_code, message=message)


def register(ctx) -> None:
    ctx.register_hook("user_prompt", _on_user_prompt)
    ctx.register_hook("pre_api_request", _on_pre_api_request)
    ctx.register_hook("post_api_request", _on_post_api_request)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("api_error", _on_api_error)


__all__ = ["emit", "redact", "register"]

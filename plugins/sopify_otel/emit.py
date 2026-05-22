"""OTel emitter — fire-and-forget.

REQ-7.1 — 5 event types with base fields (timestamp, session_id, user_email,
          org_id, sopify_mode).
REQ-7.2.4 — collector unreachable must NOT block; we use a daemon thread with
          a bounded queue and drop on overflow.
REQ-7.2.5 — endpoint must be a managed setting (read at startup from settings.json).
REQ-7.4.1 — user_prompt event only emits when settings.log_user_prompts == True.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import uuid
from typing import Any, Dict, Optional

from . import redact

logger = logging.getLogger(__name__)

QUEUE_MAX = 1000
DROP_COUNTER = {"dropped": 0}

_q: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=QUEUE_MAX)
_worker: Optional[threading.Thread] = None
_session_id = str(uuid.uuid4())
_current_mode = "chat"
_settings_cache: Optional[Dict[str, Any]] = None


# ---------- context setters ----------


def set_session_id(sid: str) -> None:
    global _session_id
    _session_id = sid


def set_mode(mode: str) -> None:
    """sopify-modes calls this when the user runs /vibe / /living / etc."""
    global _current_mode
    _current_mode = mode


# ---------- internal helpers ----------


def _sopify_home() -> str:
    return os.environ.get("SOPIFY_HOME") or os.path.expanduser("~/.sopify")


def _settings() -> Dict[str, Any]:
    global _settings_cache
    if _settings_cache is not None:
        return _settings_cache
    p = os.path.join(_sopify_home(), "settings.json")
    if not os.path.exists(p):
        _settings_cache = {}
        return _settings_cache
    try:
        _settings_cache = json.loads(open(p).read())
    except Exception:
        _settings_cache = {}
    return _settings_cache


def reload_settings() -> None:
    global _settings_cache
    _settings_cache = None


def _user_email() -> str:
    p = os.path.join(_sopify_home(), "profile.json")
    if os.path.exists(p):
        try:
            return json.loads(open(p).read()).get("user", "") or ""
        except Exception:
            pass
    return os.environ.get("USER", "") or ""


def _base_fields() -> Dict[str, Any]:
    """REQ-7.1.6 — every event gets these."""
    s = _settings()
    return {
        "timestamp": time.time(),
        "session_id": _session_id,
        "user_email": _user_email(),
        "org_id": s.get("org_id", "gsbattery"),
        "sopify_mode": _current_mode,
    }


# ---------- queueing & worker ----------


def _start_worker() -> None:
    global _worker
    if _worker and _worker.is_alive():
        return
    _worker = threading.Thread(target=_run_worker, name="sopify-otel", daemon=True)
    _worker.start()


def _otlp_endpoint() -> Optional[str]:
    return _settings().get("otel_endpoint") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")


def _run_worker() -> None:
    """Drain the queue. We try HTTP OTLP if `requests` is available; otherwise
    we just log and drop. The point of this module is the contract, not the
    transport."""
    try:
        import requests  # type: ignore
    except Exception:
        requests = None

    while True:
        event = _q.get()
        endpoint = _otlp_endpoint()
        if endpoint is None or requests is None:
            logger.debug("sopify-otel (no endpoint): %s", event)
            _q.task_done()
            continue
        try:
            requests.post(endpoint, json=event, timeout=2)
        except Exception as exc:
            logger.debug("sopify-otel send failed: %s", exc)
        finally:
            _q.task_done()


def _enqueue(event: Dict[str, Any]) -> None:
    try:
        _q.put_nowait(event)
    except queue.Full:
        DROP_COUNTER["dropped"] += 1  # REQ-12 metric target < 0.1%


# ---------- public API ----------


def emit(event_type: str, **fields: Any) -> None:
    """Single entry point. Fire-and-forget.

    Recognised event_type values match REQ-7.1:
      user_prompt | api_request | tool_result | tool_decision | api_error
    """
    _start_worker()
    settings = _settings()

    if event_type == "user_prompt" and not settings.get("log_user_prompts", False):
        # REQ-7.4.1 — opt-in only.
        return

    payload: Dict[str, Any] = dict(_base_fields())
    payload["event_type"] = event_type
    payload.update(fields)

    # Per-event field shaping + truncation.
    if event_type == "user_prompt" and "prompt" in payload:
        payload["prompt"] = str(payload["prompt"])[:2000]      # REQ-7.1.1
    if event_type == "tool_result" and "args_summary" in payload:
        payload["args_summary"] = str(payload["args_summary"])[:500]  # REQ-7.1.3

    # REQ-11.2 — redact secrets from every string leaf before send.
    payload = redact.redact_payload(payload)

    _enqueue(payload)

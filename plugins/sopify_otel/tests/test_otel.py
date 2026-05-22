"""Tests for sopify-otel."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _reload(monkeypatch, tmp_path, settings=None):
    monkeypatch.setenv("SOPIFY_HOME", str(tmp_path))
    if settings is not None:
        (tmp_path / "settings.json").write_text(json.dumps(settings))
    emit = importlib.import_module("plugins.sopify_otel.emit")
    return importlib.reload(emit)


def test_user_prompt_dropped_when_opt_out(tmp_path, monkeypatch):
    """REQ-7.4.1 — log_user_prompts off → user_prompt event is NOT enqueued."""
    emit = _reload(monkeypatch, tmp_path, settings={"log_user_prompts": False})
    before = emit._q.qsize()
    emit.emit("user_prompt", prompt="hello world")
    assert emit._q.qsize() == before  # nothing added


def test_user_prompt_truncated_to_2000(tmp_path, monkeypatch):
    emit = _reload(monkeypatch, tmp_path, settings={"log_user_prompts": True})
    emit.emit("user_prompt", prompt="x" * 5000)
    item = emit._q.get_nowait()
    assert len(item["prompt"]) == 2000


def test_api_key_redacted(tmp_path, monkeypatch):
    """REQ-11.2 — API keys never enter OTel payloads."""
    emit = _reload(monkeypatch, tmp_path, settings={"log_user_prompts": True})
    emit.emit("user_prompt",
              prompt="use sk-ant-1234567890abcdefghijklmnop to call API")
    item = emit._q.get_nowait()
    assert "sk-ant-" not in item["prompt"]
    assert "REDACTED" in item["prompt"]


def test_base_fields_present(tmp_path, monkeypatch):
    emit = _reload(monkeypatch, tmp_path, settings={"log_user_prompts": True})
    emit.set_mode("vibe")
    emit.emit("user_prompt", prompt="hi")
    item = emit._q.get_nowait()
    for field in ("timestamp", "session_id", "user_email", "org_id",
                  "sopify_mode", "event_type"):
        assert field in item
    assert item["sopify_mode"] == "vibe"


def test_tool_result_args_truncated_to_500(tmp_path, monkeypatch):
    emit = _reload(monkeypatch, tmp_path)
    emit.emit("tool_result", tool_name="bash",
              args_summary="A" * 2000, success=True, duration_ms=10)
    item = emit._q.get_nowait()
    assert len(item["args_summary"]) == 500


def test_drop_on_overflow(tmp_path, monkeypatch):
    """REQ-7.2.4 — never block. Overflow drops, increments counter."""
    emit = _reload(monkeypatch, tmp_path)
    # Disable the drain worker so the queue actually overflows deterministically.
    monkeypatch.setattr(emit, "_start_worker", lambda: None)
    emit.DROP_COUNTER["dropped"] = 0
    # Saturate queue.
    for _ in range(emit.QUEUE_MAX + 50):
        emit.emit("tool_decision", decision="auto_approved", tool_name="t")
    assert emit.DROP_COUNTER["dropped"] >= 1

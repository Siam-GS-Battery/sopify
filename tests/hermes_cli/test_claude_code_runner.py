"""Tests for hermes_cli.claude_code_runner.

Driven by a fake `claude` binary (a tiny Python script emitting the real
newline-delimited stream-json shape), so they run with no credentials, no
network, and no installed CLI. Runnable under pytest OR directly:

    python tests/hermes_cli/test_claude_code_runner.py
"""

from __future__ import annotations

import stat
import sys
import tempfile
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hermes_cli import claude_code_runner as ccr  # noqa: E402


def _write_fake_claude(dir_path: Path, body: str) -> str:
    """Drop an executable fake `claude` that runs `body` and return its path."""
    path = dir_path / "claude"
    path.write_text("#!/usr/bin/env python3\n" + textwrap.dedent(body))
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    return str(path)


# A successful turn: init (session_id) → assistant text → result (usage/cost).
_FAKE_SUCCESS = """
    import json, sys
    sid = "11111111-2222-3333-4444-555555555555"
    out = [
        {"type": "system", "subtype": "init", "session_id": sid, "model": "x", "tools": []},
        {"type": "assistant", "session_id": sid,
         "message": {"role": "assistant", "content": [{"type": "text", "text": "Hello "}]}},
        {"type": "assistant", "session_id": sid,
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "world"},
             {"type": "tool_use", "name": "Edit", "input": {}}]}},
        {"type": "result", "subtype": "success", "is_error": False, "session_id": sid,
         "result": "Done editing.", "num_turns": 2, "total_cost_usd": 0.0123,
         "usage": {"input_tokens": 100, "output_tokens": 40}},
    ]
    for o in out:
        print(json.dumps(o)); sys.stdout.flush()
"""


def test_build_argv_new_vs_resume():
    new = ccr.build_claude_argv("hi", session_id="abc", resume=False, max_turns=5)
    assert "--session-id" in new and "abc" in new and "--resume" not in new
    assert new[:2] == ["claude", "-p"] and "hi" in new
    assert "--output-format" in new and "stream-json" in new and "--verbose" in new
    assert "--max-turns" in new and "5" in new

    res = ccr.build_claude_argv("hi", session_id="abc", resume=True, max_turns=None)
    assert "--resume" in res and "abc" in res and "--session-id" not in res
    assert "--max-turns" not in res

    full = ccr.build_claude_argv("hi", model="sonnet", permission_mode="acceptEdits",
                                 extra_args=["--add-dir", "/x"])
    assert full[full.index("--model") + 1] == "sonnet"
    assert full[full.index("--permission-mode") + 1] == "acceptEdits"
    assert "--add-dir" in full and "/x" in full
    print("ok build_argv")


def test_parse_each_event_type():
    init = ccr.parse_stream_json_line(
        '{"type":"system","subtype":"init","session_id":"s1"}')
    assert init.kind == "init" and init.session_id == "s1"

    asst = ccr.parse_stream_json_line(
        '{"type":"assistant","session_id":"s1","message":{"content":[{"type":"text","text":"hi"}]}}')
    assert asst.kind == "assistant_text" and asst.text == "hi"

    tool = ccr.parse_stream_json_line(
        '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash"}]}}')
    assert tool.kind == "tool_use"

    usr = ccr.parse_stream_json_line('{"type":"user","message":{"content":[]}}')
    assert usr.kind == "tool_result"

    res = ccr.parse_stream_json_line(
        '{"type":"result","subtype":"success","result":"x","num_turns":3,'
        '"total_cost_usd":0.5,"usage":{"input_tokens":1},"session_id":"s1"}')
    assert res.kind == "result" and res.text == "x" and res.num_turns == 3
    assert res.cost_usd == 0.5 and res.usage == {"input_tokens": 1} and res.is_error is False

    err = ccr.parse_stream_json_line('{"type":"result","subtype":"error_max_turns"}')
    assert err.kind == "result" and err.is_error is True

    assert ccr.parse_stream_json_line("") is None
    bad = ccr.parse_stream_json_line("{not json")
    assert bad.kind == "raw"
    unknown = ccr.parse_stream_json_line('{"type":"brand_new_event_v9"}')
    assert unknown.kind == "raw"
    print("ok parse")


def test_run_success_captures_session_and_result():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        fake = _write_fake_claude(d, _FAKE_SUCCESS)
        events = []
        result = ccr.run_claude_code(
            "do a thing", cwd=str(d), claude_bin=fake, timeout_s=30,
            on_event=events.append)
        assert result.session_id == "11111111-2222-3333-4444-555555555555"
        assert result.final_text == "Done editing."
        assert result.is_error is False and result.returncode == 0
        assert result.timed_out is False
        assert result.usage == {"input_tokens": 100, "output_tokens": 40}
        assert result.cost_usd == 0.0123 and result.num_turns == 2
        kinds = [e.kind for e in events]
        assert kinds == ["init", "assistant_text", "tool_use", "result"]
        # streamed assistant text reassembles the message
        assert "".join(e.text or "" for e in events if e.kind in
                        ("assistant_text", "tool_use")) == "Hello world"
    print("ok run_success")


def test_run_timeout_kills_process():
    body = """
        import time, sys, json
        print(json.dumps({"type":"system","subtype":"init","session_id":"s"})); sys.stdout.flush()
        time.sleep(30)
    """
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        fake = _write_fake_claude(d, body)
        result = ccr.run_claude_code("loop", cwd=str(d), claude_bin=fake, timeout_s=1.0)
        assert result.timed_out is True
        assert result.session_id == "s"  # captured before the kill
    print("ok run_timeout")


def test_run_missing_binary():
    with tempfile.TemporaryDirectory() as d:
        result = ccr.run_claude_code("x", cwd=d, claude_bin="/nonexistent/claude-xyz")
        assert result.returncode == 127 and result.is_error is True
    print("ok run_missing_binary")


def test_run_nonzero_exit_flags_error():
    body = """
        import sys, json
        print(json.dumps({"type":"system","subtype":"init","session_id":"s"}))
        sys.exit(2)
    """
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        fake = _write_fake_claude(d, body)
        result = ccr.run_claude_code("x", cwd=str(d), claude_bin=fake, timeout_s=30)
        assert result.returncode == 2 and result.is_error is True and result.timed_out is False
    print("ok run_nonzero_exit")


def test_usage_mapper_matches_gateway_shape():
    u = ccr.claude_usage_to_gateway(
        {"input_tokens": 100, "output_tokens": 40,
         "cache_read_input_tokens": 10, "cache_creation_input_tokens": 5},
        model="claude-x", num_turns=3)
    assert u["input"] == 100 and u["output"] == 40
    assert u["cache_read"] == 10 and u["cache_write"] == 5
    assert u["total"] == 140 and u["calls"] == 3 and u["model"] == "claude-x"
    # keys must match what tui_gateway _get_usage produces
    for k in ("model", "input", "output", "cache_read", "cache_write",
              "reasoning", "prompt", "completion", "total", "calls"):
        assert k in u, k
    empty = ccr.claude_usage_to_gateway(None)
    assert empty["input"] == 0 and empty["total"] == 0
    print("ok usage_mapper")


def test_translator_emits_gateway_events_in_order():
    emitted = []
    t = ccr.GatewayEventTranslator(lambda ev, pl=None: emitted.append((ev, pl)))
    sid = "abc"
    t.handle(ccr.ClaudeCodeEvent(kind="init", raw={"model": "claude-x"}, session_id=sid))
    t.handle(ccr.ClaudeCodeEvent(kind="assistant_text", raw={}, text="Hel", session_id=sid))
    t.handle(ccr.ClaudeCodeEvent(
        kind="tool_use",
        raw={"message": {"content": [{"type": "tool_use", "name": "Edit"},
                                      {"type": "text", "text": "lo"}]}},
        text="lo", session_id=sid))
    t.handle(ccr.ClaudeCodeEvent(
        kind="result", raw={}, text="all done", session_id=sid,
        usage={"input_tokens": 7, "output_tokens": 3}, num_turns=1, is_error=False))

    assert t.session_id == sid and t.model == "claude-x"
    assert emitted[0] == ("message.delta", {"text": "Hel"})
    assert ("tool.generating", {"name": "Edit"}) in emitted
    assert ("message.delta", {"text": "lo"}) in emitted
    last_ev, last_pl = emitted[-1]
    assert last_ev == "message.complete"
    assert last_pl["text"] == "all done" and last_pl["status"] == "complete"
    assert last_pl["usage"]["input"] == 7 and last_pl["usage"]["total"] == 10
    print("ok translator_order")


def test_translator_finalize_when_no_result():
    emitted = []
    t = ccr.GatewayEventTranslator(lambda ev, pl=None: emitted.append((ev, pl)))
    t.handle(ccr.ClaudeCodeEvent(kind="assistant_text", raw={}, text="partial"))
    # CLI died before a result event — finalize must still close the turn
    t.finalize(error_message="claude crashed")
    assert ("error", {"message": "claude crashed"}) in emitted
    assert emitted[-1][0] == "message.complete" and emitted[-1][1]["status"] == "error"
    # idempotent: a real result already completed → finalize is a no-op
    e2 = []
    t2 = ccr.GatewayEventTranslator(lambda ev, pl=None: e2.append((ev, pl)))
    t2.handle(ccr.ClaudeCodeEvent(kind="result", raw={}, text="ok", is_error=False))
    n_before = len(e2)
    t2.finalize()
    assert len(e2) == n_before
    print("ok translator_finalize")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\nAll {len(fns)} tests passed.")

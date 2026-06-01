"""Tests for tools.claude_code_tool (the claude_code_task tool).

Drives the real handler against a fake `claude` on PATH (emitting stream-json),
so no credentials/CLI needed. Runnable under pytest OR directly:

    python tests/tools/test_claude_code_tool.py
"""

from __future__ import annotations

import json
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import os  # noqa: E402

from tools import claude_code_tool as cct  # noqa: E402  (import self-registers the tool)

_FAKE_CLAUDE = """#!/usr/bin/env python3
import json, sys, os
sid = "ccccdddd-1111-2222-3333-444455556666"
with open("TOUCHED.txt", "w") as fh:
    fh.write("ran")
for o in [
    {"type": "system", "subtype": "init", "session_id": sid, "model": "claude-x"},
    {"type": "assistant", "session_id": sid,
     "message": {"content": [{"type": "text", "text": "Implemented it."}]}},
    {"type": "result", "subtype": "success", "is_error": False, "session_id": sid,
     "result": "Added the function and a test.", "num_turns": 3,
     "total_cost_usd": 0.02, "usage": {"input_tokens": 200, "output_tokens": 80}},
]:
    print(json.dumps(o)); sys.stdout.flush()
"""


def _install_fake_claude(binroot: Path):
    binroot.mkdir(parents=True, exist_ok=True)
    fake = binroot / "claude"
    fake.write_text(_FAKE_CLAUDE)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    os.environ["PATH"] = str(binroot) + os.pathsep + os.environ.get("PATH", "")


def test_tool_is_registered():
    from tools.registry import registry
    assert "claude_code_task" in registry._tools
    entry = registry._tools["claude_code_task"]
    assert entry.toolset == "claude_code"
    assert entry.schema["name"] == "claude_code_task"
    assert "task" in entry.schema["parameters"]["required"]
    print("ok registered")


def test_task_required():
    out = cct.claude_code_task("")
    assert "task is required" in out.lower()
    print("ok task_required")


def test_missing_working_dir():
    out = cct.claude_code_task("do x", working_dir="/no/such/dir/xyz")
    assert "does not exist" in out.lower()
    print("ok missing_working_dir")


def test_success_returns_summary_not_full_code():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        _install_fake_claude(t / "bin")
        out = cct.claude_code_task("implement a thing", working_dir=str(t))
        res = json.loads(out)
        assert res["ok"] is True
        assert res["summary"] == "Added the function and a test."
        assert res["session_id"] == "ccccdddd-1111-2222-3333-444455556666"
        # raw CLI usage is passed through (the agent reads this JSON, not the UI)
        assert res["usage"]["input_tokens"] == 200 and res["usage"]["output_tokens"] == 80
        assert res["num_turns"] == 3 and res["cost_usd"] == 0.02
        assert res["timed_out"] is False and res["returncode"] == 0
        assert res["working_dir"] == str(t)
        # claude actually ran in the working dir
        assert (t / "TOUCHED.txt").is_file()
    print("ok success_summary")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\nAll {len(fns)} tests passed.")

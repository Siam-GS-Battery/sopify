"""Integration test for the Claude Code engine branch in the gateway.

Drives tui_gateway.server._run_prompt_submit_claude_code against a fake
`claude` on PATH (emitting real stream-json) in a temp Vibe Code project, and
asserts the gateway emits the same events the UI renders, persists the session
id, and runs in the project's cwd. No WebSocket, no real CLI, no credentials.

Runnable under pytest OR directly:
    python tests/tui_gateway/test_claude_code_prompt.py
"""

from __future__ import annotations

import importlib
import json
import os
import stat
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_FAKE_CLAUDE = """#!/usr/bin/env python3
import json, sys
argv = sys.argv[1:]
# A real `claude` honours the id we pin and reports it back; mirror that.
sid = "fallback-no-id"
for flag in ("--session-id", "--resume"):
    if flag in argv:
        sid = argv[argv.index(flag) + 1]
# Record argv + prove we run in the project cwd (file edit + flag capture).
with open("CLAUDE_ARGV.txt", "w") as fh:
    fh.write(" ".join(argv))
with open("EDITED_BY_CLAUDE.txt", "w") as fh:
    fh.write("done")
for o in [
    {"type": "system", "subtype": "init", "session_id": sid, "model": "claude-x"},
    {"type": "assistant", "session_id": sid,
     "message": {"content": [{"type": "text", "text": "Editing the file..."}]}},
    {"type": "result", "subtype": "success", "is_error": False, "session_id": sid,
     "result": "Edited the file.", "num_turns": 1, "total_cost_usd": 0.01,
     "usage": {"input_tokens": 50, "output_tokens": 20}},
]:
    print(json.dumps(o)); sys.stdout.flush()
"""


def _setup(home: Path, project: str, with_marker: bool = True):
    os.environ["HERMES_HOME"] = str(home)
    import hermes_constants
    importlib.reload(hermes_constants)
    import hermes_cli.vibe_models as vm
    importlib.reload(vm)
    pdir = home / "vibe-projects" / project
    pdir.mkdir(parents=True, exist_ok=True)
    if with_marker:
        (pdir / "project.json").write_text(json.dumps({"name": project, "phase": "backend"}))
    return vm, pdir


def _install_fake_claude(binroot: Path):
    binroot.mkdir(parents=True, exist_ok=True)
    fake = binroot / "claude"
    fake.write_text(_FAKE_CLAUDE)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    os.environ["PATH"] = str(binroot) + os.pathsep + os.environ.get("PATH", "")


def _capture_server():
    """Import the gateway and monkeypatch write_json to collect emitted events."""
    import tui_gateway.server as s
    events = []
    s.write_json = lambda msg: events.append(msg)  # _emit funnels through this
    return s, events


def _types(events):
    return [m["params"]["type"] for m in events if m.get("method") == "event"]


def _payload(events, etype):
    for m in events:
        if m.get("method") == "event" and m["params"]["type"] == etype:
            return m["params"].get("payload")
    return None


def test_claude_engine_turn_streams_persists_and_edits():
    with tempfile.TemporaryDirectory() as t:
        home = Path(t)
        vm, pdir = _setup(home, "myapp")
        _install_fake_claude(home / "bin")
        s, events = _capture_server()

        session = {
            "history_lock": threading.Lock(),
            "running": True,
            "vibe_project": "myapp",
            "engine": "claude_code",
            "session_key": "k1",
        }
        s._run_prompt_submit_claude_code("r1", "sid1", session, "please edit the file")

        types = _types(events)
        assert types[0] == "message.start"
        assert "message.delta" in types
        assert types[-1] == "message.complete"
        # final payload carries the result text + mapped usage
        complete = _payload(events, "message.complete")
        assert complete["status"] == "complete"
        assert complete["text"] == "Edited the file."
        assert complete["usage"]["input"] == 50 and complete["usage"]["total"] == 70
        # claude really ran in the project cwd
        assert (pdir / "EDITED_BY_CLAUDE.txt").is_file()
        # first turn pins a fresh session id with --session-id (not --resume)
        argv = (pdir / "CLAUDE_ARGV.txt").read_text()
        assert "--session-id" in argv and "--resume" not in argv
        pinned = argv.split("--session-id", 1)[1].split()[0]
        # that pinned id is persisted into project.json (Q3 resume)
        assert vm.get_claude_session_id("myapp") == pinned and len(pinned) >= 32
        # busy flag released
        assert session["running"] is False
    print("ok claude_engine_turn")


def test_claude_engine_resumes_existing_session():
    with tempfile.TemporaryDirectory() as t:
        home = Path(t)
        vm, pdir = _setup(home, "myapp", with_marker=False)
        known = "11111111-2222-3333-4444-555555555555"
        (pdir / "project.json").write_text(json.dumps(
            {"name": "myapp", "claude_code_session_id": known}))
        _install_fake_claude(home / "bin")
        s, _events = _capture_server()
        session = {
            "history_lock": threading.Lock(), "running": True,
            "vibe_project": "myapp", "engine": "claude_code", "session_key": "k3",
        }
        s._run_prompt_submit_claude_code("r3", "sid3", session, "continue")
        argv = (pdir / "CLAUDE_ARGV.txt").read_text()
        # existing session → --resume <known>, never a fresh --session-id
        assert f"--resume {known}" in argv and "--session-id" not in argv
        # unchanged in project.json
        assert vm.get_claude_session_id("myapp") == known
    print("ok resumes_existing")


def test_claude_engine_requires_vibe_project():
    with tempfile.TemporaryDirectory() as t:
        home = Path(t)
        _setup(home, "unused")
        s, events = _capture_server()
        session = {
            "history_lock": threading.Lock(),
            "running": True,
            "vibe_project": None,
            "engine": "claude_code",
            "session_key": "k2",
        }
        s._run_prompt_submit_claude_code("r2", "sid2", session, "hello")
        types = _types(events)
        assert types[0] == "message.start"
        assert "error" in types
        assert types[-1] == "message.complete"
        assert _payload(events, "message.complete")["status"] == "error"
        assert session["running"] is False
    print("ok requires_vibe_project")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\nAll {len(fns)} tests passed.")

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


# Fails on --resume <id> (stale session) but succeeds on a fresh --session-id.
_FAKE_STALE_THEN_OK = """#!/usr/bin/env python3
import json, sys
argv = sys.argv[1:]
if "--resume" in argv:
    sid = argv[argv.index("--resume") + 1]
    sys.stderr.write("No conversation found with session ID: " + sid + "\\n")
    sys.exit(1)
sid = argv[argv.index("--session-id") + 1] if "--session-id" in argv else "fresh"
for o in [
    {"type": "system", "subtype": "init", "session_id": sid, "model": "x"},
    {"type": "assistant", "session_id": sid,
     "message": {"content": [{"type": "text", "text": "Recovered!"}]}},
    {"type": "result", "subtype": "success", "is_error": False, "session_id": sid,
     "result": "Recovered!", "num_turns": 1, "usage": {"input_tokens": 5, "output_tokens": 2}},
]:
    print(json.dumps(o)); sys.stdout.flush()
"""

# Always fails with a non-resume error (no retry should be attempted).
_FAKE_ALWAYS_FAIL = """#!/usr/bin/env python3
import sys
sys.stderr.write("boom: something broke\\n")
sys.exit(1)
"""


def _install_fake(binroot: Path, body: str):
    binroot.mkdir(parents=True, exist_ok=True)
    fake = binroot / "claude"
    fake.write_text(body)
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


def test_claude_engine_records_usage_to_db():
    import hermes_state as hs
    with tempfile.TemporaryDirectory() as t:
        home = Path(t)
        _setup(home, "myapp")
        _install_fake_claude(home / "bin")
        s, _events = _capture_server()
        db = hs.SessionDB(home / "state.db")
        s._get_db = lambda: db  # point the gateway at our temp DB
        session = {
            "history_lock": threading.Lock(), "running": True,
            "vibe_project": "myapp", "engine": "claude_code", "session_key": "k1",
        }
        s._run_prompt_submit_claude_code("r", "sid", session, "edit it")
        row = db.get_session("k1")
        assert row is not None
        assert row["agent_kind"] == "claude_code"
        assert row["input_tokens"] == 50 and row["output_tokens"] == 20
    print("ok records_usage")


def test_recovers_from_stale_session_id():
    with tempfile.TemporaryDirectory() as t:
        home = Path(t)
        vm, pdir = _setup(home, "myapp", with_marker=False)
        # marker carries a session id the CLI never actually created
        (pdir / "project.json").write_text(json.dumps(
            {"name": "myapp", "claude_code_session_id": "stale-0000"}))
        _install_fake(home / "bin", _FAKE_STALE_THEN_OK)
        s, events = _capture_server()
        s._get_db = lambda: None
        session = {
            "history_lock": threading.Lock(), "running": True,
            "vibe_project": "myapp", "engine": "claude_code", "session_key": "k",
        }
        s._run_prompt_submit_claude_code("r", "sid", session, "hi")
        # retried fresh and succeeded
        assert _types(events)[-1] == "message.complete"
        assert _payload(events, "message.complete")["status"] == "complete"
        # the stale id was replaced with the fresh one, not kept
        new_id = vm.get_claude_session_id("myapp")
        assert new_id and new_id != "stale-0000"
        assert session["running"] is False
    print("ok recovers_stale")


def test_does_not_persist_session_on_failure():
    with tempfile.TemporaryDirectory() as t:
        home = Path(t)
        vm, _pdir = _setup(home, "myapp")  # marker, no session id
        _install_fake(home / "bin", _FAKE_ALWAYS_FAIL)
        s, events = _capture_server()
        s._get_db = lambda: None
        session = {
            "history_lock": threading.Lock(), "running": True,
            "vibe_project": "myapp", "engine": "claude_code", "session_key": "k",
        }
        s._run_prompt_submit_claude_code("r", "sid", session, "hi")
        # a failed turn must NOT persist a phantom session id
        assert vm.get_claude_session_id("myapp") is None
        assert _payload(events, "message.complete")["status"] == "error"
        assert session["running"] is False
    print("ok no_persist_on_failure")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\nAll {len(fns)} tests passed.")

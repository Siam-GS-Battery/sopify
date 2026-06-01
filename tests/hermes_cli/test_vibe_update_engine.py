"""Tests for the `engine` field on PATCH /api/vibe/projects/{name}.

Calls the real async handler directly (token check + projects-root monkeypatched
to a temp dir), so it exercises the actual validation + marker-write code with
no running server. Runnable under pytest OR directly:

    python tests/hermes_cli/test_vibe_update_engine.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import hermes_cli.web_server as w  # noqa: E402

w._require_token = lambda *a, **k: None  # bypass the dashboard session token


def _patch(name: str, **fields):
    body = w.VibeProjectPatch(**fields)
    return asyncio.run(w.vibe_update_project(name, body, request=object()))


def _with_project(t: str, marker: dict):
    root = Path(t) / "vibe-projects"
    (root / "proj").mkdir(parents=True, exist_ok=True)
    (root / "proj" / "project.json").write_text(json.dumps(marker))
    w._VIBE_PROJECTS_ROOT = root
    return root / "proj" / "project.json"


def _read(f: Path) -> dict:
    return json.loads(f.read_text())


def test_set_engine_claude_code():
    with tempfile.TemporaryDirectory() as t:
        f = _with_project(t, {"name": "proj", "phase": "backend"})
        res = _patch("proj", engine="claude_code")
        assert res["ok"] is True and res["project"]["engine"] == "claude_code"
        assert _read(f)["engine"] == "claude_code"           # persisted on disk
        assert _read(f)["phase"] == "backend"                # untouched
    print("ok set_claude_code")


def test_unset_engine_reverts_to_hermes():
    with tempfile.TemporaryDirectory() as t:
        f = _with_project(t, {"name": "proj", "engine": "claude_code"})
        for off in ("", "hermes", "default"):
            _with_project(t, {"name": "proj", "engine": "claude_code"})
            res = _patch("proj", engine=off)
            assert "engine" not in res["project"], off
            assert "engine" not in _read(f), off
    print("ok unset_reverts")


def test_unknown_engine_rejected():
    with tempfile.TemporaryDirectory() as t:
        f = _with_project(t, {"name": "proj", "engine": "claude_code"})
        try:
            _patch("proj", engine="gpt-9000")
        except w.HTTPException as e:
            assert e.status_code == 400
        else:
            raise AssertionError("expected HTTPException for unknown engine")
        # rejected write must not have mutated the marker
        assert _read(f)["engine"] == "claude_code"
    print("ok unknown_rejected")


def test_engine_omitted_leaves_it_unchanged():
    with tempfile.TemporaryDirectory() as t:
        f = _with_project(t, {"name": "proj", "engine": "claude_code"})
        res = _patch("proj", summary="hello")               # no engine field
        assert res["project"]["engine"] == "claude_code"    # preserved
        assert _read(f)["summary"] == "hello"
    print("ok omitted_unchanged")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\nAll {len(fns)} tests passed.")

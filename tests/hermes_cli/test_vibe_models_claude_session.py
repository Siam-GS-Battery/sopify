"""Tests for the Claude Code session-id persistence helpers in vibe_models.

Runnable under pytest OR directly:
    python tests/hermes_cli/test_vibe_models_claude_session.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _fresh_module(home: Path):
    """Import vibe_models with HERMES_HOME pointed at a temp dir."""
    os.environ["HERMES_HOME"] = str(home)
    import importlib
    import hermes_constants
    importlib.reload(hermes_constants)
    import hermes_cli.vibe_models as vm
    importlib.reload(vm)
    return vm


def _make_project(home: Path, name: str, marker: dict | None = None) -> Path:
    d = home / "vibe-projects" / name
    d.mkdir(parents=True, exist_ok=True)
    if marker is not None:
        (d / "project.json").write_text(json.dumps(marker), encoding="utf-8")
    return d


def test_get_returns_none_for_unknown_or_unset():
    with tempfile.TemporaryDirectory() as t:
        home = Path(t)
        vm = _fresh_module(home)
        assert vm.get_claude_session_id("nope") is None        # no project
        _make_project(home, "proj", {"name": "proj", "phase": "design"})
        assert vm.get_claude_session_id("proj") is None        # field absent
    print("ok get_none")


def test_set_then_get_roundtrip_preserves_other_fields():
    with tempfile.TemporaryDirectory() as t:
        home = Path(t)
        vm = _fresh_module(home)
        _make_project(home, "proj", {"name": "proj", "phase": "backend",
                                     "model_per_phase": {"backend": "x/y"}})
        ok = vm.set_claude_session_id("proj", "11111111-2222-3333-4444-555555555555")
        assert ok is True
        assert vm.get_claude_session_id("proj") == "11111111-2222-3333-4444-555555555555"
        # other fields survived the merge
        marker = vm.read_vibe_marker("proj")
        assert marker["phase"] == "backend" and marker["model_per_phase"] == {"backend": "x/y"}
    print("ok roundtrip")


def test_set_creates_field_when_marker_missing_but_dir_exists():
    with tempfile.TemporaryDirectory() as t:
        home = Path(t)
        vm = _fresh_module(home)
        _make_project(home, "proj")  # dir, no project.json
        assert vm.set_claude_session_id("proj", "sid-1") is True
        assert vm.get_claude_session_id("proj") == "sid-1"
    print("ok create_missing_marker")


def test_set_recovers_from_corrupt_marker():
    with tempfile.TemporaryDirectory() as t:
        home = Path(t)
        vm = _fresh_module(home)
        d = _make_project(home, "proj")
        (d / "project.json").write_text("{not valid json", encoding="utf-8")
        assert vm.set_claude_session_id("proj", "sid-2") is True
        assert vm.get_claude_session_id("proj") == "sid-2"
    print("ok recover_corrupt")


def test_set_overwrites_and_rejects_unknown_project():
    with tempfile.TemporaryDirectory() as t:
        home = Path(t)
        vm = _fresh_module(home)
        _make_project(home, "proj", {"name": "proj"})
        vm.set_claude_session_id("proj", "old")
        vm.set_claude_session_id("proj", "new")
        assert vm.get_claude_session_id("proj") == "new"
        # unknown / traversal names are rejected (vibe_project_dir returns None)
        assert vm.set_claude_session_id("../escape", "x") is False
        assert vm.set_claude_session_id("does-not-exist", "x") is False
    print("ok overwrite_and_reject")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\nAll {len(fns)} tests passed.")

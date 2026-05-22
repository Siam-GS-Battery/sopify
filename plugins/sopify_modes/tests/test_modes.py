"""Tests for sopify-modes."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _modes():
    return importlib.reload(importlib.import_module("plugins.sopify_modes"))


def test_living_profile_is_strict():
    """REQ-3.3.1/2/3."""
    cfg = importlib.import_module("plugins.sopify_modes.config")
    p = cfg.get("living")
    assert p.deny_list_level == "strict"
    assert p.require_approval_for_destructive is True
    assert p.parallel_tool_execution is False
    assert p.persistent_session is True


def test_code_with_you_profile_50k_budget():
    """REQ-5.3.1."""
    cfg = importlib.import_module("plugins.sopify_modes.config")
    p = cfg.get("code-with-you")
    assert p.daily_token_budget == 50_000
    assert p.confirm_every_step is True
    assert p.parallel_tool_execution is False


def test_vibe_intake_questions_in_order():
    vibe = importlib.import_module("plugins.sopify_modes.vibe")
    a = vibe.IntakeAnswers()
    assert vibe.render_intake_prompt(a) == vibe.INTAKE_QUESTIONS[0]
    a.goal = "x"
    assert vibe.render_intake_prompt(a) == vibe.INTAKE_QUESTIONS[1]
    a.data_source = "y"
    a.target_user = "z"
    assert vibe.render_intake_prompt(a) == vibe.INTAKE_QUESTIONS[3]
    a.output_format = "w"
    assert vibe.render_intake_prompt(a) == ""
    assert a.complete


def test_code_with_you_gate_blocks_when_skipped():
    cwy = importlib.import_module("plugins.sopify_modes.code_with_you")
    cwy.set_confirm_callback(lambda step: (cwy.SKIP, None))
    result = cwy.gate("bash", {"command": "ls"})
    assert result is not None and result["blocked"]


def test_code_with_you_gate_passes_when_execute():
    cwy = importlib.import_module("plugins.sopify_modes.code_with_you")
    cwy.set_confirm_callback(lambda step: (cwy.EXECUTE, None))
    assert cwy.gate("bash", {"command": "ls"}) is None


def test_app_fingerprint_stable(tmp_path):
    vibe = importlib.import_module("plugins.sopify_modes.vibe")
    (tmp_path / "a.py").write_text("print(1)")
    (tmp_path / "b.txt").write_text("hi")
    f1 = vibe.app_fingerprint(tmp_path)
    f2 = vibe.app_fingerprint(tmp_path)
    assert f1 == f2
    # Add a file → fingerprint changes.
    (tmp_path / "c.py").write_text("x")
    assert vibe.app_fingerprint(tmp_path) != f1


def test_slash_command_activates_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("SOPIFY_HOME", str(tmp_path))
    modes = _modes()
    out = modes._on_slash_command(command="/vibe", args="")
    assert out is not None
    assert out["mode"] == "vibe"
    assert modes.active_mode() == "vibe"

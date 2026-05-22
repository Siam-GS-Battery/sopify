"""Tests for sopify-skills loader."""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _loader(monkeypatch, home):
    monkeypatch.setenv("SOPIFY_HOME", str(home))
    mod = importlib.import_module("plugins.sopify_skills.loader")
    return importlib.reload(mod)


def test_bundled_skills_discovered(tmp_path, monkeypatch):
    loader = _loader(monkeypatch, tmp_path)
    skills = loader.all_skills()
    assert "company-sop" in skills
    assert "living-employee" in skills
    assert "vibe-app-builder" in skills
    assert "code-with-you" in skills


def test_gs_mad_gated_by_phase(tmp_path, monkeypatch):
    """REQ-8.1.5 — gs-mad only when phase >= 7."""
    loader = _loader(monkeypatch, tmp_path)
    # default phase = 1 → gs-mad should be filtered out
    assert "gs-mad" not in loader.all_skills()
    (tmp_path / "settings.json").write_text(json.dumps({"phase": 7}))
    loader = _loader(monkeypatch, tmp_path)
    assert "gs-mad" in loader.all_skills()


def test_skills_for_mode_vibe_includes_company_sop(tmp_path, monkeypatch):
    loader = _loader(monkeypatch, tmp_path)
    bundles = [s.name for s in loader.skills_for_mode("vibe")]
    assert "company-sop" in bundles
    assert "vibe-app-builder" in bundles
    # code-with-you skill should NOT be selected for vibe mode
    assert "code-with-you" not in bundles


def test_skills_for_mode_living_includes_persona(tmp_path, monkeypatch):
    loader = _loader(monkeypatch, tmp_path)
    bundles = [s.name for s in loader.skills_for_mode("living")]
    assert "living-employee" in bundles


def test_render_system_prompt_concatenates(tmp_path, monkeypatch):
    loader = _loader(monkeypatch, tmp_path)
    prompt = loader.render_system_prompt("vibe")
    assert "Skill: company-sop" in prompt
    assert "Skill: vibe-app-builder" in prompt
    assert "---" not in prompt.split("\n", 1)[0]  # front-matter stripped


def test_project_local_skill_overrides_bundled(tmp_path, monkeypatch):
    """REQ-8.2.3 — project skill with same name wins."""
    # Make tmp_path the cwd so .sopify/skills is read.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SOPIFY_HOME", str(tmp_path / ".sopify"))
    skills_dir = tmp_path / ".sopify" / "skills" / "company-sop"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        "---\nname: company-sop\ndescription: project override\n---\nLOCAL\n"
    )
    loader = _loader(monkeypatch, tmp_path / ".sopify")
    assert loader.all_skills()["company-sop"].description == "project override"

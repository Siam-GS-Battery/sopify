"""Tests for sopify-management."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _settings(monkeypatch, home):
    monkeypatch.setenv("SOPIFY_HOME", str(home))
    return importlib.reload(importlib.import_module("plugins.sopify_management.settings"))


def test_defaults_returned_when_no_file(tmp_path, monkeypatch):
    s = _settings(monkeypatch, tmp_path)
    cfg = s.load()
    assert cfg["sandbox_enabled"] is True
    assert "anthropic" in cfg["provider_chain"]
    assert cfg["log_user_prompts"] is False


def test_write_managed_sets_mode_0444(tmp_path, monkeypatch):
    s = _settings(monkeypatch, tmp_path)
    s.write_managed({"sandbox_enabled": True, "phase": 3})
    p = s.settings_path()
    assert p.stat().st_mode & 0o777 == 0o444


def test_subscribe_broadcast(tmp_path, monkeypatch):
    s = _settings(monkeypatch, tmp_path)
    seen = []
    s.subscribe(lambda data: seen.append(data))
    s.write_managed({"phase": 7})
    assert seen, "subscriber should fire on write_managed"
    assert seen[-1]["phase"] == 7


def test_quota_warning_fires_at_80_percent(tmp_path, monkeypatch):
    monkeypatch.setenv("SOPIFY_HOME", str(tmp_path))
    q = importlib.reload(importlib.import_module("plugins.sopify_management.quota"))
    q.reset()
    warnings = []
    q.set_warning_callback(lambda p, u, b: warnings.append((p, u, b)))
    # Default vibe budget = 200_000. Record 160_001 (80%+).
    # We need active_mode = "vibe" — fall back to default budget of 200_000.
    q.record("anthropic", input_tokens=160_001)
    assert warnings, "warning should fire at 80%"
    # Second hit should NOT re-warn (once per session per provider).
    q.record("anthropic", input_tokens=5_000)
    assert len(warnings) == 1


def test_onboard_records_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("SOPIFY_HOME", str(tmp_path))
    onboard = importlib.reload(importlib.import_module("plugins.sopify_management.onboard"))
    assert not onboard.already_consented()
    onboard.record_consent("alice@example.com")
    assert onboard.already_consented()
    data = json.loads(onboard.consent_file().read_text())
    assert data["user"] == "alice@example.com"

"""Tests for sopify-providers."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _import():
    return importlib.import_module("plugins.sopify_providers.router")


def test_default_chain_picks_anthropic_first(monkeypatch, tmp_path):
    monkeypatch.setenv("SOPIFY_HOME", str(tmp_path))
    mod = _import()
    r = mod.ProviderRouter.from_settings()
    assert r.pick() == "anthropic"


def test_blacklist_skips_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("SOPIFY_HOME", str(tmp_path))
    mod = _import()
    r = mod.ProviderRouter()
    r.record_failure("anthropic", status=401)
    assert r.pick() != "anthropic"
    # Should fall through to openrouter (second in default chain).
    assert r.pick() == "openrouter"


def test_blacklist_expires(tmp_path, monkeypatch):
    monkeypatch.setenv("SOPIFY_HOME", str(tmp_path))
    mod = _import()
    r = mod.ProviderRouter()
    r.record_failure("anthropic", status=401)
    # Move time forward past the 1-hour TTL.
    r._now = staticmethod(lambda: 1e12)
    assert r.pick() == "anthropic"


def test_managed_chain_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SOPIFY_HOME", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"provider_chain": ["openrouter", "anthropic"]})
    )
    mod = _import()
    r = mod.ProviderRouter.from_settings()
    assert r.pick() == "openrouter"


def test_non_auth_failure_not_blacklisted(tmp_path, monkeypatch):
    monkeypatch.setenv("SOPIFY_HOME", str(tmp_path))
    mod = _import()
    r = mod.ProviderRouter()
    r.record_failure("anthropic", status=500)  # server error, transient
    assert r.pick() == "anthropic"


def test_auth_override_masks_claude_code(monkeypatch, tmp_path):
    """Sopify login key must beat Claude Code OAuth (REQ-2.2.2 spirit)."""
    import json, os, sys
    monkeypatch.setenv("SOPIFY_HOME", str(tmp_path))
    (tmp_path / "auth.json").write_text(json.dumps({"anthropic": "sk-ant-api03-TEST"}))
    os.chmod(tmp_path / "auth.json", 0o600)
    # Pre-pollute env to simulate a Claude Code session.
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "cc-leftover")
    monkeypatch.setenv("ANTHROPIC_TOKEN", "leftover")

    # Stub the agent module so apply() can mask without importing the
    # whole Hermes runtime in the test.
    fake_adapter = type(sys)("agent.anthropic_adapter")
    fake_adapter.read_claude_code_credentials = lambda: {"access_token": "shouldnt-win"}
    sys.modules.setdefault("agent", type(sys)("agent"))
    sys.modules["agent.anthropic_adapter"] = fake_adapter

    import importlib
    ao = importlib.reload(importlib.import_module("plugins.sopify_providers.auth_override"))
    out = ao.apply()
    assert out == "sk-ant-api03-TEST"
    assert os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-api03-TEST"
    assert os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") is None
    assert os.environ.get("ANTHROPIC_TOKEN") is None
    # The mask must make read_claude_code_credentials return None.
    assert fake_adapter.read_claude_code_credentials() is None

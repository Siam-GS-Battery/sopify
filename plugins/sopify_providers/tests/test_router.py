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

"""Tests for sopify-sandbox network policy."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _np(monkeypatch, home):
    monkeypatch.setenv("SOPIFY_HOME", str(home))
    np = importlib.import_module("plugins.sopify_sandbox.network_policy")
    return importlib.reload(np)


def test_default_whitelist_allows_anthropic(tmp_path, monkeypatch):
    np = _np(monkeypatch, tmp_path)
    d = np.evaluate("api.anthropic.com", ask_user=lambda h: "deny")
    assert d.allow
    assert d.reason == "whitelisted"


def test_subdomain_match(tmp_path, monkeypatch):
    np = _np(monkeypatch, tmp_path)
    # api.anthropic.com is exact; subdomains of whitelisted should also pass.
    (tmp_path / "network-policy.json").write_text(
        json.dumps({"whitelist": ["anthropic.com"], "user_added": []})
    )
    np = _np(monkeypatch, tmp_path)
    assert np.evaluate("docs.anthropic.com", ask_user=lambda h: "deny").allow


def test_unknown_host_denied_without_ui(tmp_path, monkeypatch):
    np = _np(monkeypatch, tmp_path)
    d = np.evaluate("evil.example.com", ask_user=None)
    assert not d.allow


def test_allow_always_persists(tmp_path, monkeypatch):
    np = _np(monkeypatch, tmp_path)
    d = np.evaluate("ok.example.com", ask_user=lambda h: "always")
    assert d.allow and d.persist
    np.persist_allow_always("ok.example.com")
    data = json.loads((tmp_path / "network-policy.json").read_text())
    assert "ok.example.com" in data["user_added"]


def test_deny_choice(tmp_path, monkeypatch):
    np = _np(monkeypatch, tmp_path)
    d = np.evaluate("ads.example.com", ask_user=lambda h: "deny")
    assert not d.allow
    assert d.reason == "user denied"

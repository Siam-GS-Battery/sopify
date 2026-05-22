"""Tests for sopify-tui."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _dialogs():
    return importlib.reload(importlib.import_module("plugins.sopify_tui.dialogs"))


def test_network_dialog_choices(monkeypatch):
    d = _dialogs()
    d.COLOR = False
    monkeypatch.setattr(d, "_input", lambda *_: "2")
    assert d.ask_network_permission("evil.com") == "always"
    monkeypatch.setattr(d, "_input", lambda *_: "3")
    assert d.ask_network_permission("evil.com") == "deny"
    monkeypatch.setattr(d, "_input", lambda *_: "")
    assert d.ask_network_permission("evil.com") == "deny"  # default safe


def test_confirm_destructive_default_no(monkeypatch):
    d = _dialogs()
    d.COLOR = False
    monkeypatch.setattr(d, "_input", lambda *_: "")
    assert d.confirm_destructive("rm -rf ./x", "Recursive delete") is False
    monkeypatch.setattr(d, "_input", lambda *_: "y")
    assert d.confirm_destructive("rm -rf ./x", "Recursive delete") is True


def test_confirm_step_choices(monkeypatch):
    d = _dialogs()
    d.COLOR = False
    monkeypatch.setattr(d, "_input", lambda *_: "e")
    assert d.confirm_step("bash", {"command": "ls"}, "list dir") == ("execute", None)
    monkeypatch.setattr(d, "_input", lambda *_: "s")
    assert d.confirm_step("bash", {"command": "ls"}, "list dir") == ("skip", None)
    monkeypatch.setattr(d, "_input", lambda *_: "x")
    assert d.confirm_step("bash", {"command": "ls"}, "list dir") == ("stop", None)


def test_thai_characters_pass_through():
    """REQ-10.6 — UTF-8 Thai must not garble."""
    d = _dialogs()
    d.COLOR = False
    s = d._wrap("", "อยากได้อะไร?")
    assert "อยากได้อะไร?" in s

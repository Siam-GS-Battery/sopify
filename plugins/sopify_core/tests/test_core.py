"""Tests for sopify-core. Designed to run with `uv run pytest`."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

# Make the plugin importable as a regular package for tests.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _load(modname: str):
    return importlib.import_module(f"plugins.sopify_core.{modname}")


def test_paths_honours_sopify_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SOPIFY_HOME", str(tmp_path))
    paths = _load("paths")
    importlib.reload(paths)
    assert paths.home() == tmp_path
    assert paths.settings_file().parent == tmp_path


def test_version_string_includes_both():
    version = _load("version")
    s = version.full_version_string()
    assert "sopify" in s.lower()
    assert "runtime" in s.lower()


def test_doctor_runs_under_3s(tmp_path, monkeypatch):
    """Gate P2 — doctor reports sandbox status within < 3 seconds."""
    monkeypatch.setenv("SOPIFY_HOME", str(tmp_path))
    doctor = _load("doctor")
    importlib.reload(doctor)
    report = doctor.run()
    assert report.elapsed_ms < 3000
    assert any(c.name == "docker" for c in report.checks)
    assert any(c.name == "auth" for c in report.checks)


def test_install_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("SOPIFY_HOME", str(tmp_path))
    install = _load("install")
    importlib.reload(install)
    # The install touches Docker; if Docker is missing on the test box, both
    # runs should fail identically — same error, no state drift.
    r1 = install.run()
    r2 = install.run()
    assert r1.ok == r2.ok
    if r1.ok:
        assert (tmp_path / "network-policy.json").exists()

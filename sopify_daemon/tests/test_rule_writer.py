"""Atomic write + read + delete + disable for ENCM rule YAML files."""
from __future__ import annotations

import os

import pytest

from sopify_daemon import paths
from sopify_daemon.rule_writer import RuleFileError, RuleFileWriter, make_rule


@pytest.fixture()
def encm_root(tmp_path, monkeypatch):
    """Isolate every test under a tmp ENCM root."""
    monkeypatch.setenv(paths.ENV_ROOT, str(tmp_path))
    paths.ensure_skeleton()
    yield tmp_path


def test_write_creates_yaml(encm_root):
    w = RuleFileWriter()
    rule = make_rule(name="allow-npm", patterns=["*.npmjs.org"])
    path = w.write(rule)
    assert path.exists()
    assert path.read_text().startswith("apiVersion: sopify.dev/v1")


def test_write_landing_paths(encm_root):
    w = RuleFileWriter()
    # global → rules/global/<name>.yaml
    p1 = w.write(make_rule(name="g", patterns=["a.com"]))
    assert p1.parent.name == "global"
    # sandbox → rules/sandboxes/<sid>/<name>.yaml
    p2 = w.write(make_rule(
        name="s", patterns=["b.com"], scope="sandbox", sandbox_id="proj-x",
    ))
    assert p2.parent.name == "proj-x"
    assert p2.parent.parent.name == "sandboxes"


def test_write_refuses_overwrite_by_default(encm_root):
    w = RuleFileWriter()
    w.write(make_rule(name="dup", patterns=["a.com"]))
    with pytest.raises(RuleFileError):
        w.write(make_rule(name="dup", patterns=["b.com"]))


def test_write_overwrite_replaces(encm_root):
    w = RuleFileWriter()
    w.write(make_rule(name="rep", patterns=["a.com"]))
    w.write(make_rule(name="rep", patterns=["b.com"]), overwrite=True)
    rule = w.read(w.path_for(make_rule(name="rep", patterns=["c.com"])))
    assert rule.spec.patterns == ["b.com"]


def test_read_round_trip(encm_root):
    w = RuleFileWriter()
    rule = make_rule(
        name="rt",
        patterns=["sub.example.com", "*.example.org"],
        decision="deny",
        labels={"project": "rd"},
    )
    path = w.write(rule)
    loaded = w.read(path)
    assert loaded.metadata.name == "rt"
    assert loaded.spec.decision == "deny"
    assert "*.example.org" in loaded.spec.patterns
    assert loaded.metadata.labels == {"project": "rd"}


def test_delete(encm_root):
    w = RuleFileWriter()
    w.write(make_rule(name="d", patterns=["a.com"]))
    assert w.delete(name="d") is True
    # Idempotent on second call
    assert w.delete(name="d") is False


def test_delete_sandbox_scope(encm_root):
    w = RuleFileWriter()
    w.write(make_rule(name="s", patterns=["a.com"], scope="sandbox", sandbox_id="proj-y"))
    assert w.delete(name="s", scope="sandbox", sandbox_id="proj-y") is True


def test_delete_sandbox_requires_id(encm_root):
    w = RuleFileWriter()
    with pytest.raises(RuleFileError):
        w.delete(name="x", scope="sandbox")


def test_disable_flips_to_deny(encm_root):
    w = RuleFileWriter()
    rule = make_rule(name="dis", patterns=["a.com"], decision="allow")
    w.write(rule)
    path = w.disable(name="dis")
    reloaded = w.read(path)
    assert reloaded.spec.decision == "deny"
    # Other fields untouched
    assert reloaded.spec.patterns == ["a.com"]


def test_disable_not_found(encm_root):
    w = RuleFileWriter()
    with pytest.raises(RuleFileError):
        w.disable(name="ghost")


def test_list_all_skips_malformed(encm_root):
    w = RuleFileWriter()
    w.write(make_rule(name="ok", patterns=["a.com"]))
    # Drop a broken file alongside
    (paths.global_rules_dir() / "broken.yaml").write_text("not: a valid: rule:\n")
    rules = w.list_all()
    assert any(r.metadata.name == "ok" for r in rules)
    assert all(r.metadata.name != "broken" for r in rules)


def test_atomic_write_no_tmp_leftover(encm_root):
    w = RuleFileWriter()
    w.write(make_rule(name="atomic", patterns=["a.com"]))
    # Tempfile should be cleaned up after the rename
    for entry in paths.global_rules_dir().iterdir():
        assert not entry.name.endswith(".tmp")


def test_make_rule_defaults():
    rule = make_rule(name="x", patterns=["a.com"])
    assert rule.metadata.scope == "global"
    assert rule.spec.type == "domain"
    assert rule.spec.decision == "allow"
    assert rule.spec.ttl_seconds is None

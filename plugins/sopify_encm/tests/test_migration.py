"""v1 → v2 migration tests."""
from __future__ import annotations

import json
from pathlib import Path

from plugins.sopify_encm.migration import migrate, migrate_file
from plugins.sopify_encm.schema import HttpRule, NetworkPolicy, default_policy


def test_migrate_empty_file_writes_defaults(tmp_path):
    f = tmp_path / "network-policy.json"
    assert not f.exists()
    p = migrate_file(f)
    assert f.exists()
    assert p.schema_version == 2
    # Should contain bundled defaults
    domains = {r.domain for r in p.rules}
    assert "api.anthropic.com" in domains
    assert "pypi.org" in domains


def test_migrate_v1_to_v2_preserves_user_added(tmp_path):
    f = tmp_path / "network-policy.json"
    f.write_text(json.dumps({
        "version": 1,
        "whitelist": ["api.anthropic.com", "otel-collector.gsbattery.local"],
        "user_added": ["pg.gsbattery.local", "sharepoint.gsbattery.com"],
    }))
    p = migrate_file(f)
    assert p.schema_version == 2

    # The user_added entries became v2 rules with added_by="user"
    user_rules = [r for r in p.rules if r.added_by == "user"]
    user_domains = {r.domain for r in user_rules}
    assert "pg.gsbattery.local" in user_domains
    assert "sharepoint.gsbattery.com" in user_domains

    # v1 default whitelist entries are tagged as `default`
    default_rules = [r for r in p.rules if r.added_by == "default"]
    default_domains = {r.domain for r in default_rules}
    assert "api.anthropic.com" in default_domains

    # Backup written next to the original
    backup = f.with_suffix(f.suffix + ".v1.bak")
    assert backup.exists()
    backup_data = json.loads(backup.read_text())
    assert backup_data.get("version") == 1


def test_migrate_v2_is_idempotent(tmp_path):
    f = tmp_path / "network-policy.json"
    original = default_policy()
    f.write_text(json.dumps(original.model_dump(mode="json")))
    p = migrate_file(f)
    assert p.schema_version == 2
    # No v1 backup should be created if input was already v2
    backup = f.with_suffix(f.suffix + ".v1.bak")
    assert not backup.exists()


def test_migrate_corrupt_file_writes_fresh_defaults(tmp_path):
    f = tmp_path / "network-policy.json"
    f.write_text("{ this is not valid json")
    p = migrate_file(f)
    assert p.schema_version == 2
    assert len(p.rules) >= 5
    # Corruption backup
    corrupt_backup = f.with_suffix(f.suffix + ".corrupt.bak")
    assert corrupt_backup.exists()


def test_migrate_unknown_shape_yields_defaults():
    """If the file has neither v1 nor v2 markers, fall back to defaults
    rather than crashing — install must never hard-fail here."""
    weird = {"hello": "world", "foo": 42}
    p = migrate(weird)
    assert p.schema_version == 2
    assert len(p.rules) >= 5


def test_migrate_v1_merges_with_defaults_without_duplicates(tmp_path):
    """If user had api.anthropic.com in v1 whitelist, the v2 output must not
    contain it twice — the migration should de-dup against bundled defaults."""
    f = tmp_path / "network-policy.json"
    f.write_text(json.dumps({
        "version": 1,
        "whitelist": ["api.anthropic.com"],
        "user_added": [],
    }))
    p = migrate_file(f)
    anthro_rules = [r for r in p.rules if r.domain == "api.anthropic.com"]
    assert len(anthro_rules) == 1, "domain duplicated across whitelist + defaults"


def test_migrate_v1_user_entry_kept_even_if_also_a_default(tmp_path):
    """An odd case: user marked api.anthropic.com as user_added. Migration
    should still produce exactly one rule for the domain (no duplicate)."""
    f = tmp_path / "network-policy.json"
    f.write_text(json.dumps({
        "version": 1,
        "whitelist": [],
        "user_added": ["api.anthropic.com"],
    }))
    p = migrate_file(f)
    anthro = [r for r in p.rules if r.domain == "api.anthropic.com"]
    assert len(anthro) == 1


def test_migrate_preserves_all_v1_domains_as_https_443(tmp_path):
    """v1 had no protocol/port — migration must default to https:443 so
    behaviour is preserved (sandboxes already used the v1 whitelist over HTTPS)."""
    f = tmp_path / "network-policy.json"
    f.write_text(json.dumps({
        "version": 1,
        "whitelist": [],
        "user_added": ["custom.example.com"],
    }))
    p = migrate_file(f)
    custom = [r for r in p.rules if r.domain == "custom.example.com"]
    assert len(custom) == 1
    assert isinstance(custom[0], HttpRule)
    assert custom[0].protocol == "https"
    assert 443 in custom[0].ports

"""Audit writer + rotator tests."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.sopify_encm.audit import AuditEvent, AuditWriter, purge_old_logs


def test_writer_creates_file_on_first_write(tmp_path):
    w = AuditWriter(tmp_path)
    w.write(AuditEvent(decision="allow", protocol="https",
                       src="sandbox-1", dst="api.example.com:443"))
    w.close()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    f = tmp_path / f"{today}.jsonl"
    assert f.exists()


def test_writer_appends_one_event_per_line(tmp_path):
    w = AuditWriter(tmp_path)
    for i in range(5):
        w.write(AuditEvent(decision="allow", protocol="https",
                           src=f"sandbox-{i}", dst="api.example.com:443"))
    w.close()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    f = tmp_path / f"{today}.jsonl"
    lines = [json.loads(line) for line in f.read_text().splitlines()]
    assert len(lines) == 5
    assert all(line["decision"] == "allow" for line in lines)
    assert {line["src"] for line in lines} == {f"sandbox-{i}" for i in range(5)}


def test_writer_includes_optional_fields(tmp_path):
    w = AuditWriter(tmp_path)
    w.write(AuditEvent(
        decision="deny", protocol="tcp", src="s1", dst="pg.local:5432",
        rule_id="rule_x", reason="policy:non_dev_block:DROP",
        wire_protocol="postgresql",
        query_sample="DROP TABLE x",
    ))
    w.close()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    line = json.loads((tmp_path / f"{today}.jsonl").read_text().strip())
    assert line["wire_protocol"] == "postgresql"
    assert line["query_sample"] == "DROP TABLE x"
    assert line["reason"] == "policy:non_dev_block:DROP"


def test_writer_omits_unset_optional_fields(tmp_path):
    """Optional fields that are None must not appear in the JSON — keeps
    log size tight and avoids `"method": null` noise."""
    w = AuditWriter(tmp_path)
    w.write(AuditEvent(decision="allow", protocol="mqtt",
                       src="s1", dst="broker.local:1883",
                       mqtt_action="sub", mqtt_topic="sensors/+/telemetry"))
    w.close()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    line = json.loads((tmp_path / f"{today}.jsonl").read_text().strip())
    assert "method" not in line
    assert "status" not in line
    assert "wire_protocol" not in line
    assert line["mqtt_action"] == "sub"


def test_writer_concurrent_appends_no_interleave(tmp_path):
    """Two threads writing simultaneously must produce valid JSONL — no
    half-written line wedged inside another."""
    import threading
    w = AuditWriter(tmp_path)

    def hammer(src: str, n: int) -> None:
        for _ in range(n):
            w.write(AuditEvent(decision="allow", protocol="https",
                               src=src, dst="api.example.com:443"))

    t1 = threading.Thread(target=hammer, args=("s1", 100))
    t2 = threading.Thread(target=hammer, args=("s2", 100))
    t1.start(); t2.start()
    t1.join(); t2.join()
    w.close()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    f = tmp_path / f"{today}.jsonl"
    lines = f.read_text().splitlines()
    assert len(lines) == 200
    # Every line must be parseable JSON — if interleaving happened, some
    # would have garbage and json.loads would raise.
    for line in lines:
        parsed = json.loads(line)
        assert parsed["src"] in ("s1", "s2")


def test_writer_extras_get_flattened(tmp_path):
    w = AuditWriter(tmp_path)
    ev = AuditEvent(decision="allow", protocol="https",
                    src="s1", dst="a.com:443",
                    extras={"trace_id": "abc123", "user_agent": "curl/8.0"})
    w.write(ev)
    w.close()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    line = json.loads((tmp_path / f"{today}.jsonl").read_text().strip())
    assert line["trace_id"] == "abc123"
    assert line["user_agent"] == "curl/8.0"


def test_writer_context_manager(tmp_path):
    """`with AuditWriter(...) as w:` must close the file on exit."""
    with AuditWriter(tmp_path) as w:
        w.write(AuditEvent(decision="allow", protocol="https",
                           src="s1", dst="a.com:443"))
    # After context exit, writing should re-open the file (not crash)
    with AuditWriter(tmp_path) as w2:
        w2.write(AuditEvent(decision="deny", protocol="https",
                            src="s2", dst="bad.com:443"))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = (tmp_path / f"{today}.jsonl").read_text().splitlines()
    assert len(lines) == 2


# ── Rotator ──────────────────────────────────────────────────────────────

def test_purge_removes_old_files(tmp_path):
    # Create files for several days back
    today = datetime.now(timezone.utc).date()
    old_day = today - timedelta(days=45)
    medium_day = today - timedelta(days=15)
    new_day = today - timedelta(days=5)

    (tmp_path / f"{old_day.isoformat()}.jsonl").write_text("{}\n")
    (tmp_path / f"{medium_day.isoformat()}.jsonl").write_text("{}\n")
    (tmp_path / f"{new_day.isoformat()}.jsonl").write_text("{}\n")
    (tmp_path / f"{today.isoformat()}.jsonl").write_text("{}\n")

    removed = purge_old_logs(tmp_path, retention_days=30)

    assert (tmp_path / f"{old_day.isoformat()}.jsonl") in removed
    assert not (tmp_path / f"{old_day.isoformat()}.jsonl").exists()
    # Files within retention stay
    assert (tmp_path / f"{medium_day.isoformat()}.jsonl").exists()
    assert (tmp_path / f"{new_day.isoformat()}.jsonl").exists()
    assert (tmp_path / f"{today.isoformat()}.jsonl").exists()


def test_purge_never_deletes_today(tmp_path):
    """Even with retention_days=0, today's file must survive — protects
    against fat-finger config wiping live logs."""
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    (tmp_path / f"{today.isoformat()}.jsonl").write_text("{}\n")
    (tmp_path / f"{yesterday.isoformat()}.jsonl").write_text("{}\n")

    purge_old_logs(tmp_path, retention_days=0)
    assert (tmp_path / f"{today.isoformat()}.jsonl").exists()
    assert not (tmp_path / f"{yesterday.isoformat()}.jsonl").exists()


def test_purge_ignores_non_jsonl_files(tmp_path):
    """README, backups, etc. in the log dir must not be touched."""
    (tmp_path / "README.md").write_text("# audit logs")
    (tmp_path / "2020-01-01.jsonl.bak").write_text("{}\n")
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "2020-01-01.jsonl").write_text("{}\n")  # 6 years old

    purge_old_logs(tmp_path, retention_days=30)

    assert (tmp_path / "README.md").exists()
    assert (tmp_path / "2020-01-01.jsonl.bak").exists()
    assert (tmp_path / "config.json").exists()
    assert not (tmp_path / "2020-01-01.jsonl").exists()  # only matching-pattern + old gets deleted


def test_purge_ignores_malformed_dates(tmp_path):
    (tmp_path / "2026-13-99.jsonl").write_text("{}\n")  # invalid date but matches regex
    (tmp_path / "abcd-ef-gh.jsonl").write_text("{}\n")  # doesn't match regex
    purge_old_logs(tmp_path, retention_days=30)
    # Files with invalid dates that match the regex would crash without the
    # try/except — assert they're left untouched, not deleted.
    assert (tmp_path / "2026-13-99.jsonl").exists()
    assert (tmp_path / "abcd-ef-gh.jsonl").exists()


def test_purge_empty_dir_no_op(tmp_path):
    """No files, no crash."""
    removed = purge_old_logs(tmp_path, retention_days=30)
    assert removed == []


def test_purge_missing_dir_no_op(tmp_path):
    """Pointing to a path that doesn't exist must not raise."""
    removed = purge_old_logs(tmp_path / "does-not-exist", retention_days=30)
    assert removed == []

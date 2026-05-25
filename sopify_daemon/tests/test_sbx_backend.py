"""SbxBackend parser tests — focus on snapshot diff + entry parsing.

We don't spawn `sbx` here; that's the contract test suite's job. Instead
we exercise the pure transforms with hand-crafted dicts in the shape
that ``sbx policy log --json`` produces (verified 2026-05-24).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sopify_daemon.sbx_backend import (
    AuditEvent,
    SbxBackend,
    _entry_to_event,
    _parse_rule,
)


def test_entry_to_event_basic():
    last_seen = datetime(2026, 5, 24, 3, 15, 31, tzinfo=timezone.utc)
    ev = _entry_to_event(
        {
            "host": "api.anthropic.com:443",
            "vm_name": "proj-alpha",
            "proxy_type": "transparent",
            "rule": "allow-anthropic",
            "decision": "allow",
        },
        last_seen,
    )
    assert ev.host == "api.anthropic.com"
    assert ev.port == 443
    assert ev.sandbox_id == "proj-alpha"
    assert ev.decision == "allow"
    assert ev.rule_id == "allow-anthropic"
    assert ev.proxy_mode == "transparent"
    assert ev.ts == last_seen


def test_entry_to_event_dial_failed_clears_rule():
    """sbx writes `rule: '<dial failed>'` when no rule applied (and
    connection failed). Treat that as no rule attribution."""
    ev = _entry_to_event(
        {
            "host": "evil.com:443",
            "vm_name": "proj-x",
            "proxy_type": "transparent",
            "rule": "<dial failed>",
            "decision": "deny",
        },
        datetime.now(timezone.utc),
    )
    assert ev.rule_id is None


def test_entry_to_event_host_without_port():
    """Some events lack a port — treat the whole string as host."""
    ev = _entry_to_event(
        {"host": "api.anthropic.com", "vm_name": "v", "decision": "allow"},
        datetime.now(timezone.utc),
    )
    # rpartition with no ":" gives empty host + "api.anthropic.com" as port;
    # the parser falls back to the original host string when host is empty
    assert "api.anthropic.com" in ev.host


def test_entry_to_event_ipv6_host():
    """`[fd7f::]:9118` — bracketed IPv6 + port. Best-effort kept-as-is."""
    last_seen = datetime.now(timezone.utc)
    ev = _entry_to_event(
        {"host": "[fd7f:c07d:b31::]:9118", "vm_name": "v", "decision": "allow"},
        last_seen,
    )
    assert "fd7f" in ev.host
    assert ev.port == 9118


def test_parse_rule_basic():
    r = _parse_rule({
        "id": "rule_abc",
        "name": "allow-x",
        "resource_type": "network",
        "decision": "allow",
        "resources": ["*.example.com"],
        "scope": "global",
        "origin": "local",
        "status": "active",
    })
    assert r.id == "rule_abc"
    assert r.name == "allow-x"
    assert r.resources == ("*.example.com",)


def test_parse_rule_missing_fields_safe_defaults():
    """sbx may add/remove fields between versions — parser must not crash."""
    r = _parse_rule({"id": "x"})
    assert r.id == "x"
    assert r.decision == "allow"  # safe default
    assert r.resources == ()
    assert r.resource_type == "network"


@pytest.mark.asyncio
async def test_tail_audit_log_snapshot_diff_emits_new_only(monkeypatch):
    """Two consecutive snapshots — second call only emits the host whose
    `last_seen` advanced."""
    backend = SbxBackend.__new__(SbxBackend)  # skip __init__ (no sbx needed)
    backend._client = None  # type: ignore[assignment]

    t1 = "2026-05-24T03:00:00+00:00"
    t2 = "2026-05-24T03:05:00+00:00"

    snapshots = [
        [  # first call — establishes the baseline
            {"host": "a.com:443", "vm_name": "v", "decision": "allow",
             "last_seen": t1, "proxy_type": "transparent", "rule": "allow-a"},
            {"host": "b.com:443", "vm_name": "v", "decision": "allow",
             "last_seen": t1, "proxy_type": "transparent", "rule": "allow-b"},
        ],
        [  # second call — a.com unchanged, b.com has fresh last_seen
            {"host": "a.com:443", "vm_name": "v", "decision": "allow",
             "last_seen": t1, "proxy_type": "transparent", "rule": "allow-a"},
            {"host": "b.com:443", "vm_name": "v", "decision": "allow",
             "last_seen": t2, "proxy_type": "transparent", "rule": "allow-b"},
        ],
    ]
    call_index = {"i": 0}

    async def fake_read(self):  # noqa: ANN001
        snap = snapshots[call_index["i"]]
        call_index["i"] += 1
        return snap

    monkeypatch.setattr(SbxBackend, "_read_audit_snapshot", fake_read)

    # First call — everything is "new"
    first: list[AuditEvent] = []
    async for ev in backend.tail_audit_log():
        first.append(ev)
    assert {ev.host for ev in first} == {"a.com", "b.com"}

    # Second call — only b.com should emit (a.com's last_seen didn't move)
    second: list[AuditEvent] = []
    async for ev in backend.tail_audit_log():
        second.append(ev)
    assert [ev.host for ev in second] == ["b.com"]


@pytest.mark.asyncio
async def test_tail_audit_log_since_filter(monkeypatch):
    """The `since` arg filters out anything older than the cutoff."""
    backend = SbxBackend.__new__(SbxBackend)
    backend._client = None  # type: ignore[assignment]

    t_old = "2026-05-24T02:00:00+00:00"
    t_new = "2026-05-24T03:00:00+00:00"
    snap = [
        {"host": "old.com:443", "vm_name": "v", "decision": "allow",
         "last_seen": t_old, "proxy_type": "transparent", "rule": "r"},
        {"host": "new.com:443", "vm_name": "v", "decision": "allow",
         "last_seen": t_new, "proxy_type": "transparent", "rule": "r"},
    ]

    async def fake_read(self):  # noqa: ANN001
        return list(snap)

    monkeypatch.setattr(SbxBackend, "_read_audit_snapshot", fake_read)

    cutoff = datetime(2026, 5, 24, 2, 30, tzinfo=timezone.utc)
    out = []
    async for ev in backend.tail_audit_log(since=cutoff):
        out.append(ev)
    assert {ev.host for ev in out} == {"new.com"}

"""Tests for the sessions.agent_kind column (Phase 4 token attribution).

Runnable under pytest OR directly:
    python tests/test_agent_kind_attribution.py
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hermes_state as hs  # noqa: E402


def test_default_hermes_and_record_claude_code():
    with tempfile.TemporaryDirectory() as t:
        db = hs.SessionDB(Path(t) / "state.db")
        # Hermes turn — no agent_kind passed, column default applies.
        db.update_token_counts("s_hermes", input_tokens=10, output_tokens=5)
        # Claude Code turn — explicitly attributed.
        db.update_token_counts("s_cc", input_tokens=100, output_tokens=40,
                               agent_kind="claude_code")
        assert db.get_session("s_hermes")["agent_kind"] == "hermes"
        cc = db.get_session("s_cc")
        assert cc["agent_kind"] == "claude_code"
        assert cc["input_tokens"] == 100 and cc["output_tokens"] == 40
    print("ok default_and_record")


def test_agent_kind_is_sticky():
    with tempfile.TemporaryDirectory() as t:
        db = hs.SessionDB(Path(t) / "state.db")
        db.update_token_counts("s", input_tokens=1, agent_kind="claude_code")
        # A later delta with no agent_kind must NOT reset it (COALESCE keeps it).
        db.update_token_counts("s", input_tokens=1)
        row = db.get_session("s")
        assert row["agent_kind"] == "claude_code"
        assert row["input_tokens"] == 2  # incremented
    print("ok sticky")


def test_migration_backfills_old_rows_to_hermes():
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / "state.db"
        # Simulate a realistic pre-Phase-4 DB: the full current schema with ONLY
        # the agent_kind column removed (so its indexes/other columns still
        # exist), plus a row already in it.
        old_schema = hs.SCHEMA_SQL.replace(
            "    agent_kind TEXT DEFAULT 'hermes',\n", "", 1
        )
        assert "agent_kind TEXT DEFAULT" not in old_schema  # column def removed
        conn = sqlite3.connect(str(p))
        conn.executescript(old_schema)
        conn.execute(
            "INSERT INTO sessions (id, source, started_at, input_tokens) "
            "VALUES ('old', 'cli', 123.0, 7)"
        )
        conn.commit()
        conn.close()
        # Opening via SessionDB runs _reconcile_columns, which ADDs agent_kind
        # with its DEFAULT — SQLite backfills the existing row to 'hermes'.
        db = hs.SessionDB(p)
        row = db.get_session("old")
        assert row["agent_kind"] == "hermes"
        assert row["input_tokens"] == 7  # untouched by the migration
    print("ok migration_backfill")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\nAll {len(fns)} tests passed.")

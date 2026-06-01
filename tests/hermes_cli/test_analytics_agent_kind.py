"""Test that /api/analytics/usage splits usage by agent_kind (PR 4.3).

Calls the real async endpoint against a temp DB (DEFAULT_DB_PATH redirected),
populated with one Hermes and one Claude Code session. Runnable under pytest
OR directly:
    python tests/hermes_cli/test_analytics_agent_kind.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import hermes_state as hs  # noqa: E402


def test_usage_breakdown_by_agent_kind():
    with tempfile.TemporaryDirectory() as t:
        dbpath = Path(t) / "state.db"
        orig = hs.DEFAULT_DB_PATH
        hs.DEFAULT_DB_PATH = dbpath
        try:
            db = hs.SessionDB(dbpath)
            db.update_token_counts("s_h", input_tokens=10, output_tokens=5)  # hermes (default)
            db.update_token_counts("s_c", input_tokens=100, output_tokens=40,
                                   agent_kind="claude_code")
            db.close()

            import hermes_cli.web_server as w
            res = asyncio.run(w.get_usage_analytics(days=30))
        finally:
            hs.DEFAULT_DB_PATH = orig

        assert "by_agent_kind" in res
        rows = {r["agent_kind"]: r for r in res["by_agent_kind"]}
        assert set(rows) == {"hermes", "claude_code"}
        assert rows["hermes"]["input_tokens"] == 10 and rows["hermes"]["output_tokens"] == 5
        assert rows["claude_code"]["input_tokens"] == 100
        assert rows["claude_code"]["output_tokens"] == 40
        assert rows["claude_code"]["sessions"] == 1
    print("ok breakdown_by_agent_kind")


if __name__ == "__main__":
    test_usage_breakdown_by_agent_kind()
    print("\nAll 1 tests passed.")

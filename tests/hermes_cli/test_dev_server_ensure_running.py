"""Tests for dev_server_manager.ensure_running (Claude Code dev-server persist).

Monkeypatches _revive_spec / find_pid_for_port so it runs on any OS without
/proc or spawning real processes. Runnable under pytest OR directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import hermes_cli.dev_server_manager as dsm  # noqa: E402


def test_ensure_running_registers_and_revives():
    revived = []
    orig_revive, orig_pid = dsm._revive_spec, dsm.find_pid_for_port
    dsm.find_pid_for_port = lambda port: None
    dsm._revive_spec = lambda spec: (revived.append(spec) or True)
    try:
        spec = dsm.ensure_running(
            "sk1", 5174, "http://localhost:5174/",
            "npm run dev", "/tmp/proj", vibe_project="proj",
        )
        assert spec is not None
        assert spec.port == 5174 and spec.command == "npm run dev"
        assert spec.cwd == "/tmp/proj" and spec.vibe_project == "proj"
        assert len(revived) == 1  # re-spawn attempted under the dashboard
    finally:
        dsm._revive_spec, dsm.find_pid_for_port = orig_revive, orig_pid
        dsm.remove_session("sk1")
    print("ok registers_and_revives")


def test_ensure_running_no_command_skips_revive():
    revived = []
    orig_revive, orig_pid = dsm._revive_spec, dsm.find_pid_for_port
    dsm.find_pid_for_port = lambda port: None
    dsm._revive_spec = lambda spec: (revived.append(spec) or True)
    try:
        dsm.ensure_running("sk2", 5174, "http://localhost:5174/", None, None)
        assert len(revived) == 0  # nothing to revive without command/cwd
    finally:
        dsm._revive_spec, dsm.find_pid_for_port = orig_revive, orig_pid
        dsm.remove_session("sk2")
    print("ok no_command_skips_revive")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\nAll {len(fns)} tests passed.")

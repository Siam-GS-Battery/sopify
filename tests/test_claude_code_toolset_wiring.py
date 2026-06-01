"""Guard that claude_code_task is wired into the core toolset.

A tool is only available to the agent if its name appears in an enabled
toolset's `tools` list — registering it isn't enough. This locks in that
claude_code_task reaches both interactive Hermes and cron (Surface B).

Runnable under pytest OR directly:
    python tests/test_claude_code_toolset_wiring.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import toolsets as T  # noqa: E402


def test_in_core_once():
    assert "claude_code_task" in T._HERMES_CORE_TOOLS
    assert T._HERMES_CORE_TOOLS.count("claude_code_task") == 1
    print("ok in_core_once")


def test_available_to_cli_and_cron():
    # Both interactive (hermes-cli) and scheduled (hermes-cron) surfaces must
    # expose it; cron is the whole point of Surface B.
    for ts in ("hermes-cli", "hermes-cron", "hermes-telegram", "hermes-discord"):
        assert "claude_code_task" in T.TOOLSETS[ts]["tools"], ts
    print("ok available_to_cli_and_cron")


def test_registered_in_registry():
    from tools.registry import registry, discover_builtin_tools
    discover_builtin_tools()
    assert "claude_code_task" in registry._tools
    assert registry._tools["claude_code_task"].toolset == "claude_code"
    print("ok registered")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\nAll {len(fns)} tests passed.")

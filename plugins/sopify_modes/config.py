"""Per-mode runtime configuration profiles.

Each profile is what the mode injects into Sopify's runtime: token budget,
deny-list level, parallel-tool-execution toggle, etc.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class ModeProfile:
    name: str
    daily_token_budget: int = 200_000
    require_approval_for_destructive: bool = False
    parallel_tool_execution: bool = True
    deny_list_level: str = "default"  # "default" | "strict"
    confirm_every_step: bool = False
    persistent_session: bool = False
    extras: Dict[str, object] = field(default_factory=dict)


# REQ-3.3 — /living
LIVING = ModeProfile(
    name="living",
    daily_token_budget=300_000,
    require_approval_for_destructive=True,
    parallel_tool_execution=False,           # REQ-3.3.3
    deny_list_level="strict",                # REQ-3.3.1
    persistent_session=True,                 # REQ-3.1.1
)

# REQ-4 — /vibe
VIBE = ModeProfile(
    name="vibe",
    daily_token_budget=200_000,
    require_approval_for_destructive=False,
    parallel_tool_execution=True,
    deny_list_level="default",
)

# REQ-5 — /code-with-you
CODE_WITH_YOU = ModeProfile(
    name="code-with-you",
    daily_token_budget=50_000,               # REQ-5.3.1
    require_approval_for_destructive=True,
    parallel_tool_execution=False,           # REQ-5.1.4
    deny_list_level="default",
    confirm_every_step=True,                 # REQ-5.1.1
)

PROFILES: Dict[str, ModeProfile] = {
    "living": LIVING,
    "vibe": VIBE,
    "code-with-you": CODE_WITH_YOU,
}


def get(mode: str) -> ModeProfile:
    return PROFILES.get(mode, ModeProfile(name=mode))

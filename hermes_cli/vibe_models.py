"""Shared per-phase model defaults + resolver for the Vibe Code surface.

Factored out of ``hermes_cli.web_server`` so the WebSocket gateway
(``tui_gateway.server``) can import the resolver without pulling in the
FastAPI app + its startup side effects. Both modules import the same
constants for parity.

The marker reader here returns ``None`` on any error rather than raising
``HTTPException`` — that exception class belongs to the FastAPI surface
and isn't meaningful inside the gateway process.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from hermes_constants import get_hermes_home


# Ordered phase machine. Six phases, each with a matching
# ``prompts/vibe/phases/<name>.md``.
VIBE_PHASES: list[str] = [
    "brainstorm",
    "design",
    "backend",
    "improvement",
    "security",
    "approve",
]


# Default model per phase per spec/VIBE_CODE_PANEL_SPEC.md §2-§3.
# Stored as ``<provider>/<model>`` strings so the resolver can split the pair
# without a second lookup. The per-project override
# (``project.json:model_per_phase``) wins when set.
VIBE_PHASE_MODEL_DEFAULTS: dict[str, str] = {
    "brainstorm":  "anthropic/claude-sonnet-4-6",
    "design":      "anthropic/claude-sonnet-4-6",
    "backend":     "alibaba/qwen3-coder-plus",
    "improvement": "alibaba/qwen3-coder-plus",
    "security":    "anthropic/claude-sonnet-4-6",
    "approve":     "alibaba/qwen-plus",
}


# Curated catalog returned by the GET /api/vibe/projects/{name}/models
# endpoint. Keep the list short — adding a new entry here is the canonical
# way to expose a new model to the Vibe Code picker.
VIBE_AVAILABLE_MODELS: list[dict] = [
    # Anthropic — taste/security/scope
    {"id": "anthropic/claude-opus-4-7",   "provider": "anthropic", "label": "Claude Opus 4.7"},
    {"id": "anthropic/claude-sonnet-4-6", "provider": "anthropic", "label": "Claude Sonnet 4.6"},
    {"id": "anthropic/claude-haiku-4-5",  "provider": "anthropic", "label": "Claude Haiku 4.5"},
    # Alibaba Model Studio — coding/general/OSS
    {"id": "alibaba/qwen3-coder-plus",    "provider": "alibaba",   "label": "Qwen3 Coder Plus"},
    {"id": "alibaba/qwen3.6-plus",        "provider": "alibaba",   "label": "Qwen 3.6 Plus"},
    {"id": "alibaba/qwen-plus",           "provider": "alibaba",   "label": "Qwen Plus"},
    {"id": "alibaba/kimi-k2.6",           "provider": "alibaba",   "label": "Kimi K2.6 (via Alibaba)"},
    {"id": "alibaba/deepseek-v4-pro",     "provider": "alibaba",   "label": "DeepSeek V4 Pro (via Alibaba)"},
]


def resolve_vibe_phase_model(marker: dict, phase: Optional[str] = None) -> str:
    """Return the effective ``<provider>/<model>`` string for a project phase.

    Looks up ``model_per_phase`` on the marker first; falls back to
    ``VIBE_PHASE_MODEL_DEFAULTS``. If ``phase`` is omitted, uses the
    marker's current ``phase`` field. Unknown phase strings fall through to
    the ``brainstorm`` default so a bogus marker never crashes the resolver.
    """
    if phase is None:
        phase = marker.get("phase", "brainstorm")
    overrides = marker.get("model_per_phase") or {}
    return overrides.get(phase) or VIBE_PHASE_MODEL_DEFAULTS.get(
        phase, VIBE_PHASE_MODEL_DEFAULTS["brainstorm"]
    )


_VIBE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def vibe_projects_root() -> Path:
    return get_hermes_home() / "vibe-projects"


def vibe_project_dir(name: str) -> Optional[Path]:
    """Resolve a project dir, rejecting traversal / unknown names.

    Returns ``None`` (not an exception) so the gateway can branch on
    "no vibe context" without catching anything.
    """
    if not _VIBE_NAME_RE.match(name):
        return None
    root = vibe_projects_root()
    try:
        d = (root / name).resolve()
        d.relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    if not d.is_dir():
        return None
    return d


def read_vibe_marker(name: str) -> Optional[dict]:
    """Read project.json for a vibe project. Returns ``None`` on any error."""
    d = vibe_project_dir(name)
    if d is None:
        return None
    f = d / "project.json"
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# project.json field holding the resumable Claude Code session id for this
# project. This is what makes Claude Code "remember where it was" across turns
# and dashboard reloads (concern Q3): the gateway pins a session id on the
# first turn (claude_code_runner.new_session_id) and ``--resume``s it after.
CLAUDE_SESSION_FIELD = "claude_code_session_id"


def get_claude_session_id(name: str) -> Optional[str]:
    """Return the project's stored Claude Code session id, or None."""
    marker = read_vibe_marker(name)
    if not marker:
        return None
    sid = marker.get(CLAUDE_SESSION_FIELD)
    return sid if isinstance(sid, str) and sid else None


def set_claude_session_id(name: str, session_id: str) -> bool:
    """Persist ``session_id`` into the project's project.json. Returns success.

    Merges into the existing marker (never clobbers other fields) and writes
    atomically (temp + replace) so a crash mid-write can't corrupt the marker.
    Returns False for an unknown/invalid project or a write error rather than
    raising — the caller is the gateway, where an exception would kill a turn.
    """
    d = vibe_project_dir(name)
    if d is None:
        return False
    f = d / "project.json"
    try:
        marker = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    except (json.JSONDecodeError, OSError):
        marker = {}
    if not isinstance(marker, dict):
        marker = {}
    marker[CLAUDE_SESSION_FIELD] = session_id
    tmp = f.with_name(f.name + ".tmp")
    try:
        tmp.write_text(json.dumps(marker, indent=2), encoding="utf-8")
        tmp.replace(f)
        return True
    except OSError:
        return False

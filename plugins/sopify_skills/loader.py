"""Sopify skill loader.

Discovers SKILL.md files from three sources (in last-writer-wins order per
REQ-8.2.3):

  1. Bundled sopify_skills/ at the repo root
  2. Claude Code skills at ~/.claude/skills/  (REQ-8.2.1)
  3. Project-local .sopify/skills/  (REQ-8.1.7)

Each SKILL.md is parsed for its YAML front-matter and the `applies_to` field.
`skills_for_mode(mode)` returns the subset that should be injected for a given
mode (REQ-8.1.6).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Skill:
    name: str
    path: Path
    description: str = ""
    applies_to: List[str] = field(default_factory=list)
    phase_gate: int = 0  # REQ-8.1.5 — gs-mad gated at phase 7
    raw: str = ""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _yaml_block(text: str) -> str:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    return m.group(1) if m else ""


def _parse(text: str, path: Path) -> Skill:
    block = _yaml_block(text)
    fields: Dict[str, object] = {}
    for line in block.splitlines():
        if ":" in line and not line.lstrip().startswith("-"):
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip()
    # metadata.applies_to is a nested key; parse it loosely.
    applies = []
    m = re.search(r"applies_to:\s*\[(.*?)\]", block)
    if m:
        applies = [a.strip().strip('"').strip("'") for a in m.group(1).split(",") if a.strip()]
    phase = 0
    pm = re.search(r"phase_gate:\s*(\d+)", block)
    if pm:
        phase = int(pm.group(1))
    name = str(fields.get("name") or path.parent.name)
    desc = str(fields.get("description") or "")
    return Skill(name=name, path=path, description=desc,
                 applies_to=applies, phase_gate=phase, raw=text)


def _walk(root: Path) -> List[Skill]:
    out: List[Skill] = []
    if not root.exists():
        return out
    for skill_md in root.rglob("SKILL.md"):
        try:
            out.append(_parse(skill_md.read_text(), skill_md))
        except Exception:
            continue
    return out


def _current_phase() -> int:
    import json
    p = os.path.join(
        os.environ.get("SOPIFY_HOME") or os.path.expanduser("~/.sopify"),
        "settings.json",
    )
    if os.path.exists(p):
        try:
            return int(json.loads(open(p).read()).get("phase", 1))
        except Exception:
            return 1
    return 1


def all_skills() -> Dict[str, Skill]:
    """Return name -> Skill, applying last-writer-wins precedence."""
    skills: Dict[str, Skill] = {}

    # Source 1: bundled (lowest precedence)
    for s in _walk(_repo_root() / "sopify_skill_bundles"):
        skills[s.name] = s

    # Source 2: ~/.claude/skills (Claude Code compat)
    claude_home = Path(os.path.expanduser("~/.claude/skills"))
    for s in _walk(claude_home):
        skills[s.name] = s  # override bundled if name matches

    # Source 3: project-local .sopify/skills/ (highest)
    project_skills = Path.cwd() / ".sopify" / "skills"
    for s in _walk(project_skills):
        skills[s.name] = s

    # REQ-8.1.5 — phase gate
    cur_phase = _current_phase()
    return {n: s for n, s in skills.items() if s.phase_gate <= cur_phase}


def skills_for_mode(mode: str) -> List[Skill]:
    """REQ-8.1.6 — return the bundles the mode should inject."""
    selected: List[Skill] = []
    for s in all_skills().values():
        if not s.applies_to or mode in s.applies_to:
            # company-sop has applies_to=["vibe","living","code-with-you"];
            # an empty applies_to means "everywhere".
            if not s.applies_to or mode in s.applies_to:
                selected.append(s)
    # Stable ordering: org-context first, then persona, then workflow.
    selected.sort(key=lambda s: (s.name != "company-sop", s.name))
    return selected


def render_system_prompt(mode: str) -> str:
    """Join all matching SKILL.md bodies into one system-prompt block."""
    parts: List[str] = []
    for s in skills_for_mode(mode):
        body = re.sub(r"^---\n.*?\n---\n", "", s.raw, count=1, flags=re.DOTALL)
        parts.append(f"# Skill: {s.name}\n{body}")
    return "\n\n".join(parts)

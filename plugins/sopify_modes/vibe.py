"""/vibe mode — guided app builder.

REQ-4.1.1 — structured intake (goal / data / target / output).
REQ-4.1.2 — restate + propose 2-3 approaches before coding.
REQ-4.1.3 — implementation starts only after user approves an approach.
REQ-4.2.1 — every brainstorm gets its own session branch.
REQ-4.4.1 — app_fingerprint computed per session for promotion gate.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class IntakeAnswers:
    goal: str = ""
    data_source: str = ""
    target_user: str = ""
    output_format: str = ""

    @property
    def complete(self) -> bool:
        return all([self.goal, self.data_source, self.target_user, self.output_format])


INTAKE_QUESTIONS: List[str] = [
    "อยากได้อะไร? (What do you want the app to do?)",
    "ใช้ข้อมูลอะไร? (What data does it use?)",
    "ใครจะใช้? (Who will use it?)",
    "ต้องการ output แบบไหน? (What output format?)",
]


@dataclass
class Approach:
    label: str
    summary: str
    tradeoff: str


def app_fingerprint(project_dir: Path | None = None) -> str:
    """REQ-4.4.1 — hash project structure (sorted relative paths).

    Stable enough to detect the same app shape across sessions; coarse enough
    not to change for minor edits.
    """
    project_dir = project_dir or Path.cwd()
    paths: List[str] = []
    for root, dirs, files in os.walk(project_dir):
        # Skip hidden + common cruft so churn doesn't break the fingerprint.
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in
                   ("node_modules", "__pycache__", "venv", ".venv", "dist", "build")]
        for f in files:
            if f.startswith(".") or f.endswith((".pyc", ".log")):
                continue
            paths.append(os.path.relpath(os.path.join(root, f), project_dir))
    paths.sort()
    return hashlib.sha256("\n".join(paths).encode()).hexdigest()


def render_intake_prompt(answered: IntakeAnswers) -> str:
    """Return the next question or None if intake is done."""
    if answered.complete:
        return ""
    if not answered.goal:
        return INTAKE_QUESTIONS[0]
    if not answered.data_source:
        return INTAKE_QUESTIONS[1]
    if not answered.target_user:
        return INTAKE_QUESTIONS[2]
    return INTAKE_QUESTIONS[3]


def restate(answers: IntakeAnswers) -> str:
    """REQ-4.1.2 — short restatement + 2-3 approach proposals."""
    if not answers.complete:
        return ""
    return (
        f"Let me check I've got this right.\n\n"
        f"You want **{answers.goal}** using **{answers.data_source}**, "
        f"for **{answers.target_user}**, with the result shown as "
        f"**{answers.output_format}**.\n\n"
        f"Here are three ways I could build it — pick one and I'll start."
    )

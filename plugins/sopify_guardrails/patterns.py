"""
HARD_DENY and SOFT_DENY pattern tables.

Mirrors the table in DESIGN_ARCHITECTURE.md §REQ-6.1.2 and §REQ-6.2.1.
Patterns are compiled at import time so the hot path is just regex match.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Pattern


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: Pattern[str]
    reason: str


# REQ-6.1.2 — every entry here is non-negotiable, blocked for every role.
HARD_DENY: List[Rule] = [
    Rule("rm-rf-root",
         re.compile(r"\brm\s+-rf\s+(/|~|\$HOME)(\s|$)"),
         "Recursive delete root/home"),
    Rule("drop-database",
         re.compile(r"\bDROP\s+DATABASE\b", re.IGNORECASE),
         "Drop database"),
    Rule("drop-table-no-where",
         re.compile(r"\bDROP\s+TABLE\s+\w+\s*;", re.IGNORECASE),
         "Drop table without WHERE"),
    Rule("fork-bomb",
         re.compile(r":\(\)\s*\{\s*:\|:&\s*\};?:"),
         "Fork bomb"),
    Rule("mkfs",
         re.compile(r"\bmkfs\.[a-z0-9]+\b"),
         "Format filesystem"),
    Rule("dd-block-device",
         re.compile(r"\bdd\b[^|]*\bof=/dev/sd"),
         "Overwrite block device"),
    Rule("chmod-777-root",
         re.compile(r"\bchmod\s+-R\s+777\s+/(\s|$)"),
         "World-write root"),
    Rule("system-shutdown",
         re.compile(r"\b(shutdown|reboot|halt|poweroff)\b"),
         "System shutdown command"),
]


# REQ-6.2.1 — user: block. dev: confirm.
SOFT_DENY: List[Rule] = [
    Rule("delete-no-where",
         re.compile(r"\bDELETE\s+FROM\s+\w+\s*;", re.IGNORECASE),
         "DELETE without WHERE clause"),
    Rule("truncate",
         re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE),
         "TRUNCATE TABLE"),
    Rule("rm-rf-any",
         re.compile(r"\brm\s+-rf\s+\S+"),
         "Recursive delete"),
    Rule("git-force-push",
         re.compile(r"\bgit\s+push\s+.*--force\b"),
         "git push --force"),
    Rule("curl-pipe-shell",
         re.compile(r"\b(curl|wget)\s+\S+\s*\|\s*(bash|sh)\b"),
         "Pipe download to shell"),
]


def first_match(rules: List[Rule], command: str) -> Rule | None:
    for r in rules:
        if r.pattern.search(command):
            return r
    return None

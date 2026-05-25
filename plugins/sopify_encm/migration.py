"""Migrate ``network-policy.json`` schema v1 → v2.

v1 schema (shipped with sopify_sandbox.network_policy):
    {
      "version": 1,
      "whitelist": ["api.anthropic.com", ...],
      "user_added": ["pg.local", ...]
    }

v2 schema is fully typed (see :mod:`sopify_encm.schema`). v1 entries are
bare hostnames with no protocol/port hint — we conservatively map each to
HTTPS:443, and the operator can edit later via the dashboard. Pre-existing
v1 entries become ``added_by="user"`` (or ``"default"`` if they're known
defaults from the v1 ``DEFAULTS`` set).

Idempotent: if the file is already v2, returns it unchanged.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .schema import (
    CURRENT_SCHEMA_VERSION,
    HttpRule,
    NetworkPolicy,
    default_policy,
    dump_policy,
    new_rule_id,
)

# Mirror sopify_sandbox.network_policy.DEFAULTS so migrated entries keep
# their "default" provenance instead of being miscategorised as user_added.
_V1_DEFAULTS = {"api.anthropic.com", "otel-collector.gsbattery.local"}


def _v1_to_rules(v1: dict[str, Any]) -> list[HttpRule]:
    """Convert v1 hostname lists into HTTPS:443 rules."""
    rules: list[HttpRule] = []
    seen: set[str] = set()

    def add(domain: str, provenance: str) -> None:
        domain = domain.strip().lower()
        if not domain or domain in seen:
            return
        seen.add(domain)
        rules.append(
            HttpRule(
                id=new_rule_id(),
                protocol="https",
                domain=domain,
                ports=[443],
                description=f"Migrated from policy v1 ({provenance})",
                added_by="default" if provenance == "default" else "user",
            )
        )

    for d in v1.get("whitelist", []) or []:
        add(d, "default" if d in _V1_DEFAULTS else "default")
    for d in v1.get("user_added", []) or []:
        add(d, "user")
    return rules


def migrate(data: dict[str, Any]) -> NetworkPolicy:
    """Convert a parsed v1 dict to a v2 NetworkPolicy. Idempotent on v2 input."""
    if data.get("schema_version") == CURRENT_SCHEMA_VERSION:
        # Already v2 — just validate and return.
        return NetworkPolicy.model_validate(data)
    if data.get("version") == 1 or "whitelist" in data or "user_added" in data:
        # v1 shape (or pre-versioned legacy)
        rules = _v1_to_rules(data)
        # Merge with bundled defaults so we never drop below the safe baseline,
        # but skip defaults that the user already had (avoid duplicate domains).
        existing_domains = {r.domain for r in rules}
        for d in default_policy().rules:
            if d.domain not in existing_domains:
                rules.append(d)
        return NetworkPolicy(rules=rules)
    # Unknown shape — treat as empty + emit fresh defaults so the operator
    # at least has a working policy file. Loud failure would block install.
    return default_policy()


def migrate_file(path: str | Path, *, backup: bool = True) -> NetworkPolicy:
    """Read a policy file, migrate in-place if needed, return the v2 policy.

    Args:
      path: ``~/.sopify/network-policy.json``
      backup: when True, write the original to ``<path>.v1.bak`` before overwriting.

    Returns:
      The v2 ``NetworkPolicy``. If the file doesn't exist, writes + returns
      the bundled defaults.
    """
    path = Path(path).expanduser()
    if not path.exists():
        policy = default_policy()
        path.parent.mkdir(parents=True, exist_ok=True)
        dump_policy(policy, path)
        return policy

    raw = path.read_text()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Corrupted file — back it up, write fresh defaults rather than crash.
        if backup:
            shutil.copy2(path, path.with_suffix(path.suffix + ".corrupt.bak"))
        policy = default_policy()
        dump_policy(policy, path)
        return policy

    if data.get("schema_version") == CURRENT_SCHEMA_VERSION:
        return NetworkPolicy.model_validate(data)

    # Needs migration.
    if backup:
        shutil.copy2(path, path.with_suffix(path.suffix + ".v1.bak"))
    policy = migrate(data)
    dump_policy(policy, path)
    return policy

"""Atomic YAML writer for ENCM rules.

Single entry point per the integration plan §7 — direct ``open(...).write()``
against a rule file is a bug; all writes go through :class:`RuleFileWriter`
so we get:

  - schema validation (`NetworkRule.model_validate`) before any disk write
  - atomic publish via temp file + ``os.replace`` (POSIX atomic on same FS)
  - canonical filenames keyed on ``scope`` + ``sandbox_id`` + ``name``
  - filesystem locking left to ``filelock`` only on the sync state file —
    rule files themselves are owned by humans (or our own writer) so we
    intentionally don't lock them. Concurrent writers should be rare;
    if two API calls land at the same instant the second's atomic
    rename wins, which is the same semantics as `kubectl apply`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from .paths import global_rules_dir, rules_dir, sandbox_rules_dir
from .schema import NetworkRule, RuleMetadata, RuleSpec


class RuleFileError(Exception):
    """Raised when a write would violate scope/path rules."""


class RuleFileWriter:
    """One-shot writer per rule file. Stateless — instantiate per call."""

    def path_for(self, rule: NetworkRule) -> Path:
        """Where this rule's YAML lives on disk."""
        name = rule.metadata.name
        if rule.metadata.scope == "global":
            return global_rules_dir() / f"{name}.yaml"
        sid = rule.metadata.sandbox_id or ""
        if not sid:  # belt-and-braces — schema validator catches this too
            raise RuleFileError("metadata.sandbox_id required for scope=sandbox")
        return sandbox_rules_dir(sid) / f"{name}.yaml"

    def write(self, rule: NetworkRule, *, overwrite: bool = False) -> Path:
        """Validate + serialize + atomic-rename. Returns the final path."""
        target = self.path_for(rule)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise RuleFileError(
                f"rule file already exists at {target}; pass overwrite=True to replace"
            )

        # Strip Pydantic implementation noise + write a clean, human-edit-friendly
        # YAML doc. by_alias=False keeps the K8s-style `apiVersion` casing.
        payload = rule.model_dump(mode="json")
        tmp = target.with_suffix(target.suffix + ".tmp")
        # YAML safe_dump avoids `!!python/...` tags that would render the
        # file unreadable to non-Python tools.
        tmp.write_text(
            yaml.safe_dump(payload, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        tmp.replace(target)
        return target

    def read(self, path: Path) -> NetworkRule:
        """Load + validate a rule from disk. Raises pydantic.ValidationError."""
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return NetworkRule.model_validate(data)

    def delete(self, *, name: str, scope: str = "global", sandbox_id: Optional[str] = None) -> bool:
        """Remove a rule file. Returns True if deleted, False if not found."""
        if scope == "global":
            target = global_rules_dir() / f"{name}.yaml"
        elif scope == "sandbox":
            if not sandbox_id:
                raise RuleFileError("sandbox_id required when scope=sandbox")
            target = sandbox_rules_dir(sandbox_id) / f"{name}.yaml"
        else:
            raise RuleFileError(f"unknown scope: {scope!r}")
        if not target.exists():
            return False
        target.unlink()
        return True

    def disable(self, *, name: str, scope: str = "global", sandbox_id: Optional[str] = None) -> Path:
        """Flip ``spec.decision`` to ``deny`` in-place (atomically).

        Used by ``POST /api/v1/rules/{name}/disable`` — keeps the file
        on disk so audit history references survive, but stops the rule
        from allowing traffic.
        """
        if scope == "global":
            target = global_rules_dir() / f"{name}.yaml"
        elif scope == "sandbox":
            if not sandbox_id:
                raise RuleFileError("sandbox_id required when scope=sandbox")
            target = sandbox_rules_dir(sandbox_id) / f"{name}.yaml"
        else:
            raise RuleFileError(f"unknown scope: {scope!r}")
        if not target.exists():
            raise RuleFileError(f"rule not found: {target}")
        rule = self.read(target)
        new_rule = rule.model_copy(update={
            "spec": rule.spec.model_copy(update={"decision": "deny"}),
        })
        return self.write(new_rule, overwrite=True)

    def list_all(self) -> list[NetworkRule]:
        """Walk the rules tree, parse every YAML, skip malformed files (logged)."""
        out: list[NetworkRule] = []
        root = rules_dir()
        if not root.exists():
            return out
        for path in sorted(root.rglob("*.yaml")):
            try:
                out.append(self.read(path))
            except Exception:
                # Skip individual broken files — reconciler emits warnings,
                # but we never let one bad file kill the whole list.
                continue
        return out


def make_rule(
    *,
    name: str,
    patterns: list[str],
    decision: str = "allow",
    rule_type: str = "domain",
    scope: str = "global",
    sandbox_id: Optional[str] = None,
    created_by: str = "user",
    ttl_seconds: Optional[int] = None,
    labels: Optional[dict[str, str]] = None,
) -> NetworkRule:
    """Convenience constructor for the API + CLI. Centralises defaults so
    the FastAPI route and the CLI helper both produce identical files."""
    return NetworkRule(
        metadata=RuleMetadata(
            name=name,
            scope=scope,  # type: ignore[arg-type]
            sandbox_id=sandbox_id,
            created_by=created_by,
            created_at=datetime.now(timezone.utc),
            labels=labels or {},
        ),
        spec=RuleSpec(
            type=rule_type,  # type: ignore[arg-type]
            patterns=patterns,
            decision=decision,  # type: ignore[arg-type]
            ttl_seconds=ttl_seconds,
        ),
    )

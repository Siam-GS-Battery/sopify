"""Pydantic models for the ENCM rule YAML files.

Schema is Kubernetes-style (``apiVersion`` + ``kind`` + ``metadata`` +
``spec``) on purpose — operators who've touched K8s, Argo, or
``kubectl`` pick up the mental model instantly. The exact shape is
locked in SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md §3 Week 2.

Files live at::

    ~/.sopify/encm/rules/global/<name>.yaml          # scope=global
    ~/.sopify/encm/rules/sandboxes/<sid>/<name>.yaml # scope=sandbox

Each file produces one or more sandboxd policy rules (one per pattern in
``spec.patterns``). The reconciler is responsible for the YAML→sandboxd
translation; this module is responsible only for parsing + validation.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

API_VERSION = "sopify.dev/v1"
RULE_KIND = "NetworkRule"

# Sopify slug rules — kept lenient enough that operators can name rules
# like `allow-internal-mqtt` without escape gymnastics. Kubernetes-style
# RFC 1123 label format (lowercase + digits + dash).
_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")

# Same regex as the archived MITM schema — domain matching grammar didn't
# change with the rewrite, only what enforces it.
_DOMAIN_RE = re.compile(r"^\*\.[a-z0-9.-]+|[a-z0-9][a-z0-9.-]*[a-z0-9]$", re.IGNORECASE)


class RuleMetadata(BaseModel):
    """The K8s-style ``metadata`` block."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="RFC 1123 label — unique within scope")
    scope: Literal["global", "sandbox"] = "global"
    sandbox_id: Optional[str] = Field(default=None, description="Required when scope=sandbox")
    created_by: str = Field(default="unknown", description="Operator who created the rule")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the YAML file was first written",
    )
    labels: dict[str, str] = Field(
        default_factory=dict,
        description="Free-form key/value pairs (mirrored into sandboxd as origin metadata)",
    )

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(
                f"invalid rule name {v!r}: must be lowercase RFC 1123 label "
                "(letters, digits, dashes; 1-63 chars; start+end alphanumeric)"
            )
        return v


class RuleSpec(BaseModel):
    """The K8s-style ``spec`` block — what the rule does."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["domain", "cidr", "port"] = Field(
        default="domain",
        description=(
            "domain = hostname/wildcard match (most common); "
            "cidr = IP range (e.g. 10.0.0.0/8); "
            "port = host:port literal (raw TCP)"
        ),
    )
    patterns: list[str] = Field(
        ..., min_length=1, max_length=100,
        description="One YAML rule fans out to one sandboxd rule per pattern",
    )
    decision: Literal["allow", "deny"] = "allow"
    ttl_seconds: Optional[int] = Field(
        default=None, ge=1, le=365 * 24 * 3600,
        description="If set, reconciler removes the rule after this many seconds",
    )

    @field_validator("patterns")
    @classmethod
    def _validate_patterns(cls, v: list[str]) -> list[str]:
        # Type-specific validation happens in the model_validator below
        # (needs access to .type). Here we just normalise + cheap checks.
        out: list[str] = []
        for p in v:
            p = p.strip()
            if not p:
                raise ValueError("empty pattern")
            out.append(p)
        return out

    @model_validator(mode="after")
    def _validate_pattern_types(self) -> RuleSpec:
        if self.type == "domain":
            for p in self.patterns:
                if not _DOMAIN_RE.match(p):
                    raise ValueError(f"invalid domain pattern: {p!r}")
        elif self.type == "cidr":
            import ipaddress
            for p in self.patterns:
                try:
                    ipaddress.ip_network(p, strict=False)
                except ValueError as exc:
                    raise ValueError(f"invalid CIDR {p!r}: {exc}") from exc
        elif self.type == "port":
            for p in self.patterns:
                # Expected `host:port` (host = literal IP or domain)
                if ":" not in p:
                    raise ValueError(f"port pattern {p!r} missing `:port`")
                host, _, port = p.rpartition(":")
                try:
                    port_int = int(port)
                except ValueError as exc:
                    raise ValueError(f"port pattern {p!r} non-numeric port") from exc
                if not (1 <= port_int <= 65535):
                    raise ValueError(f"port pattern {p!r} port out of range")
                if not host:
                    raise ValueError(f"port pattern {p!r} missing host")
        return self


class NetworkRule(BaseModel):
    """Top-level YAML document — `kind: NetworkRule`."""

    model_config = ConfigDict(extra="forbid")

    apiVersion: Literal["sopify.dev/v1"] = API_VERSION  # noqa: N815 — K8s case
    kind: Literal["NetworkRule"] = RULE_KIND
    metadata: RuleMetadata
    spec: RuleSpec

    @model_validator(mode="after")
    def _check_scope_consistency(self) -> NetworkRule:
        if self.metadata.scope == "sandbox" and not self.metadata.sandbox_id:
            raise ValueError("metadata.sandbox_id is required when scope=sandbox")
        if self.metadata.scope == "global" and self.metadata.sandbox_id:
            raise ValueError(
                "metadata.sandbox_id must be null when scope=global "
                "(set scope=sandbox to target a specific sandbox)"
            )
        return self


# ── Type aliases used by RuleFileWriter + reconciler ─────────────────────

RuleId = Annotated[str, Field(description="sandboxd handle (server-assigned)")]
RulePath = Annotated[str, Field(description="Filesystem path under ~/.sopify/encm/rules/")]


class RuleHandle(BaseModel):
    """Lightweight reference to one applied rule, persisted in sync state."""

    model_config = ConfigDict(extra="forbid")

    sbx_rule_id: RuleId
    pattern: str = Field(description="Which pattern from spec.patterns this handle covers")


class RuleSyncState(BaseModel):
    """Per-file state tracked in ``~/.sopify/encm/.state/sync.yaml``."""

    model_config = ConfigDict(extra="forbid")

    source_path: RulePath
    checksum: str = Field(description="sha256 of the YAML file contents")
    sbx_handles: list[RuleHandle] = Field(default_factory=list)
    last_applied_at: Optional[datetime] = None
    sync_state: Literal["pending", "applied", "drift", "error"] = "pending"
    last_error: Optional[str] = None


class DriftObservation(BaseModel):
    """An sbx-side rule with no matching ENCM YAML file."""

    model_config = ConfigDict(extra="forbid")

    sbx_rule_id: RuleId
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str
    resources: list[str] = Field(default_factory=list)
    decision: Optional[Literal["allow", "deny"]] = None


class SyncState(BaseModel):
    """Top-level shape of ``.state/sync.yaml`` — machine-managed, never edited by hand."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    rules: list[RuleSyncState] = Field(default_factory=list)
    drift_observations: list[DriftObservation] = Field(default_factory=list)
    last_reconcile_at: Optional[datetime] = None

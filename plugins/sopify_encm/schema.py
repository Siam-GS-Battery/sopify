"""Pydantic models for network-policy.json schema v2.

See ``docs/sopify/REQ-ENCM-M1.md`` §3 for the full schema.

Design notes:
  - ``Rule`` is a discriminated union keyed by ``protocol``. Each protocol
    has its own ``*Rule`` class so validators stay narrow.
  - IDs are ULID-shaped (26 chars) but we accept any non-empty string so
    legacy/manual edits don't break.
  - ``default_action`` is locked to ``"deny"`` for M1 — REQ-1.2 requires
    default-deny. Schema validates it but doesn't allow ``"allow"``.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CURRENT_SCHEMA_VERSION = 2

# Limits chosen to bound JSON size and audit-log growth; raise via PR if a
# real workload hits them.
MAX_RULES_PER_FILE = 500
MAX_PATHS_PER_RULE = 50
MAX_TOPICS_PER_RULE = 100

# Glob/wildcard patterns for hostname matching — `*.example.com` matches
# any subdomain, plain `example.com` matches exact only. No regex here so
# users can't accidentally allow `.*` style catch-alls.
_DOMAIN_RE = re.compile(r"^\*\.[a-z0-9.-]+|[a-z0-9][a-z0-9.-]*[a-z0-9]$", re.IGNORECASE)


class _BaseRule(BaseModel):
    """Shared rule fields across protocols."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    id: str = Field(default="", description="ULID-shaped unique ID — auto-filled on save if blank")
    domain: str = Field(..., description="Hostname or `*.domain.tld` wildcard")
    ports: list[int] = Field(..., min_length=1, description="Allowed destination ports")
    description: str = Field(default="", max_length=500)
    added_by: Literal["default", "user", "dev", "it_admin"] = "user"
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    managed: bool = Field(default=False, description="True = MDM-managed, user cannot edit")
    tags: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("domain")
    @classmethod
    def _check_domain(cls, v: str) -> str:
        v = v.strip().lower()
        if not _DOMAIN_RE.match(v):
            raise ValueError(f"invalid domain pattern: {v!r}")
        return v

    @field_validator("ports")
    @classmethod
    def _check_ports(cls, v: list[int]) -> list[int]:
        for p in v:
            if not (1 <= p <= 65535):
                raise ValueError(f"port {p} out of range 1..65535")
        return v


class HttpRule(_BaseRule):
    """HTTP or HTTPS rule. mitmproxy enforces method + path matching."""

    protocol: Literal["http", "https"]
    methods: list[Literal["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]] = Field(
        default_factory=lambda: ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
    )
    paths_allow: list[str] = Field(default_factory=list, max_length=MAX_PATHS_PER_RULE)
    paths_deny: list[str] = Field(default_factory=list, max_length=MAX_PATHS_PER_RULE)
    rate_limit_per_min: int | None = Field(default=None, ge=1, le=100_000)
    log_payload: bool = Field(default=False, description="Log req+resp bodies (opt-in per rule)")


class WebSocketRule(_BaseRule):
    """WebSocket upgrade pass-through. Frame contents not inspected by default."""

    protocol: Literal["ws", "wss"]
    rate_limit_per_min: int | None = Field(default=None, ge=1, le=100_000)
    log_messages: bool = Field(default=False, description="Log frame count + size (not contents)")


class MqttRule(_BaseRule):
    """MQTT broker proxy with topic ACL. Topics use MQTT wildcards: + (single), # (multi)."""

    protocol: Literal["mqtt", "mqtts"]
    topics_allow: list[str] = Field(default_factory=list, max_length=MAX_TOPICS_PER_RULE)
    topics_deny: list[str] = Field(default_factory=lambda: ["#"], max_length=MAX_TOPICS_PER_RULE)
    qos_max: Literal[0, 1, 2] = 1
    log_messages: bool = Field(default=False)

    @field_validator("topics_allow", "topics_deny")
    @classmethod
    def _validate_topic_filter(cls, v: list[str]) -> list[str]:
        for t in v:
            # MQTT spec: + matches single level, # matches all remaining (must be last)
            if "#" in t and not t.endswith("#"):
                raise ValueError(f"topic filter {t!r}: `#` must be at the end")
            if not t or any(c in t for c in "\x00 "):
                raise ValueError(f"topic filter {t!r}: empty or contains illegal char")
        return v


class QueryFilter(BaseModel):
    """SQL/Redis query-level filter applied for Non-Dev role."""

    model_config = ConfigDict(extra="forbid")

    non_dev_block: list[str] = Field(
        default_factory=lambda: [
            "DROP", "TRUNCATE", "ALTER", "GRANT", "REVOKE",
            "DELETE_WITHOUT_WHERE", "UPDATE_WITHOUT_WHERE",
        ],
        description="SQL keyword patterns blocked for role=user; role=dev bypasses",
    )
    log_queries: bool = False


class TcpRule(_BaseRule):
    """Raw TCP forward (PostgreSQL/MySQL/Redis). Wire-level parser optional."""

    protocol: Literal["tcp"]
    wire_protocol: Literal["postgresql", "mysql", "redis", "raw"] = "raw"
    query_filter: QueryFilter | None = None


# Discriminated union — Pydantic picks the right subclass based on `protocol`.
Rule = Annotated[
    HttpRule | WebSocketRule | MqttRule | TcpRule,
    Field(discriminator="protocol"),
]


class AuditConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    log_dir: str = "~/.sopify/audit-log"
    retention_days: int = Field(default=30, ge=1, le=3650)
    log_allowed: bool = False
    log_denied: bool = True
    log_payload: bool = Field(default=False, description="Global default — per-rule overrides")
    otel_emit: bool = True
    max_payload_kb: int = Field(default=64, ge=1, le=4096)


class EncmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    http_proxy_port: int = Field(default=3128, ge=1, le=65535)
    mqtt_broker_port: int = Field(default=1883, ge=1, le=65535)
    websocket_port: int = Field(default=9001, ge=1, le=65535)
    tcp_forward_ports: dict[str, int] = Field(
        default_factory=lambda: {"postgresql": 5432, "mysql": 3306, "redis": 6379}
    )
    ca_cert_path: str = "~/.sopify/encm-ca/ca.crt"
    ca_key_path: str = "~/.sopify/encm-ca/ca.key"


class NetworkPolicy(BaseModel):
    """Top-level container — what gets serialized into ~/.sopify/network-policy.json."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    default_action: Literal["deny"] = "deny"
    rules: list[Rule] = Field(default_factory=list, max_length=MAX_RULES_PER_FILE)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    encm: EncmConfig = Field(default_factory=EncmConfig)

    @model_validator(mode="after")
    def _check_unique_ids(self) -> NetworkPolicy:
        seen: set[str] = set()
        for r in self.rules:
            if r.id and r.id in seen:
                raise ValueError(f"duplicate rule id: {r.id}")
            if r.id:
                seen.add(r.id)
        return self

    def find_rule(self, rule_id: str) -> Rule | None:
        for r in self.rules:
            if r.id == rule_id:
                return r
        return None


def load_policy(path: str | Path) -> NetworkPolicy:
    """Read + validate a policy file. Raises pydantic.ValidationError on bad input."""
    import json
    data = json.loads(Path(path).read_text())
    return NetworkPolicy.model_validate(data)


def dump_policy(policy: NetworkPolicy, path: str | Path) -> None:
    """Atomic write — temp file + rename — so a crash mid-write doesn't corrupt."""
    import json
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(policy.model_dump(mode="json"), indent=2, ensure_ascii=False))
    tmp.replace(path)


def default_policy() -> NetworkPolicy:
    """Bundled defaults (REQ-1.2.2). Auto-written on first boot if no file exists.

    Each default rule gets a fresh ULID so audit log entries can attribute
    requests to a specific rule (empty rule_id would make filtering noisy)."""
    return NetworkPolicy(
        rules=[
            HttpRule(
                id=new_rule_id(),
                protocol="https", domain="api.anthropic.com", ports=[443],
                description="Default LLM provider", added_by="default",
            ),
            HttpRule(
                id=new_rule_id(),
                protocol="https", domain="otel-collector.gsbattery.local",
                ports=[443, 4317, 4318],
                description="OTel telemetry", added_by="default",
            ),
            HttpRule(
                id=new_rule_id(),
                protocol="https", domain="pypi.org", ports=[443],
                description="Python packages", added_by="default",
            ),
            HttpRule(
                id=new_rule_id(),
                protocol="https", domain="files.pythonhosted.org", ports=[443],
                description="Python wheels", added_by="default",
            ),
            HttpRule(
                id=new_rule_id(),
                protocol="https", domain="registry.npmjs.org", ports=[443],
                description="npm packages", added_by="default",
            ),
        ],
    )


def new_rule_id() -> str:
    """26-char ULID-shaped ID. Uses python-ulid if installed; else falls back to uuid hex."""
    try:
        from ulid import ULID
        return f"rule_{ULID()!s}"
    except ImportError:
        import uuid
        return f"rule_{uuid.uuid4().hex[:24]}"

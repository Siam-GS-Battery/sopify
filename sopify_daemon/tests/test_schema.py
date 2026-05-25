"""Schema validation for the new Kubernetes-style NetworkRule YAML."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from sopify_daemon.schema import (
    NetworkRule,
    RuleMetadata,
    RuleSpec,
    SyncState,
)


def test_minimal_rule_validates():
    r = NetworkRule(
        metadata=RuleMetadata(name="allow-npm"),
        spec=RuleSpec(patterns=["*.npmjs.org"]),
    )
    assert r.apiVersion == "sopify.dev/v1"
    assert r.kind == "NetworkRule"
    assert r.metadata.scope == "global"
    assert r.spec.decision == "allow"


def test_rule_name_must_be_rfc1123():
    # Uppercase rejected
    with pytest.raises(ValidationError):
        RuleMetadata(name="Allow-NPM")
    # Underscores rejected
    with pytest.raises(ValidationError):
        RuleMetadata(name="allow_npm")
    # Leading/trailing dash rejected
    with pytest.raises(ValidationError):
        RuleMetadata(name="-allow")
    with pytest.raises(ValidationError):
        RuleMetadata(name="allow-")
    # Empty rejected
    with pytest.raises(ValidationError):
        RuleMetadata(name="")


def test_sandbox_scope_requires_sandbox_id():
    with pytest.raises(ValidationError) as exc:
        NetworkRule(
            metadata=RuleMetadata(name="x", scope="sandbox"),
            spec=RuleSpec(patterns=["a.com"]),
        )
    assert "sandbox_id" in str(exc.value)


def test_global_scope_rejects_sandbox_id():
    with pytest.raises(ValidationError):
        NetworkRule(
            metadata=RuleMetadata(name="x", scope="global", sandbox_id="proj-alpha"),
            spec=RuleSpec(patterns=["a.com"]),
        )


def test_domain_pattern_wildcard():
    r = RuleSpec(type="domain", patterns=["*.example.com", "api.foo.com"])
    assert "*.example.com" in r.patterns


def test_domain_pattern_rejects_garbage():
    with pytest.raises(ValidationError):
        RuleSpec(type="domain", patterns=["not a domain!!"])


def test_cidr_pattern():
    r = RuleSpec(type="cidr", patterns=["10.0.0.0/8", "192.168.1.0/24"])
    assert len(r.patterns) == 2


def test_cidr_rejects_invalid():
    with pytest.raises(ValidationError):
        RuleSpec(type="cidr", patterns=["10.0.0.0/99"])


def test_port_pattern():
    r = RuleSpec(type="port", patterns=["10.0.0.1:5432", "mqtt.local:1883"])
    assert "mqtt.local:1883" in r.patterns


def test_port_rejects_missing_port():
    with pytest.raises(ValidationError):
        RuleSpec(type="port", patterns=["10.0.0.1"])


def test_port_rejects_bad_range():
    with pytest.raises(ValidationError):
        RuleSpec(type="port", patterns=["10.0.0.1:99999"])


def test_ttl_constraints():
    # OK
    RuleSpec(patterns=["a.com"], ttl_seconds=3600)
    # 0 not allowed (ge=1)
    with pytest.raises(ValidationError):
        RuleSpec(patterns=["a.com"], ttl_seconds=0)


def test_extra_fields_rejected():
    """`extra=forbid` — typos surface loudly."""
    with pytest.raises(ValidationError):
        RuleMetadata(name="x", surprise="boom")  # type: ignore[call-arg]


def test_sync_state_round_trip():
    s = SyncState()
    s2 = SyncState.model_validate(s.model_dump(mode="json"))
    assert s2.schema_version == 1
    assert s2.rules == []

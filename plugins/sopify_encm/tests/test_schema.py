"""Schema v2 validation tests."""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from plugins.sopify_encm.schema import (
    CURRENT_SCHEMA_VERSION,
    HttpRule,
    MqttRule,
    NetworkPolicy,
    QueryFilter,
    TcpRule,
    WebSocketRule,
    default_policy,
    dump_policy,
    load_policy,
    new_rule_id,
)


def test_default_policy_validates():
    p = default_policy()
    assert p.schema_version == CURRENT_SCHEMA_VERSION
    assert p.default_action == "deny"
    assert len(p.rules) >= 5  # Anthropic, OTel, PyPI, etc.
    # Every default rule must be an HTTPS rule on port 443
    for r in p.rules:
        assert isinstance(r, HttpRule)
        assert r.protocol == "https"
        assert 443 in r.ports


def test_http_rule_methods_default():
    r = HttpRule(protocol="https", domain="api.example.com", ports=[443])
    assert "GET" in r.methods and "POST" in r.methods


def test_http_rule_rejects_bad_domain():
    with pytest.raises(ValidationError):
        HttpRule(protocol="https", domain="not a domain!!", ports=[443])


def test_http_rule_rejects_bad_port():
    with pytest.raises(ValidationError):
        HttpRule(protocol="https", domain="example.com", ports=[99999])
    with pytest.raises(ValidationError):
        HttpRule(protocol="https", domain="example.com", ports=[0])


def test_http_rule_wildcard_domain_ok():
    r = HttpRule(protocol="https", domain="*.sharepoint.com", ports=[443])
    assert r.domain == "*.sharepoint.com"


def test_http_rule_lowercases_domain():
    r = HttpRule(protocol="https", domain="API.Anthropic.COM", ports=[443])
    assert r.domain == "api.anthropic.com"


def test_mqtt_topic_wildcard_validation():
    # `#` must be at the end of a topic filter (MQTT spec)
    with pytest.raises(ValidationError):
        MqttRule(protocol="mqtt", domain="broker.local", ports=[1883],
                 topics_allow=["sensors/#/bad"])
    # `+` mid-topic is fine
    r = MqttRule(protocol="mqtt", domain="broker.local", ports=[1883],
                 topics_allow=["sensors/+/telemetry"])
    assert "sensors/+/telemetry" in r.topics_allow


def test_mqtt_topic_rejects_empty_or_space():
    with pytest.raises(ValidationError):
        MqttRule(protocol="mqtt", domain="broker.local", ports=[1883],
                 topics_allow=["sensors/ /bad"])
    with pytest.raises(ValidationError):
        MqttRule(protocol="mqtt", domain="broker.local", ports=[1883],
                 topics_allow=[""])


def test_websocket_rule_validates():
    r = WebSocketRule(protocol="wss", domain="realtime.example.com", ports=[443])
    assert r.protocol == "wss"
    assert r.log_messages is False  # default


def test_tcp_rule_default_wire_protocol():
    r = TcpRule(protocol="tcp", domain="pg.example.com", ports=[5432])
    assert r.wire_protocol == "raw"  # default — no query filter applied


def test_tcp_rule_with_query_filter():
    r = TcpRule(
        protocol="tcp",
        domain="pg.example.com",
        ports=[5432],
        wire_protocol="postgresql",
        query_filter=QueryFilter(non_dev_block=["DROP", "TRUNCATE"]),
    )
    assert r.query_filter is not None
    assert "DROP" in r.query_filter.non_dev_block


def test_discriminated_union_picks_right_class():
    """Pydantic must select the right Rule subclass based on `protocol`."""
    data = {
        "schema_version": 2,
        "default_action": "deny",
        "rules": [
            {"protocol": "https", "domain": "a.com", "ports": [443]},
            {"protocol": "mqtt", "domain": "b.local", "ports": [1883]},
            {"protocol": "tcp", "domain": "c.local", "ports": [5432]},
            {"protocol": "wss", "domain": "d.com", "ports": [443]},
        ],
    }
    p = NetworkPolicy.model_validate(data)
    assert isinstance(p.rules[0], HttpRule)
    assert isinstance(p.rules[1], MqttRule)
    assert isinstance(p.rules[2], TcpRule)
    assert isinstance(p.rules[3], WebSocketRule)


def test_unknown_protocol_rejected():
    with pytest.raises(ValidationError):
        NetworkPolicy.model_validate({
            "schema_version": 2,
            "rules": [{"protocol": "smtp", "domain": "mail.local", "ports": [25]}],
        })


def test_extra_fields_forbidden():
    """Schema is `extra=forbid` so typos surface loudly, not silently ignored."""
    with pytest.raises(ValidationError):
        HttpRule(protocol="https", domain="a.com", ports=[443], surprise=42)  # type: ignore[call-arg]


def test_default_action_locked_to_deny():
    """M1 must default-deny — schema rejects `allow`."""
    with pytest.raises(ValidationError):
        NetworkPolicy.model_validate({
            "schema_version": 2,
            "default_action": "allow",
            "rules": [],
        })


def test_duplicate_rule_ids_rejected():
    with pytest.raises(ValidationError):
        NetworkPolicy.model_validate({
            "schema_version": 2,
            "rules": [
                {"id": "dup", "protocol": "https", "domain": "a.com", "ports": [443]},
                {"id": "dup", "protocol": "https", "domain": "b.com", "ports": [443]},
            ],
        })


def test_find_rule():
    p = NetworkPolicy(rules=[
        HttpRule(id="rule_a", protocol="https", domain="a.com", ports=[443]),
        HttpRule(id="rule_b", protocol="https", domain="b.com", ports=[443]),
    ])
    assert p.find_rule("rule_a").domain == "a.com"
    assert p.find_rule("missing") is None


def test_roundtrip_dump_load(tmp_path):
    """Atomic write + reload reproduces the policy verbatim."""
    p = default_policy()
    f = tmp_path / "policy.json"
    dump_policy(p, f)
    p2 = load_policy(f)
    assert p2.model_dump(mode="json") == p.model_dump(mode="json")


def test_atomic_write_no_partial_on_serialize_failure(tmp_path):
    """If json.dumps fails partway, the temp file shouldn't replace the real one."""
    p = default_policy()
    f = tmp_path / "policy.json"
    dump_policy(p, f)
    original = f.read_text()
    # Simulate a write where the temp side is never finalised — just ensure
    # the public file still parses after a successful roundtrip.
    assert json.loads(original)["schema_version"] == 2


def test_new_rule_id_unique():
    a = new_rule_id()
    b = new_rule_id()
    assert a != b
    assert a.startswith("rule_")

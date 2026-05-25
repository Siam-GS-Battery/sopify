"""Rule matcher tests — covers HTTP/HTTPS, WS, MQTT topic ACL, TCP, rate limits."""
from __future__ import annotations

import pytest

from plugins.sopify_encm.rules import RateLimiter, RuleMatcher
from plugins.sopify_encm.schema import (
    HttpRule,
    MqttRule,
    NetworkPolicy,
    TcpRule,
    WebSocketRule,
)


# ── Domain matching ─────────────────────────────────────────────────────

def test_exact_domain_match():
    p = NetworkPolicy(rules=[HttpRule(id="r1", protocol="https", domain="api.example.com", ports=[443])])
    m = RuleMatcher(p)
    d = m.evaluate_http(protocol="https", host="api.example.com", port=443,
                         method="GET", path="/", src="sandbox-1")
    assert d.allow
    assert d.rule_id == "r1"


def test_exact_match_doesnt_match_subdomain():
    p = NetworkPolicy(rules=[HttpRule(id="r1", protocol="https", domain="example.com", ports=[443])])
    m = RuleMatcher(p)
    d = m.evaluate_http(protocol="https", host="sub.example.com", port=443,
                         method="GET", path="/", src="sandbox-1")
    assert not d.allow


def test_wildcard_matches_subdomain():
    p = NetworkPolicy(rules=[HttpRule(id="r1", protocol="https", domain="*.example.com", ports=[443])])
    m = RuleMatcher(p)
    d = m.evaluate_http(protocol="https", host="sub.example.com", port=443,
                         method="GET", path="/", src="sandbox-1")
    assert d.allow


def test_wildcard_doesnt_match_parent():
    """`*.example.com` matches `sub.example.com` but NOT bare `example.com`."""
    p = NetworkPolicy(rules=[HttpRule(id="r1", protocol="https", domain="*.example.com", ports=[443])])
    m = RuleMatcher(p)
    d = m.evaluate_http(protocol="https", host="example.com", port=443,
                         method="GET", path="/", src="sandbox-1")
    assert not d.allow


def test_protocol_must_match_exactly():
    """An https rule must not allow http requests, even on the same host+port."""
    p = NetworkPolicy(rules=[HttpRule(id="r1", protocol="https", domain="a.com", ports=[443])])
    m = RuleMatcher(p)
    # Different protocol
    d = m.evaluate_http(protocol="http", host="a.com", port=443,
                         method="GET", path="/", src="sandbox-1")
    assert not d.allow


def test_default_deny_when_no_rules():
    p = NetworkPolicy(rules=[])
    m = RuleMatcher(p)
    d = m.evaluate_http(protocol="https", host="anywhere.com", port=443,
                         method="GET", path="/", src="sandbox-1")
    assert not d.allow
    assert "default-deny" in d.reason


# ── Method + port ────────────────────────────────────────────────────────

def test_method_must_be_allowed():
    p = NetworkPolicy(rules=[
        HttpRule(id="r1", protocol="https", domain="a.com", ports=[443], methods=["GET"]),
    ])
    m = RuleMatcher(p)
    assert m.evaluate_http(protocol="https", host="a.com", port=443,
                           method="GET", path="/", src="s").allow
    assert not m.evaluate_http(protocol="https", host="a.com", port=443,
                                method="POST", path="/", src="s").allow


def test_port_must_be_in_ports_list():
    p = NetworkPolicy(rules=[HttpRule(id="r1", protocol="https", domain="a.com", ports=[443])])
    m = RuleMatcher(p)
    assert not m.evaluate_http(protocol="https", host="a.com", port=8443,
                                method="GET", path="/", src="s").allow


# ── Path allow / deny ────────────────────────────────────────────────────

def test_paths_allow_empty_means_any():
    p = NetworkPolicy(rules=[HttpRule(id="r1", protocol="https", domain="a.com", ports=[443])])
    m = RuleMatcher(p)
    assert m.evaluate_http(protocol="https", host="a.com", port=443,
                           method="GET", path="/anywhere", src="s").allow


def test_paths_allow_glob():
    p = NetworkPolicy(rules=[
        HttpRule(id="r1", protocol="https", domain="graph.microsoft.com", ports=[443],
                 paths_allow=["/v1.0/me/messages*", "/v1.0/me/sendMail"]),
    ])
    m = RuleMatcher(p)
    assert m.evaluate_http(protocol="https", host="graph.microsoft.com", port=443,
                           method="GET", path="/v1.0/me/messages", src="s").allow
    assert m.evaluate_http(protocol="https", host="graph.microsoft.com", port=443,
                           method="GET", path="/v1.0/me/messages/123", src="s").allow
    # Not in allow list
    assert not m.evaluate_http(protocol="https", host="graph.microsoft.com", port=443,
                                method="GET", path="/v1.0/me/contacts", src="s").allow


def test_paths_deny_overrides_allow():
    p = NetworkPolicy(rules=[
        HttpRule(id="r1", protocol="https", domain="api.com", ports=[443],
                 paths_allow=["/v1/*"], paths_deny=["/v1/admin/*"]),
    ])
    m = RuleMatcher(p)
    assert m.evaluate_http(protocol="https", host="api.com", port=443,
                           method="GET", path="/v1/users", src="s").allow
    assert not m.evaluate_http(protocol="https", host="api.com", port=443,
                                method="GET", path="/v1/admin/danger", src="s").allow


# ── Rate limiting ────────────────────────────────────────────────────────

def test_rate_limit_blocks_beyond_threshold():
    p = NetworkPolicy(rules=[
        HttpRule(id="r1", protocol="https", domain="a.com", ports=[443],
                 rate_limit_per_min=3),
    ])
    m = RuleMatcher(p)
    for _ in range(3):
        d = m.evaluate_http(protocol="https", host="a.com", port=443,
                             method="GET", path="/", src="s1")
        assert d.allow
    # 4th request exceeds the cap
    d = m.evaluate_http(protocol="https", host="a.com", port=443,
                         method="GET", path="/", src="s1")
    assert not d.allow
    assert "rate limit" in d.reason


def test_rate_limit_is_per_source():
    """Two different sandboxes shouldn't share the same bucket."""
    p = NetworkPolicy(rules=[
        HttpRule(id="r1", protocol="https", domain="a.com", ports=[443], rate_limit_per_min=2),
    ])
    m = RuleMatcher(p)
    # Exhaust s1's quota
    assert m.evaluate_http(protocol="https", host="a.com", port=443, method="GET", path="/", src="s1").allow
    assert m.evaluate_http(protocol="https", host="a.com", port=443, method="GET", path="/", src="s1").allow
    assert not m.evaluate_http(protocol="https", host="a.com", port=443, method="GET", path="/", src="s1").allow
    # s2 still has a fresh quota
    assert m.evaluate_http(protocol="https", host="a.com", port=443, method="GET", path="/", src="s2").allow


def test_rate_limit_none_means_unlimited():
    p = NetworkPolicy(rules=[HttpRule(id="r1", protocol="https", domain="a.com", ports=[443])])
    m = RuleMatcher(p)
    for _ in range(50):
        assert m.evaluate_http(protocol="https", host="a.com", port=443,
                               method="GET", path="/", src="s1").allow


# ── WebSocket ────────────────────────────────────────────────────────────

def test_websocket_match():
    p = NetworkPolicy(rules=[
        WebSocketRule(id="ws1", protocol="wss", domain="realtime.example.com", ports=[443]),
    ])
    m = RuleMatcher(p)
    d = m.evaluate_websocket(protocol="wss", host="realtime.example.com", port=443, src="s")
    assert d.allow
    # Wrong protocol scheme
    assert not m.evaluate_websocket(protocol="ws", host="realtime.example.com", port=443, src="s").allow


# ── MQTT topic ACL ───────────────────────────────────────────────────────

def test_mqtt_connect_matches_broker():
    rule = MqttRule(id="m1", protocol="mqtt", domain="broker.local", ports=[1883],
                    topics_allow=["sensors/+/telemetry"])
    p = NetworkPolicy(rules=[rule])
    m = RuleMatcher(p)
    d, r = m.evaluate_mqtt_connect(protocol="mqtt", host="broker.local", port=1883, src="s")
    assert d.allow
    assert r is rule


def test_mqtt_topic_plus_wildcard():
    rule = MqttRule(id="m1", protocol="mqtt", domain="broker.local", ports=[1883],
                    topics_allow=["sensors/+/telemetry"])
    d = RuleMatcher.evaluate_mqtt_topic(rule, "sensors/cell-01/telemetry", "sub")
    assert d.allow
    # Multi-level not matched by `+`
    d = RuleMatcher.evaluate_mqtt_topic(rule, "sensors/cell-01/sub/telemetry", "sub")
    assert not d.allow
    # Wrong topic family
    d = RuleMatcher.evaluate_mqtt_topic(rule, "alerts/critical", "sub")
    assert not d.allow


def test_mqtt_topic_hash_wildcard():
    """Per MQTT spec v3.1.1 §4.7.1.2: `alerts/#` matches `alerts` (the parent
    counts as zero remaining levels) AND `alerts/x/y/z` (multi-level)."""
    rule = MqttRule(id="m1", protocol="mqtt", domain="broker.local", ports=[1883],
                    topics_allow=["alerts/#"])
    assert RuleMatcher.evaluate_mqtt_topic(rule, "alerts/cell/critical", "sub").allow
    assert RuleMatcher.evaluate_mqtt_topic(rule, "alerts", "sub").allow
    assert RuleMatcher.evaluate_mqtt_topic(rule, "alerts/x/y/z", "sub").allow
    # Wrong root topic must still be denied
    assert not RuleMatcher.evaluate_mqtt_topic(rule, "sensors/x", "sub").allow


def test_mqtt_topics_deny_default_blocks_unlisted():
    """Default `topics_deny=['#']` means nothing is allowed unless explicitly
    in `topics_allow`. This is the safe baseline."""
    rule = MqttRule(id="m1", protocol="mqtt", domain="b.local", ports=[1883],
                    topics_allow=["machines/+/status"])
    # The explicit allow wins over the catch-all deny
    assert RuleMatcher.evaluate_mqtt_topic(rule, "machines/x/status", "sub").allow
    # Outside the allow list — falls through to deny
    assert not RuleMatcher.evaluate_mqtt_topic(rule, "secrets/leak", "sub").allow


# ── TCP forward ──────────────────────────────────────────────────────────

def test_tcp_match():
    rule = TcpRule(id="t1", protocol="tcp", domain="pg.local", ports=[5432], wire_protocol="postgresql")
    p = NetworkPolicy(rules=[rule])
    m = RuleMatcher(p)
    d, r = m.evaluate_tcp(host="pg.local", port=5432, src="s")
    assert d.allow
    assert r is rule


def test_tcp_no_match_returns_none_rule():
    p = NetworkPolicy(rules=[])
    m = RuleMatcher(p)
    d, r = m.evaluate_tcp(host="anywhere.local", port=5432, src="s")
    assert not d.allow
    assert r is None


# ── Hot reload ───────────────────────────────────────────────────────────

def test_update_policy_swaps_rules():
    p1 = NetworkPolicy(rules=[HttpRule(id="r1", protocol="https", domain="old.com", ports=[443])])
    p2 = NetworkPolicy(rules=[HttpRule(id="r2", protocol="https", domain="new.com", ports=[443])])
    m = RuleMatcher(p1)
    assert m.evaluate_http(protocol="https", host="old.com", port=443,
                           method="GET", path="/", src="s").allow
    m.update_policy(p2)
    assert not m.evaluate_http(protocol="https", host="old.com", port=443,
                                method="GET", path="/", src="s").allow
    assert m.evaluate_http(protocol="https", host="new.com", port=443,
                           method="GET", path="/", src="s").allow


# ── First-match-wins ─────────────────────────────────────────────────────

def test_first_matching_rule_wins():
    """Two rules can match the same destination — earlier rule's settings apply."""
    p = NetworkPolicy(rules=[
        HttpRule(id="strict", protocol="https", domain="a.com", ports=[443],
                 methods=["GET"]),
        HttpRule(id="loose", protocol="https", domain="a.com", ports=[443],
                 methods=["GET", "POST", "DELETE"]),
    ])
    m = RuleMatcher(p)
    # GET → strict rule matches first
    d = m.evaluate_http(protocol="https", host="a.com", port=443,
                         method="GET", path="/", src="s")
    assert d.allow and d.rule_id == "strict"
    # POST → strict doesn't allow POST → falls through to loose
    d = m.evaluate_http(protocol="https", host="a.com", port=443,
                         method="POST", path="/", src="s")
    assert d.allow and d.rule_id == "loose"

"""Rule-matching engine.

Given a destination (protocol + host + port + optional path/topic/method)
and a NetworkPolicy, decide allow/deny + which rule matched. Rate-limit
enforcement is delegated to :class:`RateLimiter`.

Matching precedence:
  1. Protocol must match exactly (https != http for a v2 https rule)
  2. Domain pattern match (exact or wildcard `*.domain.tld`)
  3. Port must be in the rule's ``ports`` list
  4. Method/path/topic match (protocol-specific)
  5. Rate limit window check (consumes a slot if allowed)

First matching rule wins. ``default_action="deny"`` means no match → deny.
"""
from __future__ import annotations

# Unix File name matching checker
import fnmatch
import re
from dataclasses import dataclass
from typing import Literal, Optional

from ..schema import (
    HttpRule,
    MqttRule,
    NetworkPolicy,
    Rule,
    TcpRule,
    WebSocketRule,
)
from .rate_limiter import RateLimiter

Protocol = Literal["http", "https", "ws", "wss", "mqtt", "mqtts", "tcp"]


@dataclass(frozen=True, slots=True)
class Decision:
    """Result of rule evaluation. Audit logger consumes this directly."""

    allow: bool
    reason: str
    rule_id: Optional[str] = None
    protocol: str = ""
    dst_host: str = ""
    dst_port: int = 0

    @classmethod
    def deny(cls, reason: str, **kw) -> "Decision":
        return cls(allow=False, reason=reason, **kw)

    @classmethod
    def allow_via(cls, rule: Rule, **kw) -> "Decision":
        return cls(allow=True, reason="matched", rule_id=rule.id, **kw)


def _domain_matches(rule_domain: str, host: str) -> bool:
    """`*.example.com` matches sub.example.com but NOT example.com.

    Exact match is case-insensitive. Wildcards only at the leftmost position
    (i.e. `*.example.com` is allowed, `example.*.com` is not).
    """
    host = host.lower()
    if rule_domain.startswith("*."):
        suffix = rule_domain[2:]  # drop "*."
        # `*.example.com` matches `sub.example.com` (has a label before suffix)
        # but not `example.com` (no extra label).
        return host.endswith("." + suffix) and len(host) > len(suffix) + 1
    return host == rule_domain


def _path_matches_any(patterns: list[str], path: str) -> bool:
    """
    True iff `path` matches at least one glob pattern. Empty list → False
    (no patterns can match nothing). Caller decides what empty means.
    """
    for pat in patterns:
        if fnmatch.fnmatchcase(path, pat):
            return True
    return False


def _path_is_allowed(allow_patterns: list[str], path: str) -> bool:
    """
    Allow-list semantics: empty list = allow anything; non-empty = path
    must match at least one pattern.
    """
    if not allow_patterns:
        return True
    return _path_matches_any(allow_patterns, path)


def _path_is_denied(deny_patterns: list[str], path: str) -> bool:
    """
    Deny-list semantics: empty list = deny nothing; non-empty = path is
    denied iff it matches at least one pattern.
    """
    if not deny_patterns:
        return False
    return _path_matches_any(deny_patterns, path)


def _mqtt_topic_matches(pattern: str, topic: str) -> bool:
    """
    MQTT topic-filter matching. `+` = single level, `#` = multi-level (terminal).
    """
    if pattern == "#":
        return True

    # Convert MQTT wildcards to regex
    parts = pattern.split("/")
    topic_parts = topic.split("/")
    for i, p in enumerate(parts):

        if p == "#":
            return True  # remaining levels swallowed

        if i >= len(topic_parts):
            return False
        
        if p == "+":
            continue  # any single level
        
        if p != topic_parts[i]:
            return False
    
    # All pattern parts consumed — accept iff topic is fully consumed too.
    return len(topic_parts) == len(parts)










class RuleMatcher:
    """
    Stateless rule lookup + rate-limit gate over a NetworkPolicy snapshot.
    """

    def __init__(self, policy: NetworkPolicy, rate_limiter: RateLimiter | None = None) -> None:
        self._policy = policy
        self._rl = rate_limiter or RateLimiter()


    @property
    def policy(self) -> NetworkPolicy:
        return self._policy


    def update_policy(self, policy: NetworkPolicy) -> None:
        """
        Hot-reload — swap the policy snapshot. Existing rate-limit buckets keep
        accruing (intentional: rule reload doesn't reset quotas).
        """
        self._policy = policy


    def evaluate_http(
        self,
        *,
        protocol: Literal["http", "https"],
        host: str,
        port: int,
        method: str,
        path: str,
        src: str,
    ) -> Decision:
        """
        Evaluate an HTTP/HTTPS request.
        """
        for rule in self._policy.rules:
            if not isinstance(rule, HttpRule):
                continue
            if rule.protocol != protocol:
                continue
            if not _domain_matches(rule.domain, host):
                continue
            if port not in rule.ports:
                continue
            if method.upper() not in rule.methods:
                continue
            if _path_is_denied(rule.paths_deny, path):
                return Decision.deny(
                    reason=f"rule {rule.id}: paths_deny matched",
                    rule_id=rule.id, protocol=protocol, dst_host=host, dst_port=port,
                )
            if not _path_is_allowed(rule.paths_allow, path):
                continue
            if not self._rl.check_and_consume(rule.id, src, rule.rate_limit_per_min):
                return Decision.deny(
                    reason=f"rule {rule.id}: rate limit exceeded",
                    rule_id=rule.id, protocol=protocol, dst_host=host, dst_port=port,
                )
            return Decision.allow_via(rule, protocol=protocol, dst_host=host, dst_port=port)
        return Decision.deny(
            reason="no matching rule (default-deny)",
            protocol=protocol, dst_host=host, dst_port=port,
        )




    def evaluate_websocket(
        self, *, protocol: Literal["ws", "wss"], host: str, port: int, src: str
    ) -> Decision:
        for rule in self._policy.rules:
            if not isinstance(rule, WebSocketRule):
                continue
            if rule.protocol != protocol:
                continue
            if not _domain_matches(rule.domain, host):
                continue
            if port not in rule.ports:
                continue
            if not self._rl.check_and_consume(rule.id, src, rule.rate_limit_per_min):
                return Decision.deny(
                    reason=f"rule {rule.id}: rate limit exceeded",
                    rule_id=rule.id, protocol=protocol, dst_host=host, dst_port=port,
                )
            return Decision.allow_via(rule, protocol=protocol, dst_host=host, dst_port=port)
        return Decision.deny(
            reason="no matching rule (default-deny)",
            protocol=protocol, dst_host=host, dst_port=port,
        )



    def evaluate_mqtt_connect(
        self, *, protocol: Literal["mqtt", "mqtts"], host: str, port: int, src: str
    ) -> tuple[Decision, MqttRule | None]:
        """First step of MQTT — broker-level connect. Returns (decision, rule) so
        the proxy can apply topic ACL on subsequent SUBSCRIBE/PUBLISH frames."""
        for rule in self._policy.rules:
            if not isinstance(rule, MqttRule):
                continue
            if rule.protocol != protocol:
                continue
            if not _domain_matches(rule.domain, host):
                continue
            if port not in rule.ports:
                continue
            return (
                Decision.allow_via(rule, protocol=protocol, dst_host=host, dst_port=port),
                rule,
            )
        return (
            Decision.deny(
                reason="no matching mqtt broker rule",
                protocol=protocol, dst_host=host, dst_port=port,
            ),
            None,
        )




    @staticmethod
    def evaluate_mqtt_topic(rule: MqttRule, topic: str, action: Literal["pub", "sub"]) -> Decision:
        """Per-frame topic ACL. Caller must already have established the broker
        connection via :meth:`evaluate_mqtt_connect`."""
        # Deny list overrides allow list (matches sopify_guardrails semantics).
        for pat in rule.topics_deny:
            if _mqtt_topic_matches(pat, topic):
                # Special-case: if `topics_allow` also matches, the allow wins
                # for the most specific pattern. Spec keeps it simple: deny wins.
                if any(_mqtt_topic_matches(p, topic) for p in rule.topics_allow):
                    # Both match — prefer allow because topics_deny defaults to ["#"]
                    # which would otherwise deny everything. The user-configured
                    # `topics_allow` is the positive carve-out.
                    return Decision.allow_via(rule)
                return Decision.deny(
                    reason=f"rule {rule.id}: topic {topic!r} in topics_deny ({pat})",
                    rule_id=rule.id,
                )
        for pat in rule.topics_allow:
            if _mqtt_topic_matches(pat, topic):
                return Decision.allow_via(rule)
        return Decision.deny(
            reason=f"rule {rule.id}: topic {topic!r} not in topics_allow",
            rule_id=rule.id,
        )





    def evaluate_tcp(
        self, *, host: str, port: int, src: str
    ) -> tuple[Decision, TcpRule | None]:
        """Connection-level decision for raw TCP. Per-query filtering would
        happen on data frames in a wire-protocol parser (not implemented in
        the current Control Plane variant — sbx enforces at gateway proxy
        instead)."""
        for rule in self._policy.rules:
            if not isinstance(rule, TcpRule):
                continue
            if not _domain_matches(rule.domain, host):
                continue
            if port not in rule.ports:
                continue
            return (
                Decision.allow_via(rule, protocol="tcp", dst_host=host, dst_port=port),
                rule,
            )
        return (
            Decision.deny(
                reason="no matching tcp rule",
                protocol="tcp", dst_host=host, dst_port=port,
            ),
            None,
        )

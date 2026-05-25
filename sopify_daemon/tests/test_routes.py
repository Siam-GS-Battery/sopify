"""FastAPI route tests — use TestClient + a fake backend so we don't hit
the real sandboxd."""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from sopify_daemon import paths
from sopify_daemon.app import create_app
from sopify_daemon.sbx_backend import (
    AuditEvent,
    BackendHealth,
    PolicyRuleApplied,
    PolicyRuleRequest,
)


class FakeBackend:
    """In-memory ISandboxBackend for tests. Records applied rules + lets us
    inject health + drift."""

    def __init__(self) -> None:
        self._next_id = 1
        self._rules: dict[str, PolicyRuleApplied] = {}
        self.healthy = True

    async def apply_rule(self, rule: PolicyRuleRequest) -> PolicyRuleApplied:
        rid = f"pol_{self._next_id}"
        self._next_id += 1
        applied = PolicyRuleApplied(
            id=rid, name=rule.name, resource_type=rule.resource_type,
            decision=rule.decision, resources=rule.resources,
            scope=rule.scope, sandbox_id=rule.sandbox_id,
            origin="local", status="active",
        )
        self._rules[rid] = applied
        return applied

    async def remove_rule(self, rule_id: str) -> None:
        self._rules.pop(rule_id, None)

    async def list_rules(self) -> list[PolicyRuleApplied]:
        return list(self._rules.values())

    async def tail_audit_log(self, *, since=None) -> AsyncIterator[AuditEvent]:
        if False:  # pragma: no cover — empty stream
            yield  # type: ignore[unreachable]

    async def health_check(self) -> BackendHealth:
        return BackendHealth(
            reachable=self.healthy,
            version="compatible" if self.healthy else None,
            socket_path="/fake/sock",
            error=None if self.healthy else "fake offline",
        )

    async def close(self) -> None: ...


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Spin up an app with isolated config + FS + fake backend.

    Skip the lifespan context (which would touch real sandboxd) by
    constructing the app and overriding state on first use.
    """
    monkeypatch.setenv(paths.ENV_ROOT, str(tmp_path / "encm"))
    monkeypatch.setenv(paths.ENV_CONFIG, str(tmp_path / "sopify"))
    paths.ensure_skeleton()

    # Build app — skip its lifespan (which would touch real sandboxd).
    from sopify_daemon import config as daemon_config
    cfg = daemon_config.load(create_if_missing=True)

    app = create_app()
    app.state.token = cfg.token
    app.state.config = cfg
    app.state.backend = FakeBackend()
    app.state.reconciler_obj = None  # routes tolerate this for now
    app.state.audit_ingester = None

    c = TestClient(app)
    yield c, cfg.token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health_is_public(client):
    c, _ = client
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_rules_list_requires_auth(client):
    c, _ = client
    r = c.get("/api/v1/rules")
    assert r.status_code == 401


def test_rules_list_empty(client):
    c, token = client
    r = c.get("/api/v1/rules", headers=_auth(token))
    assert r.status_code == 200
    assert r.json() == {"count": 0, "rules": []}


def test_rules_create_minimal(client):
    c, token = client
    body = {"name": "allow-anthropic", "patterns": ["api.anthropic.com"]}
    r = c.post("/api/v1/rules", json=body, headers=_auth(token))
    assert r.status_code == 201
    data = r.json()
    assert data["rule"]["metadata"]["name"] == "allow-anthropic"
    assert data["rule"]["spec"]["decision"] == "allow"
    # And list_rules sees it
    r2 = c.get("/api/v1/rules", headers=_auth(token))
    assert r2.json()["count"] == 1


def test_rules_create_rejects_bad_name(client):
    c, token = client
    r = c.post(
        "/api/v1/rules",
        json={"name": "BAD NAME", "patterns": ["a.com"]},
        headers=_auth(token),
    )
    assert r.status_code == 400


def test_rules_create_rejects_no_patterns(client):
    c, token = client
    r = c.post(
        "/api/v1/rules",
        json={"name": "no-pat", "patterns": []},
        headers=_auth(token),
    )
    # Either 422 (Pydantic) or 400 (our handler) — both signal invalid input
    assert r.status_code in (400, 422)


def test_rule_show(client):
    c, token = client
    c.post(
        "/api/v1/rules",
        json={"name": "x", "patterns": ["a.com"]},
        headers=_auth(token),
    )
    r = c.get("/api/v1/rules/x", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["metadata"]["name"] == "x"


def test_rule_show_404(client):
    c, token = client
    r = c.get("/api/v1/rules/ghost", headers=_auth(token))
    assert r.status_code == 404


def test_rule_remove(client):
    c, token = client
    c.post(
        "/api/v1/rules",
        json={"name": "to-rm", "patterns": ["a.com"]},
        headers=_auth(token),
    )
    r = c.delete("/api/v1/rules/to-rm", headers=_auth(token))
    assert r.status_code == 204
    r2 = c.get("/api/v1/rules/to-rm", headers=_auth(token))
    assert r2.status_code == 404


def test_rule_disable(client):
    c, token = client
    c.post(
        "/api/v1/rules",
        json={"name": "to-dis", "patterns": ["a.com"], "decision": "allow"},
        headers=_auth(token),
    )
    r = c.post("/api/v1/rules/to-dis/disable", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["decision"] == "deny"
    # Reload via show
    r2 = c.get("/api/v1/rules/to-dis", headers=_auth(token))
    assert r2.json()["spec"]["decision"] == "deny"


def test_audit_query_empty(client):
    c, token = client
    r = c.get("/api/v1/audit", headers=_auth(token))
    assert r.status_code == 200
    assert r.json() == {"count": 0, "events": []}


def test_drift_empty(client):
    c, token = client
    r = c.get("/api/v1/drift", headers=_auth(token))
    assert r.status_code == 200
    assert r.json() == {"count": 0, "drift": []}


def test_status_with_fake_backend(client):
    c, token = client
    r = c.get("/api/v1/status", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["sandboxd"]["reachable"] is True
    assert body["sandboxd"]["version"] == "compatible"
    assert body["rules"]["count"] == 0


def test_status_offline_backend(client):
    c, token = client
    # Flip the fake to unhealthy
    c.app.state.backend.healthy = False
    r = c.get("/api/v1/status", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["sandboxd"]["reachable"] is False


def test_token_malformed_header(client):
    c, _ = client
    r = c.get("/api/v1/rules", headers={"Authorization": "garbage"})
    assert r.status_code == 401


def test_token_wrong_value(client):
    c, _ = client
    r = c.get("/api/v1/rules", headers={"Authorization": "Bearer wrongtoken"})
    assert r.status_code == 401


def test_token_alt_form_token_keyword(client):
    """`Authorization: token <t>` (Jupyter style) accepted alongside Bearer."""
    c, token = client
    r = c.get("/api/v1/rules", headers={"Authorization": f"token {token}"})
    assert r.status_code == 200

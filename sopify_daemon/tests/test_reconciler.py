"""Reconciler diff logic — uses the FakeBackend so we can drive scenarios."""
from __future__ import annotations

from typing import AsyncIterator

import pytest

from sopify_daemon import paths
from sopify_daemon.reconciler import Reconciler
from sopify_daemon.rule_writer import RuleFileWriter, make_rule
from sopify_daemon.sbx_backend import (
    AuditEvent,
    BackendHealth,
    PolicyRuleApplied,
    PolicyRuleRequest,
)


class FakeBackend:
    def __init__(self) -> None:
        self._next_id = 100
        self._rules: dict[str, PolicyRuleApplied] = {}
        # Mirror the real sbx "default-allow-all" rule so drift detection
        # has a realistic starting state.
        self._add_default()

    def _add_default(self) -> None:
        self._rules["default-allow-all"] = PolicyRuleApplied(
            id="default-allow-all", name="default-allow-all",
            resource_type="network", decision="allow",
            resources=("**",), origin="default", status="active",
        )

    async def apply_rule(self, rule: PolicyRuleRequest) -> PolicyRuleApplied:
        rid = f"pol_{self._next_id}"
        self._next_id += 1
        a = PolicyRuleApplied(
            id=rid, name=rule.name, resource_type=rule.resource_type,
            decision=rule.decision, resources=rule.resources,
            scope=rule.scope, sandbox_id=rule.sandbox_id,
            origin="local", status="active",
        )
        self._rules[rid] = a
        return a

    async def remove_rule(self, rule_id: str) -> None:
        self._rules.pop(rule_id, None)

    async def list_rules(self) -> list[PolicyRuleApplied]:
        return list(self._rules.values())

    async def tail_audit_log(self, *, since=None) -> AsyncIterator[AuditEvent]:
        if False:  # pragma: no cover
            yield  # type: ignore[unreachable]

    async def health_check(self) -> BackendHealth:
        return BackendHealth(reachable=True, version="compatible")

    async def close(self) -> None: ...


@pytest.fixture()
def encm_root(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_ROOT, str(tmp_path))
    paths.ensure_skeleton()
    yield tmp_path


@pytest.mark.asyncio
async def test_tick_with_no_rules_yields_no_drift_for_sbx_defaults(encm_root):
    backend = FakeBackend()
    r = Reconciler(backend)
    state = await r.tick_once()
    # sbx has a default-origin rule — that's not drift
    assert state.drift_observations == []
    assert state.rules == []


@pytest.mark.asyncio
async def test_tick_applies_new_rule(encm_root):
    backend = FakeBackend()
    w = RuleFileWriter()
    w.write(make_rule(name="allow-anth", patterns=["api.anthropic.com"]))

    r = Reconciler(backend)
    state = await r.tick_once()

    assert len(state.rules) == 1
    assert state.rules[0].sync_state == "applied"
    assert state.rules[0].sbx_handles  # at least one handle
    # And the backend received it
    applied = await backend.list_rules()
    names = [a.name for a in applied if a.origin == "local"]
    assert any("allow-anth" in n for n in names)


@pytest.mark.asyncio
async def test_tick_idempotent_when_checksum_unchanged(encm_root):
    backend = FakeBackend()
    w = RuleFileWriter()
    w.write(make_rule(name="idem", patterns=["a.com"]))
    r = Reconciler(backend)
    state1 = await r.tick_once()
    state2 = await r.tick_once()
    # Both ticks produce the same handle set — re-apply didn't churn
    h1 = {h.sbx_rule_id for s in state1.rules for h in s.sbx_handles}
    h2 = {h.sbx_rule_id for s in state2.rules for h in s.sbx_handles}
    assert h1 == h2


@pytest.mark.asyncio
async def test_tick_removes_deleted_rule(encm_root):
    backend = FakeBackend()
    w = RuleFileWriter()
    w.write(make_rule(name="ephemeral", patterns=["a.com"]))
    r = Reconciler(backend)
    await r.tick_once()
    handles_before = [a for a in (await backend.list_rules()) if a.origin == "local"]
    assert handles_before

    # Delete the file → next tick should drop the sandboxd rule
    w.delete(name="ephemeral")
    await r.tick_once()
    handles_after = [a for a in (await backend.list_rules()) if a.origin == "local"]
    assert handles_after == []


@pytest.mark.asyncio
async def test_drift_detection(encm_root):
    backend = FakeBackend()
    # Manually inject a rule into sbx that ENCM didn't write
    await backend.apply_rule(PolicyRuleRequest(
        name="manual-rule", resource_type="network",
        decision="deny", resources=("evil.com",),
    ))
    r = Reconciler(backend)
    state = await r.tick_once()
    drift_targets = [d.resources for d in state.drift_observations]
    assert ["evil.com"] in [list(x) for x in drift_targets]


@pytest.mark.asyncio
async def test_changed_checksum_reapplies(encm_root):
    backend = FakeBackend()
    w = RuleFileWriter()
    w.write(make_rule(name="change-me", patterns=["a.com"]))
    r = Reconciler(backend)
    await r.tick_once()
    handles_v1 = {
        a.id for a in (await backend.list_rules())
        if a.origin == "local" and "change-me" in a.name
    }

    # Edit the file (different patterns → different checksum)
    w.write(make_rule(name="change-me", patterns=["b.com"]), overwrite=True)
    await r.tick_once()
    handles_v2 = {
        a.id for a in (await backend.list_rules())
        if a.origin == "local" and "change-me" in a.name
    }
    # Handles should have rotated (old removed, new created)
    assert handles_v1 != handles_v2


# ── Drift filter — sbx baseline must not look like drift ────────────────


class BaselineLikeBackend(FakeBackend):
    """Real sandboxd tags ``default-allow-all`` with ``origin=local``
    (verified 2026-05-24). The drift filter must catch it via
    name+resources, not origin alone."""

    def _add_default(self) -> None:
        from sopify_daemon.sbx_backend import PolicyRuleApplied
        self._rules["default-allow-all"] = PolicyRuleApplied(
            id="default-allow-all", name="default-allow-all",
            resource_type="network", decision="allow",
            resources=("**",),
            origin="local",  # ← matches real sandboxd output
            status="active",
        )


@pytest.mark.asyncio
async def test_default_allow_all_not_drift_when_origin_local(encm_root):
    """Real sandboxd tags the baseline rule as origin=local; we still
    need to recognise it as built-in to avoid spurious drift."""
    backend = BaselineLikeBackend()
    r = Reconciler(backend)
    state = await r.tick_once()
    assert state.drift_observations == []


@pytest.mark.asyncio
async def test_user_created_local_rule_does_appear_as_drift(encm_root):
    """Counter-example: a genuinely-untracked rule (origin=local + not
    `default-allow-all` + non-`**` resources) MUST appear as drift."""
    backend = BaselineLikeBackend()
    # Manually inject a rogue rule that ENCM didn't write
    from sopify_daemon.sbx_backend import PolicyRuleRequest
    await backend.apply_rule(PolicyRuleRequest(
        name="rogue-deny", resource_type="network",
        decision="deny", resources=("evil.com",),
    ))
    r = Reconciler(backend)
    state = await r.tick_once()
    assert len(state.drift_observations) == 1
    assert state.drift_observations[0].resources == ["evil.com"]


@pytest.mark.asyncio
async def test_kit_managed_rule_not_drift_http_shape(encm_root):
    """The real HTTP API returns kit rules with origin='scoped' +
    sandbox_id set + name='kit:<sandbox-id>'. Verified against sandboxd
    0.29 on 2026-05-24. Filter must catch this shape, not just the
    CLI's 'sandbox:<id>' origin string."""
    backend = BaselineLikeBackend()
    from sopify_daemon.sbx_backend import PolicyRuleApplied
    backend._rules["uuid-1"] = PolicyRuleApplied(
        id="c415c3fa-86e3-42ba-bced-ac792bf42c05",  # UUID, not `kit:` prefix
        name="kit:proj-x",                           # name has the prefix
        resource_type="network",
        decision="allow",
        resources=("api.anthropic.com", "pypi.org"),
        scope="sandbox",
        sandbox_id="proj-x",
        origin="scoped",                             # HTTP API value
        status="active",
    )
    r = Reconciler(backend)
    state = await r.tick_once()
    assert state.drift_observations == []


@pytest.mark.asyncio
async def test_sandbox_origin_filtered_even_without_kit_prefix(encm_root):
    """Defense-in-depth: if sbx adds a different rule ID format but
    still tags origin with `sandbox:`, treat as managed too."""
    backend = BaselineLikeBackend()
    from sopify_daemon.sbx_backend import PolicyRuleApplied
    backend._rules["weird:1234"] = PolicyRuleApplied(
        id="weird:1234",
        name="some-kit-rule",
        resource_type="network",
        decision="allow",
        resources=("a.com",),
        scope="sandbox",
        sandbox_id="proj-y",
        origin="sandbox:proj-y",  # ← the discriminator
        status="active",
    )
    r = Reconciler(backend)
    state = await r.tick_once()
    assert state.drift_observations == []

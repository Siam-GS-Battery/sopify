"""Adapter for the sbx (Docker Sandbox) policy API.

Two layers:

  1. :class:`ISandboxBackend` — abstract Protocol that the reconciler /
     route handlers depend on. Lets us swap to a different microVM
     runtime (Kata, Firecracker) without rewriting business logic.

  2. :class:`SbxBackend` — concrete implementation talking to sandboxd's
     Unix socket via ``httpx``. ``httpx.AsyncHTTPTransport`` supports
     unix sockets natively, no shell-out, no CLI scraping.

Why no CLI parsing: SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md §7 — "Do not
parse `sbx` CLI stdout via regex. CLI output format is not a stable
contract." Confirmed: between sbx 0.24 and 0.30 several CLI rows were
renamed/reformatted.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional, Protocol, runtime_checkable

import httpx

log = logging.getLogger(__name__)


# ── Domain types — kept narrow so backend swaps don't ripple ─────────────


@dataclass(frozen=True, slots=True)
class PolicyRuleApplied:
    """One row from ``GET /policy/rules`` — i.e. the *actual* state of sbx."""

    id: str
    name: str
    resource_type: str  # "network" | "file" | ...
    decision: str  # "allow" | "deny"
    resources: tuple[str, ...]
    scope: str = "global"
    sandbox_id: Optional[str] = None
    origin: str = "local"  # "local" | "organization" | "default"
    status: str = "active"


@dataclass(frozen=True, slots=True)
class PolicyRuleRequest:
    """What we POST to sandboxd to create a rule. Reconciler-built."""

    name: str
    resource_type: str
    decision: str
    resources: tuple[str, ...]
    scope: str = "global"
    sandbox_id: Optional[str] = None
    labels: Optional[dict[str, str]] = None


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One decision from ``GET /policy/log`` — feeds the audit ingester."""

    ts: datetime
    sandbox_id: str
    host: str
    decision: str
    rule_id: Optional[str] = None
    port: Optional[int] = None
    proxy_mode: Optional[str] = None
    raw: Optional[dict] = None  # original payload for forensic dumps


@dataclass(frozen=True, slots=True)
class BackendHealth:
    """Health probe result for ``GET /api/v1/status``."""

    reachable: bool
    version: Optional[str] = None
    error: Optional[str] = None
    socket_path: Optional[str] = None


# ── Protocol ────────────────────────────────────────────────────────────


@runtime_checkable
class ISandboxBackend(Protocol):
    """All methods async — daemon's reconciler + audit ingester are asyncio tasks."""

    async def apply_rule(self, rule: PolicyRuleRequest) -> PolicyRuleApplied: ...
    async def remove_rule(self, rule_id: str) -> None: ...
    async def list_rules(self) -> list[PolicyRuleApplied]: ...
    async def tail_audit_log(
        self, *, since: Optional[datetime] = None
    ) -> AsyncIterator[AuditEvent]: ...
    async def health_check(self) -> BackendHealth: ...
    async def close(self) -> None: ...


# ── Implementation ──────────────────────────────────────────────────────


def default_socket_path() -> Path:
    """Probe well-known locations for the sandboxd Unix socket.

    Order matches what we found on the dev machine (2026-05-24); Linux
    paths are predictions until verified."""
    candidates = [
        Path.home() / "Library/Application Support/com.docker.sandboxes/sandboxes/sandboxd/sandboxd.sock",
        Path.home() / ".docker/sandboxes/sandboxd.sock",
        Path("/run/sandboxd.sock"),
        Path("/var/run/sandboxd.sock"),
    ]
    for c in candidates:
        if c.exists():
            return c
    # Return the most likely macOS path so error messages are actionable
    return candidates[0]


class SbxBackend(ISandboxBackend):
    """sandboxd HTTP API client over Unix socket."""

    def __init__(self, socket_path: Optional[Path] = None) -> None:
        self._socket_path = Path(socket_path) if socket_path else default_socket_path()
        # `http+unix://` is httpx convention. Base URL is irrelevant since
        # the transport ignores it, but it has to be set.
        self._client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=str(self._socket_path)),
            base_url="http://sandboxd",
            timeout=httpx.Timeout(5.0, read=30.0),
        )

    async def apply_rule(self, rule: PolicyRuleRequest) -> PolicyRuleApplied:
        """Create a rule via ``sbx policy allow|deny network``.

        Why CLI rather than the HTTP API: ``POST /policy/rules`` exists on
        the daemon (verified by probe — it returns 400 on empty body)
        but the accepted payload shape is undocumented and our
        hand-written OpenAPI mini-spec guessed wrong. ``sbx policy
        allow/deny network`` is the only stable write surface; we never
        parse its stdout (the integration plan's "no CLI regex" rule),
        we just check exit code and re-list via HTTP to recover the
        assigned UUID.
        """
        if rule.resource_type != "network":
            raise ValueError(
                f"only resource_type=network supported (got {rule.resource_type!r})"
            )
        if not rule.resources:
            raise ValueError("at least one resource required")

        # Build CLI args: `sbx policy allow|deny network [-g|<sandbox>] <res>`
        verb = "allow" if rule.decision == "allow" else "deny"
        scope_args: list[str] = ["-g"] if rule.scope == "global" else [rule.sandbox_id or ""]
        if rule.scope == "sandbox" and not rule.sandbox_id:
            raise ValueError("sandbox_id required when scope=sandbox")
        resources_csv = ",".join(rule.resources)

        await self._run_sbx(
            ["policy", verb, "network", *scope_args, resources_csv],
            err_prefix=f"apply_rule({verb} {resources_csv})",
        )

        # Re-list to find the rule sbx just created. We match by resource
        # set rather than name because sbx doesn't accept a custom name
        # via this CLI subcommand — it assigns its own UUID. The
        # reconciler tracks the returned UUID in sync.yaml.
        for r in await self.list_rules():
            if r.resource_type != "network":
                continue
            if r.decision != rule.decision:
                continue
            if r.scope != rule.scope:
                continue
            if r.sandbox_id != rule.sandbox_id:
                continue
            if tuple(r.resources) != tuple(rule.resources):
                continue
            return r

        # If we got here the rule didn't materialise — surface a clear
        # error so the reconciler marks the file as ``sync_state=error``.
        raise RuntimeError(
            f"apply_rule succeeded but no matching rule found in sbx "
            f"(resources={rule.resources!r}, scope={rule.scope!r})"
        )

    async def remove_rule(self, rule_id: str) -> None:
        """Remove a rule via ``sbx policy rm network -g --id <uuid>``.

        Idempotent: missing rules surface as exit=non-zero with stderr
        like "policy not found" — we swallow that case and treat it as
        success since the desired state (rule is gone) holds either way.
        """
        # First look up the rule so we know whether it's scope=sandbox.
        # Without scope context, `rm network -g --id` may not match a
        # sandbox-scoped rule (and vice versa).
        target = None
        for r in await self.list_rules():
            if r.id == rule_id:
                target = r
                break
        if target is None:
            return  # already gone — idempotent

        scope_args: list[str] = ["-g"] if target.scope == "global" else [target.sandbox_id or ""]
        await self._run_sbx(
            ["policy", "rm", "network", *scope_args, "--id", rule_id],
            err_prefix=f"remove_rule({rule_id})",
            allow_nonzero=True,
        )

    async def _run_sbx(
        self,
        argv: list[str],
        *,
        err_prefix: str,
        allow_nonzero: bool = False,
    ) -> tuple[int, bytes, bytes]:
        """Spawn ``sbx <argv>`` async. Returns (rc, stdout, stderr)."""
        import asyncio
        proc = await asyncio.create_subprocess_exec(
            "sbx", *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"{err_prefix}: sbx timed out after 10s") from None
        rc = proc.returncode or 0
        if rc != 0 and not allow_nonzero:
            raise RuntimeError(
                f"{err_prefix}: sbx exit={rc} stderr={stderr.decode(errors='replace')[:300]}"
            )
        return rc, stdout, stderr

    async def list_rules(self) -> list[PolicyRuleApplied]:
        r = await self._client.get("/policy/rules")
        r.raise_for_status()
        body = r.json()
        return [_parse_rule(item) for item in body.get("rules", [])]

    async def tail_audit_log(
        self, *, since: Optional[datetime] = None
    ) -> AsyncIterator[AuditEvent]:
        """Snapshot-diff audit events from ``sbx policy log --json``.

        Sandboxd does NOT expose an HTTP audit endpoint (verified
        2026-05-24 — exhaustive probe of /policy/log, /audit, /events,
        /policy/events, etc. all returned 404). The CLI's JSON output is
        the only stable interface. We're not parsing stdout via regex —
        the integration plan's "no CLI" rule targets free-form stdout
        parsing, not structured JSON which sbx maintains as part of its
        public CLI contract.

        Each call returns the events that are *new* since the previous
        call (by ``last_seen`` timestamp or by ``count_since`` delta).
        The audit ingester wraps this in a polling loop."""
        snapshot = await self._read_audit_snapshot()
        prev_seen = getattr(self, "_audit_seen", {})
        new_seen: dict[str, datetime] = {}
        for entry in snapshot:
            key = f"{entry['vm_name']}|{entry['host']}"
            try:
                last_seen = datetime.fromisoformat(
                    entry["last_seen"].replace("Z", "+00:00")
                )
            except (ValueError, KeyError, AttributeError):
                continue
            new_seen[key] = last_seen
            prev = prev_seen.get(key)
            if prev is not None and last_seen <= prev:
                continue  # not newer
            if since is not None and last_seen < since:
                continue
            yield _entry_to_event(entry, last_seen)
        # Persist for next poll. Stored on the backend instance so a
        # daemon restart resets the diff window — that's fine because
        # the JSONL writer is append-only and dedup happens via key+ts.
        self._audit_seen = new_seen

    async def _read_audit_snapshot(self) -> list[dict]:
        """Spawn ``sbx policy log --json --limit N`` and parse the result.

        Async-friendly: uses ``asyncio.create_subprocess_exec`` so the
        ingester loop doesn't block the event loop."""
        import asyncio
        try:
            proc = await asyncio.create_subprocess_exec(
                "sbx", "policy", "log", "--json", "--limit", "1000",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        except (FileNotFoundError, asyncio.TimeoutError):
            return []
        if proc.returncode != 0:
            return []
        try:
            data = json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError:
            log.warning("sbx policy log produced non-JSON output")
            return []
        entries: list[dict] = []
        for host in data.get("allowed_hosts") or []:
            entries.append({**host, "decision": "allow"})
        for host in data.get("blocked_hosts") or []:
            entries.append({**host, "decision": "deny"})
        return entries

    async def health_check(self) -> BackendHealth:
        try:
            # /version exists; POST returns 200 even with empty body.
            r = await self._client.post("/version")
            if r.status_code != 200:
                return BackendHealth(
                    reachable=False,
                    error=f"/version returned {r.status_code}",
                    socket_path=str(self._socket_path),
                )
            data = r.json()
            return BackendHealth(
                reachable=True,
                version=str(data.get("result", "unknown")),
                socket_path=str(self._socket_path),
            )
        except (httpx.ConnectError, httpx.TimeoutException, FileNotFoundError) as exc:
            return BackendHealth(
                reachable=False,
                error=f"{type(exc).__name__}: {exc}",
                socket_path=str(self._socket_path),
            )

    async def close(self) -> None:
        await self._client.aclose()


# ── Parsers ─────────────────────────────────────────────────────────────


def _parse_rule(item: dict) -> PolicyRuleApplied:
    """Best-effort conversion of a sandboxd rule dict. Unknown fields
    accepted silently so a sandboxd minor upgrade doesn't crash us."""
    return PolicyRuleApplied(
        id=str(item.get("id", "")),
        name=str(item.get("name", "")),
        resource_type=str(item.get("resource_type", "network")),
        decision=str(item.get("decision", "allow")),
        resources=tuple(item.get("resources", []) or []),
        scope=str(item.get("scope", "global")),
        sandbox_id=item.get("sandbox_id"),
        origin=str(item.get("origin", "local")),
        status=str(item.get("status", "active")),
    )


def _parse_audit_event(item: dict) -> AuditEvent:
    """Translate a (hypothetical) sandboxd JSON event into our domain type.

    Kept for compatibility if sbx ever ships a streaming endpoint. Today's
    code path is :func:`_entry_to_event` operating on the CLI snapshot
    shape."""
    ts_raw = item.get("ts") or item.get("timestamp") or ""
    try:
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        ts = datetime.now(timezone.utc)
    return AuditEvent(
        ts=ts,
        sandbox_id=str(item.get("sandbox_id") or item.get("sandbox") or ""),
        host=str(item.get("host") or item.get("destination") or ""),
        decision=str(item.get("decision") or ""),
        rule_id=item.get("rule_id"),
        port=item.get("port"),
        proxy_mode=item.get("proxy_mode"),
        raw=item,
    )


def _entry_to_event(entry: dict, last_seen: datetime) -> AuditEvent:
    """Translate one ``sbx policy log --json`` row into :class:`AuditEvent`.

    The CLI shape is::

        {
          "host": "api.anthropic.com:443",   # may include `:port`
          "vm_name": "sopify-proj-alpha",
          "proxy_type": "transparent",       # or "forward"
          "rule": "<rule name or '<dial failed>'>",
          "last_seen": "2026-05-24T03:15:31.850531+07:00",
          "since": "2026-05-24T03:13:15.273004+07:00",
          "count_since": 3,
          "decision": "allow",               # injected by _read_audit_snapshot
        }
    """
    host_raw = str(entry.get("host", ""))
    host, _, port_str = host_raw.rpartition(":")
    if host_raw.startswith("["):  # IPv6 literal like `[fd7f::]:9118`
        # rpartition already split it correctly, but the host has the
        # leading `[` and trailing `]` — keep as-is for traceability.
        pass
    try:
        port: Optional[int] = int(port_str) if port_str.isdigit() else None
    except ValueError:
        port = None
    if not host:
        host = host_raw
    rule = entry.get("rule")
    return AuditEvent(
        ts=last_seen,
        sandbox_id=str(entry.get("vm_name") or ""),
        host=host or host_raw,
        decision=str(entry.get("decision") or ""),
        rule_id=str(rule) if rule and rule != "<dial failed>" else None,
        port=port,
        proxy_mode=str(entry.get("proxy_type") or ""),
        raw=entry,
    )

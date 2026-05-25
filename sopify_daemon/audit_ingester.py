"""Audit ingester — tails sandboxd's policy log + writes enriched JSONL.

Runs as an asyncio task. The actual JSONL writer + daily rotation lives
in :mod:`plugins.sopify_encm.audit` (kept from the archived MITM build —
the file format is identical between architectures).

Enrichment: at write time we look up ``rule_id`` against the current
sync state and add ``rule_name`` + ``created_by`` so the audit log
remains human-readable even after sbx-side IDs change.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import sys
sys.path.insert(0, "plugins")  # for `from sopify_encm.audit import ...`

from plugins.sopify_encm.audit import AuditEvent as JsonlEvent, AuditWriter  # noqa: E402

from . import paths
from .reconciler import Reconciler
from .sbx_backend import AuditEvent, ISandboxBackend
from .schema import SyncState

log = logging.getLogger(__name__)


class AuditIngester:
    """One ingester per daemon. Tails the sbx log + writes JSONL."""

    def __init__(
        self,
        backend: ISandboxBackend,
        reconciler: Reconciler,
    ) -> None:
        self._backend = backend
        self._reconciler = reconciler
        self._writer = AuditWriter(paths.audit_dir())
        self._stop = asyncio.Event()
        self._events_seen = 0
        self._last_event_at: Optional[datetime] = None
        self._last_error: Optional[str] = None

    @property
    def events_seen(self) -> int:
        return self._events_seen

    @property
    def last_event_at(self) -> Optional[datetime]:
        return self._last_event_at

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        """Reconnect-with-backoff loop over the sandboxd streaming endpoint.

        sandboxd may not stream (returns end-of-response immediately on
        older versions) — in that case we sleep + retry rather than
        spinning."""
        backoff_seconds = 1
        max_backoff = 30
        since: Optional[datetime] = None
        while not self._stop.is_set():
            try:
                got_any = False
                async for ev in self._backend.tail_audit_log(since=since):
                    got_any = True
                    self._handle_event(ev)
                    since = ev.ts
                    backoff_seconds = 1  # reset on successful delivery
                # If the stream ended cleanly without events, treat as
                # poll-mode and back off.
                if not got_any:
                    await asyncio.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2, max_backoff)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("audit tail failed (%s); retrying in %ds",
                            type(exc).__name__, backoff_seconds)
                self._last_error = f"{type(exc).__name__}: {exc}"
                try:
                    await asyncio.sleep(backoff_seconds)
                except asyncio.CancelledError:
                    raise
                backoff_seconds = min(backoff_seconds * 2, max_backoff)
        self._writer.close()

    def _handle_event(self, ev: AuditEvent) -> None:
        """Enrich + persist one event."""
        try:
            rule_name = self._lookup_rule_name(ev.rule_id)
            self._writer.write(JsonlEvent(
                decision=_normalize_decision(ev.decision),
                protocol="https" if ev.proxy_mode == "forward" else "tcp",
                src=ev.sandbox_id or "unknown",
                dst=ev.host + (f":{ev.port}" if ev.port else ""),
                rule_id=ev.rule_id,
                ts=ev.ts.isoformat(),
                extras={
                    "rule_name": rule_name,
                    "proxy_mode": ev.proxy_mode,
                },
            ))
            self._events_seen += 1
            self._last_event_at = ev.ts
        except Exception as exc:  # noqa: BLE001
            log.exception("failed to persist audit event %s", ev)
            self._last_error = f"{type(exc).__name__}: {exc}"

    def _lookup_rule_name(self, rule_id: Optional[str]) -> Optional[str]:
        """Look up ENCM-side rule_name from sync state by sandboxd handle ID."""
        if not rule_id:
            return None
        # Cheap path: load sync state per call. The state file is small;
        # if profiling shows this is hot we'll cache + invalidate on
        # reconciler tick.
        sf = paths.sync_state_file()
        if not sf.exists():
            return None
        try:
            import yaml
            data = yaml.safe_load(sf.read_text(encoding="utf-8")) or {}
            state = SyncState.model_validate(data)
        except Exception:
            return None
        for r in state.rules:
            for h in r.sbx_handles:
                if h.sbx_rule_id == rule_id:
                    return r.source_path
        return None


def _normalize_decision(d: str) -> str:
    """Map sbx decisions onto the JSONL writer's enum."""
    d_lower = (d or "").lower()
    if d_lower in ("allow", "permit", "accept"):
        return "allow"
    if d_lower in ("deny", "reject", "block"):
        return "deny"
    if "rate" in d_lower:
        return "rate_limited"
    return "deny"  # safe default

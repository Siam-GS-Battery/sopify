"""``/api/v1/audit`` — read access to the JSONL audit log."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query

from .. import paths

router = APIRouter()


@router.get("/audit")
async def query_audit(
    limit: int = Query(default=200, ge=1, le=10_000),
    since: Optional[str] = Query(
        default=None, description="ISO-8601 timestamp; default = 24h ago"
    ),
    decision: Optional[str] = Query(default=None, description="allow | deny | …"),
    src: Optional[str] = Query(default=None, description="Filter by sandbox ID"),
) -> dict:
    """Return up to ``limit`` recent audit events newest-first.

    No streaming yet — the daemon plan calls for `/audit/stream` (SSE)
    in a follow-up; for v1 this poll endpoint is enough for the UI to
    paint a timeline.
    """
    since_dt = _parse_since(since)
    rows = _read_recent(since_dt=since_dt, limit=limit, decision=decision, src=src)
    return {"count": len(rows), "events": rows}


def _parse_since(since: Optional[str]) -> datetime:
    if since:
        try:
            return datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc) - timedelta(hours=24)


def _read_recent(
    *,
    since_dt: datetime,
    limit: int,
    decision: Optional[str],
    src: Optional[str],
) -> list[dict]:
    """Scan today's + yesterday's JSONL files; filter; return newest-first.

    Beyond 48h we'd want an index — see SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md
    §8 Q9 ("when audit log scale warrants SQLite"). For v1 a linear scan
    of two files (~100MB ceiling) is fine.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    rows: list[dict] = []
    for name in (today, yesterday):
        path = paths.audit_dir() / f"{name}.jsonl"
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if decision and ev.get("decision") != decision:
                    continue
                if src and ev.get("src") != src:
                    continue
                ts_raw = ev.get("ts", "")
                try:
                    ev_ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
                if ev_ts < since_dt:
                    continue
                rows.append(ev)
        except OSError:
            continue

    rows.sort(key=lambda r: r.get("ts", ""), reverse=True)
    return rows[:limit]

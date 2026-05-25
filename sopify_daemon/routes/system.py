"""``/api/v1/reconcile`` + ``/api/v1/drift`` + ``/api/v1/status``.

System-level operations: force a reconciler tick, list drift observations,
report daemon health.
"""
from __future__ import annotations

import re

import yaml
from fastapi import APIRouter, HTTPException, Path as PathParam, Request

from .. import paths
from ..rule_writer import RuleFileError, RuleFileWriter, make_rule
from ..schema import SyncState

router = APIRouter()


# Safe-ish name for an imported rule. sbx rule IDs are UUIDs; we use a short
# prefix and keep RFC 1123 compliance (lowercase letters/digits/dashes).
_IMPORT_NAME_RE = re.compile(r"[^a-z0-9-]+")


def _import_name_from(sbx_rule_id: str, fallback_name: str | None) -> str:
    """Build an ENCM rule name from an sbx rule. Prefer the sbx rule's own
    name (if it's already RFC 1123); otherwise derive from the UUID prefix."""
    candidate = (fallback_name or "").strip().lower()
    candidate = _IMPORT_NAME_RE.sub("-", candidate).strip("-")
    if candidate and len(candidate) <= 60 and re.fullmatch(r"[a-z0-9-]+", candidate):
        return f"imported-{candidate}"
    suffix = sbx_rule_id.split("-")[0][:10] if sbx_rule_id else "unknown"
    return f"imported-{suffix.lower()}"


@router.get("/status")
async def status(request: Request) -> dict:
    backend = getattr(request.app.state, "backend", None)
    reconciler = getattr(request.app.state, "reconciler_obj", None)
    ingester = getattr(request.app.state, "audit_ingester", None)
    retention = getattr(request.app.state, "audit_retention", None)

    health = None
    if backend is not None:
        h = await backend.health_check()
        health = {
            "reachable": h.reachable,
            "version": h.version,
            "socket_path": h.socket_path,
            "error": h.error,
        }

    state = _load_sync_state_safe()
    return {
        "daemon": {
            "encm_root": str(paths.encm_root()),
        },
        "sandboxd": health,
        "reconciler": {
            "last_tick_at": reconciler.last_tick_at.isoformat() if reconciler and reconciler.last_tick_at else None,
            "last_error": reconciler.last_error if reconciler else None,
        },
        "audit_ingester": {
            "events_seen": ingester.events_seen if ingester else 0,
            "last_event_at": ingester.last_event_at.isoformat() if ingester and ingester.last_event_at else None,
            "last_error": ingester.last_error if ingester else None,
        },
        "audit_retention": (
            {
                "retention_days": retention.retention_days,
                "last_run_at": retention.last_run_at.isoformat() if retention.last_run_at else None,
                "last_result": retention.last_result,
                "last_error": retention.last_error,
            }
            if retention is not None
            else None
        ),
        "rules": {
            "count": len(state.rules),
            "drift_count": len(state.drift_observations),
        },
    }


@router.post("/reconcile")
async def reconcile_now(request: Request) -> dict:
    reconciler = getattr(request.app.state, "reconciler_obj", None)
    if reconciler is None:
        raise HTTPException(503, detail="reconciler not initialised")
    new_state = await reconciler.tick_once()
    return {
        "applied": len(new_state.rules),
        "drift_count": len(new_state.drift_observations),
        "last_reconcile_at": new_state.last_reconcile_at.isoformat()
        if new_state.last_reconcile_at else None,
    }


@router.get("/drift")
async def list_drift() -> dict:
    state = _load_sync_state_safe()
    return {
        "count": len(state.drift_observations),
        "drift": [d.model_dump(mode="json") for d in state.drift_observations],
    }


@router.post("/drift/{sbx_rule_id}/import")
async def import_drift(
    request: Request,
    sbx_rule_id: str = PathParam(..., description="sbx rule ID to adopt"),
) -> dict:
    """Adopt an sbx-side rule into an ENCM YAML file so the reconciler
    treats it as managed state. On the next tick the drift entry clears.

    The endpoint fetches the live sbx rule (via the configured backend),
    maps its resources/decision/type into a :class:`NetworkRule`, and writes
    it through :class:`RuleFileWriter` — same path the API + CLI use, so
    schema validation + atomic write happen identically.
    """
    backend = getattr(request.app.state, "backend", None)
    if backend is None:
        raise HTTPException(503, detail="backend not initialised")

    try:
        sbx_rules = await backend.list_rules()
    except Exception as exc:  # noqa: BLE001 — surface as 502 for UI
        raise HTTPException(502, detail=f"failed to list sbx rules: {exc}") from exc

    match = next((r for r in sbx_rules if r.id == sbx_rule_id), None)
    if match is None:
        raise HTTPException(404, detail=f"sbx rule {sbx_rule_id!r} not found")

    # Map sbx resource_type → ENCM rule_type. Default to "domain" for any
    # value we don't recognise — ENCM's schema validation will reject if
    # the patterns shape is wrong, which is the right failure mode (loud).
    rule_type = {
        "network": "domain",
        "domain": "domain",
        "cidr": "cidr",
        "port": "port",
    }.get(match.resource_type, "domain")

    rule = make_rule(
        name=_import_name_from(match.id, match.name),
        patterns=list(match.resources),
        decision=match.decision,
        rule_type=rule_type,
        scope=match.scope,
        sandbox_id=match.sandbox_id,
        created_by="drift-import",
        labels={"imported_from": match.id, "imported_origin": match.origin},
    )

    writer = RuleFileWriter()
    try:
        path = writer.write(rule)
    except (RuleFileError, ValueError) as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    # Kick the reconciler so the new YAML lands in .state and the drift
    # entry clears immediately on the next tick.
    reconciler = getattr(request.app.state, "reconciler_obj", None)
    if reconciler is not None:
        reconciler.kick()

    return {
        "path": str(path),
        "rule": rule.model_dump(mode="json"),
        "imported_from": sbx_rule_id,
    }


def _load_sync_state_safe() -> SyncState:
    sf = paths.sync_state_file()
    if not sf.exists():
        return SyncState()
    try:
        data = yaml.safe_load(sf.read_text(encoding="utf-8")) or {}
        return SyncState.model_validate(data)
    except Exception:
        return SyncState()

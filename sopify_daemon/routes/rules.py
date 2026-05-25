"""``/api/v1/rules`` — CRUD for ENCM rule YAML files.

All writes go through :class:`RuleFileWriter`; we never bypass it.
The route returns immediately on file write — the reconciler picks up
the change on its next tick (default 30s). Callers wanting synchronous
behaviour can ``POST /api/v1/reconcile`` to force an immediate tick.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Path as PathParam, Query, Request, status
from pydantic import BaseModel, Field

from ..rule_writer import RuleFileError, RuleFileWriter, make_rule
from ..schema import NetworkRule

router = APIRouter()


class CreateRuleRequest(BaseModel):
    """API surface for ``POST /api/v1/rules``. Less verbose than raw YAML;
    server fills in metadata defaults."""

    name: str = Field(..., description="RFC 1123 label, unique per scope")
    patterns: list[str] = Field(..., min_length=1)
    decision: str = Field(default="allow", description="allow | deny")
    rule_type: str = Field(default="domain", description="domain | cidr | port")
    scope: str = "global"
    sandbox_id: Optional[str] = None
    created_by: str = "user"
    ttl_seconds: Optional[int] = None
    labels: dict[str, str] = Field(default_factory=dict)


@router.get("/rules")
async def list_rules() -> dict:
    writer = RuleFileWriter()
    rules = writer.list_all()
    return {
        "count": len(rules),
        "rules": [r.model_dump(mode="json") for r in rules],
    }


@router.post("/rules", status_code=status.HTTP_201_CREATED)
async def create_rule(request: Request, body: CreateRuleRequest = Body(...)) -> dict:
    writer = RuleFileWriter()
    try:
        rule = make_rule(
            name=body.name,
            patterns=body.patterns,
            decision=body.decision,
            rule_type=body.rule_type,
            scope=body.scope,
            sandbox_id=body.sandbox_id,
            created_by=body.created_by,
            ttl_seconds=body.ttl_seconds,
            labels=body.labels,
        )
        path = writer.write(rule)
    except (RuleFileError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    # Kick the reconciler so the change lands in sbx within seconds
    reconciler = getattr(request.app.state, "reconciler_obj", None)
    if reconciler is not None:
        reconciler.kick()
    return {"path": str(path), "rule": rule.model_dump(mode="json")}


@router.get("/rules/{name}")
async def get_rule(
    name: str = PathParam(..., description="Rule name"),
    scope: str = Query("global"),
    sandbox_id: Optional[str] = Query(default=None),
) -> NetworkRule:
    writer = RuleFileWriter()
    if scope == "global":
        from ..paths import global_rules_dir
        path = global_rules_dir() / f"{name}.yaml"
    elif scope == "sandbox":
        if not sandbox_id:
            raise HTTPException(400, detail="sandbox_id required when scope=sandbox")
        from ..paths import sandbox_rules_dir
        path = sandbox_rules_dir(sandbox_id) / f"{name}.yaml"
    else:
        raise HTTPException(400, detail=f"unknown scope: {scope}")
    if not path.exists():
        raise HTTPException(404, detail=f"rule {name!r} not found")
    return writer.read(path)


@router.delete("/rules/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    request: Request,
    name: str = PathParam(...),
    scope: str = Query("global"),
    sandbox_id: Optional[str] = Query(default=None),
) -> None:
    writer = RuleFileWriter()
    try:
        ok = writer.delete(name=name, scope=scope, sandbox_id=sandbox_id)
    except RuleFileError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(404, detail=f"rule {name!r} not found")
    reconciler = getattr(request.app.state, "reconciler_obj", None)
    if reconciler is not None:
        reconciler.kick()


@router.post("/rules/{name}/disable")
async def disable_rule(
    request: Request,
    name: str = PathParam(...),
    scope: str = Query("global"),
    sandbox_id: Optional[str] = Query(default=None),
) -> dict:
    writer = RuleFileWriter()
    try:
        path = writer.disable(name=name, scope=scope, sandbox_id=sandbox_id)
    except RuleFileError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    reconciler = getattr(request.app.state, "reconciler_obj", None)
    if reconciler is not None:
        reconciler.kick()
    return {"path": str(path), "decision": "deny"}

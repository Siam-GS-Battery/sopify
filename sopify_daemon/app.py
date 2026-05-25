"""FastAPI scaffold for the sopify daemon.

Binds to 127.0.0.1 only (localhost-only — see SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md
§1.5 + §7 anti-pattern "do not bind to 0.0.0.0"). Every ``/api/v1/**`` route
requires a bearer token (Jupyter pattern).

Lifecycle:

  startup → load config, build backend, ensure FS skeleton, start
            reconciler + audit ingester as background tasks
  request → routes hit the protected REST surface
  shutdown → cancel tasks, close backend HTTP client cleanly
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from . import config as daemon_config
from . import paths
from .audit_ingester import AuditIngester
from .auth import verify_token
from .reconciler import Reconciler
from .retention import AuditRetentionTask
from .routes import audit as audit_route
from .routes import rules as rules_route
from .routes import system as system_route
from .sbx_backend import SbxBackend

log = logging.getLogger("sopify_daemon")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup + shutdown — owns the long-lived backend + asyncio tasks."""
    cfg = daemon_config.load(create_if_missing=True)
    app.state.config = cfg
    app.state.token = cfg.token

    paths.ensure_skeleton()
    _write_pid_file()

    socket_path = Path(cfg.sandboxd_socket).expanduser() if cfg.sandboxd_socket else None
    backend = SbxBackend(socket_path=socket_path)
    app.state.backend = backend

    reconciler = Reconciler(backend)
    app.state.reconciler_obj = reconciler

    ingester = AuditIngester(backend, reconciler)
    app.state.audit_ingester = ingester

    retention = AuditRetentionTask(retention_days=cfg.audit_retention_days)
    app.state.audit_retention = retention

    reconciler_task = asyncio.create_task(
        reconciler.run_forever(cfg.reconciler_interval_seconds),
        name="encm-reconciler",
    )
    ingester_task = asyncio.create_task(
        ingester.run_forever(),
        name="encm-audit-ingester",
    )
    retention_task = asyncio.create_task(
        retention.run_forever(),
        name="encm-audit-retention",
    )
    app.state.background_tasks = [reconciler_task, ingester_task, retention_task]

    log.info(
        "sopify daemon up: bind=%s:%d, encm_root=%s, sandboxd=%s",
        cfg.bind, cfg.port, paths.encm_root(), backend._socket_path,  # noqa: SLF001
    )

    try:
        yield
    finally:
        reconciler.stop()
        ingester.stop()
        retention.stop()
        for t in app.state.background_tasks:
            t.cancel()
        for t in app.state.background_tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        await backend.close()
        _remove_pid_file()


def _write_pid_file() -> None:
    """Drop ``~/.sopify/daemon.pid`` so ``sopify stop`` can find us.

    If a stale pid file is already there, we replace it — uvicorn already
    failed to bind the port if another live daemon owns it, so reaching
    this code means our PID is the new authoritative one."""
    import os
    pid_path = paths.pid_file()
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")


def _remove_pid_file() -> None:
    """Best-effort removal on clean shutdown. Stale PIDs are tolerated."""
    try:
        paths.pid_file().unlink(missing_ok=True)
    except OSError:
        pass


def create_app() -> FastAPI:
    """Factory — used by uvicorn (`sopify_daemon.app:create_app`) and tests."""
    app = FastAPI(
        title="Sopify Daemon",
        version="0.1.0",
        description=(
            "Local-only control plane for ENCM. Bearer token required on "
            "every /api/v1/** call. See SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md."
        ),
        lifespan=lifespan,
    )

    protected = [Depends(verify_token)]
    app.include_router(rules_route.router, prefix="/api/v1", dependencies=protected, tags=["rules"])
    app.include_router(audit_route.router, prefix="/api/v1", dependencies=protected, tags=["audit"])
    app.include_router(system_route.router, prefix="/api/v1", dependencies=protected, tags=["system"])

    @app.get("/health", tags=["health"])
    async def public_health() -> JSONResponse:
        """Unauthenticated liveness probe — for systemd/launchd watchdogs."""
        return JSONResponse({"status": "ok"})

    return app


# uvicorn target — `uvicorn sopify_daemon.app:app`
app = create_app()


def run() -> None:
    """Entry point for the ``sopify start`` subcommand. Blocks."""
    import uvicorn
    cfg = daemon_config.load(create_if_missing=True)
    uvicorn.run(
        "sopify_daemon.app:app",
        host=cfg.bind,
        port=cfg.port,
        log_level="info",
        reload=False,
    )

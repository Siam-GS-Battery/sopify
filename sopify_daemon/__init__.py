"""sopify_daemon — the local FastAPI service that owns the ENCM Control Plane.

Architecture:
  - Single-process daemon, binds 127.0.0.1:7777 by default
  - Bearer-token auth (Jupyter-style) — token lives at ~/.sopify/config.yaml
  - Reconciler + audit ingester run as asyncio tasks in the same event loop
  - User-facing CLI (`sopify start/stop/rules/...`) is a thin HTTP client
  - Web UI (when built) is served as static assets at `/`
  - Data plane = sandboxd over Unix socket via :class:`sopify_daemon.sbx_backend.SbxBackend`

Out of scope:
  - Custom HTTPS interception (archived 2026-05-24)
  - Database — all state lives on the filesystem under ~/.sopify/encm/

See SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md for the full design.
"""
from __future__ import annotations

__version__ = "0.1.0"

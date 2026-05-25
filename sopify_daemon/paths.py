"""Filesystem layout for ENCM Control Plane state.

Centralised so the reconciler, writer, audit ingester, and tests all see
the same locations. ``SOPIFY_ENCM_ROOT`` env var overrides the default
for tests/dev setups.

Layout (see SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md §3 Week 2)::

    $SOPIFY_ENCM_ROOT/   (default ~/.sopify/encm/)
    ├── rules/
    │   ├── global/
    │   │   └── <name>.yaml
    │   └── sandboxes/
    │       └── <sandbox-id>/
    │           └── <name>.yaml
    ├── audit/
    │   ├── YYYY-MM-DD.jsonl
    │   └── archive/                 # compressed older files
    └── .state/                      # reconciler-owned, never edit by hand
        ├── sync.yaml
        └── sync.yaml.lock
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_ROOT = "SOPIFY_ENCM_ROOT"
ENV_CONFIG = "SOPIFY_CONFIG_DIR"  # ~/.sopify/ (parent of encm/) for token + port


def encm_root() -> Path:
    """Base directory for all ENCM state. Override with ``SOPIFY_ENCM_ROOT``."""
    override = os.environ.get(ENV_ROOT)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".sopify" / "encm"


def sopify_config_dir() -> Path:
    """``~/.sopify/`` — parent of ``encm/`` + holds ``config.yaml`` (token, port)."""
    override = os.environ.get(ENV_CONFIG)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".sopify"


def rules_dir() -> Path:
    return encm_root() / "rules"


def global_rules_dir() -> Path:
    return rules_dir() / "global"


def sandbox_rules_dir(sandbox_id: str) -> Path:
    return rules_dir() / "sandboxes" / sandbox_id


def audit_dir() -> Path:
    return encm_root() / "audit"


def audit_archive_dir() -> Path:
    return audit_dir() / "archive"


def state_dir() -> Path:
    return encm_root() / ".state"


def sync_state_file() -> Path:
    return state_dir() / "sync.yaml"


def sync_state_lock_file() -> Path:
    return state_dir() / "sync.yaml.lock"


def config_file() -> Path:
    return sopify_config_dir() / "config.yaml"


def pid_file() -> Path:
    """``~/.sopify/daemon.pid`` — written on startup, removed on clean
    shutdown. Used by ``sopify stop`` to find the running daemon."""
    return sopify_config_dir() / "daemon.pid"


def ensure_skeleton() -> None:
    """Create every directory the daemon expects. Idempotent — safe to call
    multiple times. Permissions kept default; the auth token + sync lock
    are the only items that strictly need 0600."""
    for d in (
        encm_root(),
        rules_dir(),
        global_rules_dir(),
        rules_dir() / "sandboxes",
        audit_dir(),
        audit_archive_dir(),
        state_dir(),
        sopify_config_dir(),
    ):
        d.mkdir(parents=True, exist_ok=True)

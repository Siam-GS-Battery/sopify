"""Daemon-level config — token, port, sandboxd socket override.

Lives at ``~/.sopify/config.yaml`` mode 0600. Created on first
``sopify start`` if missing; never overwritten silently.

Format::

    token: <64-hex-char hex string>
    port: 7777
    bind: 127.0.0.1
    sandboxd_socket: null            # null = auto-detect
    reconciler_interval_seconds: 30
    audit_retention_days: 90
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from .paths import config_file, sopify_config_dir


@dataclass(slots=True)
class DaemonConfig:
    """In-memory representation of ``~/.sopify/config.yaml``."""

    token: str
    port: int = 7777
    bind: str = "127.0.0.1"
    sandboxd_socket: Optional[str] = None  # None = auto-detect
    reconciler_interval_seconds: int = 30
    audit_retention_days: int = 90
    # `tags` are for IT-managed installs that want to label this daemon
    # (e.g. "department=rd-i-03"). Free-form; not enforced.
    tags: dict[str, str] = field(default_factory=dict)


_FILE_MODE = 0o600


def _generate_token() -> str:
    """256-bit token, hex-encoded → 64 chars. Same shape as Jupyter."""
    return secrets.token_hex(32)


def load(*, create_if_missing: bool = True) -> DaemonConfig:
    """Load config; generate one with a fresh token on first run."""
    path = config_file()
    if not path.exists():
        if not create_if_missing:
            raise FileNotFoundError(
                f"Sopify config not found at {path}; run `sopify install` first"
            )
        sopify_config_dir().mkdir(parents=True, exist_ok=True)
        cfg = DaemonConfig(token=_generate_token())
        save(cfg)
        return cfg

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config at {path} is not a mapping")
    token = data.get("token")
    if not token or not isinstance(token, str) or len(token) < 32:
        raise ValueError(
            f"config at {path} missing or short token; delete the file "
            "to regenerate (rotates the bearer secret)"
        )
    return DaemonConfig(
        token=token,
        port=int(data.get("port", 7777)),
        bind=str(data.get("bind", "127.0.0.1")),
        sandboxd_socket=data.get("sandboxd_socket"),
        reconciler_interval_seconds=int(data.get("reconciler_interval_seconds", 30)),
        audit_retention_days=int(data.get("audit_retention_days", 90)),
        tags=dict(data.get("tags") or {}),
    )


def save(cfg: DaemonConfig) -> Path:
    """Persist + tighten mode to 0600. Atomic write."""
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "token": cfg.token,
        "port": cfg.port,
        "bind": cfg.bind,
        "sandboxd_socket": cfg.sandboxd_socket,
        "reconciler_interval_seconds": cfg.reconciler_interval_seconds,
        "audit_retention_days": cfg.audit_retention_days,
        "tags": cfg.tags,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "# Sopify daemon config. The `token` is a bearer secret —\n"
        "# never commit this file, never share it.\n"
        + yaml.safe_dump(payload, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    tmp.replace(path)
    try:
        os.chmod(path, _FILE_MODE)
    except (PermissionError, NotImplementedError):
        # Windows / restricted FS — best-effort
        pass
    return path

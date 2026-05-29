"""
Helpers Function for finding folder and file state
Canonical paths for Sopify config / state.

REQ traceability:
  REQ-1.2.6 / REQ-1.2.7 / REQ-1.2.8 — mount points
  REQ-2.2.1 — auth.json at 0600
  REQ-6.3.1 — profile.json (role) IT-owned
  REQ-9.1.1 — settings.json (managed, 0444)
"""
from __future__ import annotations
import os
from pathlib import Path


def home() -> Path:
    """Sopify root dir on the host. Overridable via $SOPIFY_HOME for tests."""
    override = os.environ.get("SOPIFY_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".sopify"


def settings_file() -> Path:
    """IT-managed settings (read-only for user, mode 0444)."""
    return home() / "settings.json"


def profile_file() -> Path:
    """User role + identity (IT-set, mode 0444)."""
    return home() / "profile.json"


def auth_file() -> Path:
    """API keys (user-owned, mode 0600)."""
    return home() / "auth.json"


def network_policy_file() -> Path:
    """Egress whitelist for the sandbox container."""
    return home() / "network-policy.json"


def sessions_dir() -> Path:
    """Persistent session DB dir (mounted into /sopify-sessions)."""
    return home() / "sessions"


def ensure_directories() -> None:
    """Create dirs if missing. Idempotent; safe to call from `sopify install`."""
    home().mkdir(parents=True, exist_ok=True, mode=0o700)
    sessions_dir().mkdir(parents=True, exist_ok=True, mode=0o700)

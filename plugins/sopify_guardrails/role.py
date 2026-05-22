"""User role read from `~/.sopify/profile.json`.

REQ-6.3.1 — IT writes profile.json on install.
REQ-6.3.2 — user cannot modify (file perm + this loader's validator).
REQ-6.3.4 — values: "user" (default) | "dev".
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

Role = Literal["user", "dev"]


def _profile_path() -> Path:
    home = os.environ.get("SOPIFY_HOME") or os.path.expanduser("~/.sopify")
    return Path(home) / "profile.json"


def current_role() -> Role:
    """Returns 'user' by default. Validates value strictly."""
    p = _profile_path()
    if not p.exists():
        return "user"
    try:
        data = json.loads(p.read_text())
    except Exception:
        return "user"
    role = data.get("role", "user")
    if role not in ("user", "dev"):
        return "user"  # REQ-6.3.2 defensive
    return role


def assert_dev_only(action: str) -> None:
    """Raise if not dev. Used by `sopify admin set-role`."""
    if current_role() != "dev":
        raise PermissionError(
            f"sopify-guardrails: {action!r} requires role:dev (REQ-6.3.3). "
            f"Contact IT to escalate."
        )


def set_role(target_user: str, role: Role) -> None:
    """REQ-6.3.3 — `sopify admin set-role`. Caller must already be dev."""
    if role not in ("user", "dev"):
        raise ValueError(f"role must be 'user' or 'dev', got {role!r}")
    assert_dev_only("admin set-role")
    p = _profile_path()
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text())
        except Exception:
            data = {}
    data["role"] = role
    data["user"] = target_user
    p.write_text(json.dumps(data, indent=2))
    p.chmod(0o444)  # REQ-9.1.1 — read-only for the user

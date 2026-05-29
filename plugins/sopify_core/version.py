"""sopify version reporting.

REQ-0.5 — `sopify --version` shows Sopify version *and* its underlying
runtime version (the upstream fork — see SOPIFY_ARCH.md).
"""
from __future__ import annotations
import importlib.metadata as md
SOPIFY_VERSION = "0.1.0"


def sopify_version() -> str:
    return SOPIFY_VERSION


def runtime_version() -> str:
    """Best-effort lookup of the bundled runtime (upstream fork) version."""
    # Pip package names are fixed by the upstream we forked from; do not rename.
    for dist_name in ("hermes-agent", "hermes_agent", "hermes"):
        try:
            return md.version(dist_name)
        except md.PackageNotFoundError:
            continue
    return "unknown"


# Keep the old name as an alias so any caller that imported it keeps working.
hermes_version = runtime_version


def full_version_string() -> str:
    """Render for `sopify --version`."""
    return f"sopify {sopify_version()} (runtime {runtime_version()})"

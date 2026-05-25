"""Proxy helper: forward dashboard requests to the local Sopify daemon.

The dashboard is served by the Hermes web server (different process) but the
ENCM control plane runs in its own daemon at ``127.0.0.1:7777`` with a bearer
token. Instead of teaching the React app two auth schemes, the web server
proxies ``/api/encm/*`` to the daemon's ``/api/v1/*`` and attaches the bearer
token server-side. The browser keeps its existing ``X-Hermes-Session-Token``
auth and never sees the daemon's secret.

Token + port are read from ``~/.sopify/config.yaml`` each call (cheap: a few
dozen bytes); no long-lived cache, so rotating the token by deleting the
config file takes effect on the next request.
"""
from __future__ import annotations

import glob
import logging
import os
from pathlib import Path
from typing import Any, Optional

import yaml

_log = logging.getLogger(__name__)

_DEFAULT_PORT = 7777
_DEFAULT_BIND = "127.0.0.1"
_REQUEST_TIMEOUT = 10.0
# Docker Desktop's host-gateway hostname — resolves to the host machine from
# inside a Docker / sbx microVM on macOS + Windows. The daemon binds to
# 127.0.0.1 on the host, so from inside a sandbox we must rewrite to this
# name. Linux Docker uses the same hostname when the extra_hosts/host-gateway
# flag is set, which sbx does by default.
_SANDBOX_HOST_GATEWAY = "host.docker.internal"


class DaemonUnavailable(Exception):
    """Daemon not running or config missing — caller renders 503."""


def _in_sandbox() -> bool:
    """True when running inside the sbx microVM (set by sopify-kit spec)."""
    return os.environ.get("SOPIFY_IN_SANDBOX") == "1"


def _config_path() -> Path:
    """Resolve the daemon's ``config.yaml`` location.

    Host: always ``~/.sopify/config.yaml`` (where the daemon writes it).
    Sandbox: sbx_launcher.py mounts host ``~/.sopify`` read-only into the
    microVM, but sbx preserves the host's absolute path — e.g. on macOS the
    file lands at ``/Users/<name>/.sopify/config.yaml`` not ``$HOME/.sopify/``.
    Probe a few common locations + fall back to a glob across user homes.
    """
    primary = Path.home() / ".sopify" / "config.yaml"
    if primary.exists():
        return primary
    if not _in_sandbox():
        return primary  # let the caller error with the expected path
    for candidate in glob.glob("/Users/*/.sopify/config.yaml") + glob.glob(
        "/home/*/.sopify/config.yaml"
    ):
        if Path(candidate).exists():
            return Path(candidate)
    return primary


def _read_config() -> tuple[str, str, int]:
    """Return ``(token, bind, port)`` or raise ``DaemonUnavailable``.

    Re-read on every call — the config is tiny and the daemon may rotate
    its token without notifying us.
    """
    config_path = _config_path()
    if not config_path.exists():
        raise DaemonUnavailable(
            f"sopify daemon config not found at {config_path}; "
            "run `sopify start` once on the host to generate it"
        )
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise DaemonUnavailable(f"failed to read sopify config: {exc}") from exc
    token = data.get("token")
    if not isinstance(token, str) or len(token) < 32:
        raise DaemonUnavailable("sopify config missing or invalid token")
    bind = str(data.get("bind", _DEFAULT_BIND))
    # Inside the sandbox, ``127.0.0.1`` resolves to the microVM's own loopback,
    # not the host where the daemon lives. Swap to the Docker host-gateway
    # hostname so the proxy actually reaches the daemon.
    if _in_sandbox() and bind in {"127.0.0.1", "localhost", "::1"}:
        bind = _SANDBOX_HOST_GATEWAY
    return (
        token,
        bind,
        int(data.get("port", _DEFAULT_PORT)),
    )


async def proxy(
    method: str,
    path: str,
    *,
    query: Optional[dict[str, Any]] = None,
    body: Optional[Any] = None,
) -> tuple[int, Any]:
    """Forward a request to the daemon. ``path`` is relative to ``/api/v1/``.

    Returns ``(status_code, parsed_json_or_text)``. The caller is expected to
    propagate the status as the dashboard response. On daemon-unreachable
    errors returns ``(503, {"detail": ...})``.
    """
    import httpx  # local import — match the pattern used elsewhere

    try:
        token, bind, port = _read_config()
    except DaemonUnavailable as exc:
        return 503, {"detail": str(exc), "reachable": False}

    url = f"http://{bind}:{port}/api/v1/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.request(
                method.upper(),
                url,
                params=query,
                json=body if body is not None else None,
                headers=headers,
            )
    except httpx.ConnectError as exc:
        return 503, {
            "detail": f"sopify daemon not reachable at {bind}:{port}: {exc}",
            "reachable": False,
        }
    except httpx.HTTPError as exc:
        _log.exception("ENCM proxy error to %s", url)
        return 502, {"detail": f"proxy error: {exc}"}

    if resp.status_code == 204:
        return 204, None
    ct = resp.headers.get("content-type", "")
    if "application/json" in ct:
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {"detail": resp.text}
    return resp.status_code, resp.text


def daemon_url() -> Optional[str]:
    """Best-effort URL for the local daemon — used by status panels.

    Returns ``None`` if the config can't be read; callers should treat that
    as "daemon not installed yet" rather than an error.
    """
    try:
        _, bind, port = _read_config()
    except DaemonUnavailable:
        return None
    return f"http://{bind}:{port}"

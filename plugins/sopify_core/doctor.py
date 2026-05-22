"""`sopify doctor` — health check.

REQ-0.8 — check auth, sandbox, OTel connectivity.
REQ-1.1.5 — sandbox health (image exists, network ready, permissions).
Acceptance gate P2 — doctor reports sandbox status within < 3s.
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from typing import List
from urllib.parse import urlparse

from . import paths


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class DoctorReport:
    checks: List[Check] = field(default_factory=list)
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


def _check_docker() -> Check:
    if not shutil.which("docker"):
        return Check("docker", False, "docker CLI not on PATH (REQ-1.1.2)")
    try:
        out = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=2,
        )
    except subprocess.TimeoutExpired:
        return Check("docker", False, "docker info timed out (daemon not running?)")
    if out.returncode != 0:
        return Check("docker", False, out.stderr.strip()[:120])
    return Check("docker", True, f"daemon {out.stdout.strip()}")


def _check_sandbox_image() -> Check:
    try:
        out = subprocess.run(
            ["docker", "image", "inspect", "sopify-sandbox:latest"],
            capture_output=True, text=True, timeout=2,
        )
    except Exception as exc:
        return Check("sandbox-image", False, f"docker inspect failed: {exc}")
    ok = out.returncode == 0
    return Check("sandbox-image", ok,
                 "image present" if ok else "run `sopify install` to pull")


def _check_sandbox_network() -> Check:
    try:
        out = subprocess.run(
            ["docker", "network", "inspect", "sopify-net"],
            capture_output=True, text=True, timeout=2,
        )
    except Exception as exc:
        return Check("sandbox-net", False, str(exc))
    ok = out.returncode == 0
    return Check("sandbox-net", ok,
                 "bridge ready" if ok else "missing — run `sopify install`")


def _check_auth() -> Check:
    f = paths.auth_file()
    if not f.exists():
        return Check("auth", False, "no auth.json — run `sopify login`")
    mode = f.stat().st_mode & 0o777
    if mode != 0o600:
        return Check("auth", False, f"auth.json mode is {mode:o}, expected 600 (REQ-11.1)")
    return Check("auth", True, "auth.json OK (0600)")


def _check_otel(endpoint: str | None) -> Check:
    if not endpoint:
        return Check("otel", True, "no endpoint configured (skip)")
    try:
        host = urlparse(endpoint).hostname or endpoint
        port = urlparse(endpoint).port or 4317
        with socket.create_connection((host, port), timeout=1):
            return Check("otel", True, f"reachable {host}:{port}")
    except Exception as exc:
        # REQ-7.2.4 — collector unreachable must NOT block sopify; doctor only reports.
        return Check("otel", False, f"unreachable: {exc} (sessions still work)")


def _load_settings() -> dict:
    f = paths.settings_file()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text())
    except Exception:
        return {}


def _check_sbx() -> Check:
    """REQ-1.2.1 — preferred sandbox backend (Docker Sandboxes / microVM)."""
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
        from plugins.sopify_sandbox import sbx_launcher  # type: ignore
    except Exception as exc:
        return Check("sbx", False, f"import failed: {exc}")
    summary = sbx_launcher.status_summary()
    ok = summary.startswith("sbx OK")
    return Check("sbx", ok, summary)


def run() -> DoctorReport:
    start = time.time()
    settings = _load_settings()
    report = DoctorReport(
        checks=[
            _check_sbx(),               # preferred microVM backend
            _check_docker(),            # fallback backend
            _check_sandbox_image(),
            _check_sandbox_network(),
            _check_auth(),
            _check_otel(settings.get("otel_endpoint")),
        ]
    )
    report.elapsed_ms = int((time.time() - start) * 1000)
    return report


def format_report(report: DoctorReport) -> str:
    lines = ["sopify doctor"]
    for c in report.checks:
        mark = "OK " if c.ok else "FAIL"
        lines.append(f"  [{mark}] {c.name:14s} — {c.detail}")
    lines.append(f"  ({report.elapsed_ms} ms)")
    return "\n".join(lines)

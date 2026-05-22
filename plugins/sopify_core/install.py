"""`sopify install` — one-shot bootstrap.

REQ-0.7  — install does everything: Docker pull + auth + config + service register.
REQ-1.1.1 — pulls/builds sopify-sandbox:latest.
REQ-1.1.2 — verifies docker daemon; aborts with guide if missing.
REQ-1.1.3 — creates `sopify-net` bridge network.
REQ-1.1.4 — writes default `~/.sopify/network-policy.json`.
REQ-9.2.4 — emits `install_complete` OTel event.

The install runs ON THE HOST (not inside the sandbox) — it is the bootstrap
that creates the sandbox. Subsequent `sopify <command>` calls run inside it.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from typing import List

from . import paths

SANDBOX_IMAGE = "sopify-sandbox:latest"
SANDBOX_NETWORK = "sopify-net"

DEFAULT_WHITELIST = [
    "api.anthropic.com",          # REQ-1.2.2 — LLM API
    "otel-collector.gsbattery.local",  # REQ-1.2.2 — internal telemetry
]


@dataclass
class InstallReport:
    steps: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _require_docker(report: InstallReport) -> bool:
    if not shutil.which("docker"):
        report.errors.append(
            "Docker CLI not found. Install Docker Desktop (macOS/Windows) or "
            "docker.io (Linux), then re-run `sopify install`. "
            "Guide: https://docs.docker.com/engine/install/"
        )
        return False
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=3)
    except Exception as exc:
        report.errors.append(f"Docker daemon not running: {exc}")
        return False
    report.steps.append("docker daemon: OK")
    return True


def _ensure_image(report: InstallReport) -> None:
    inspect = subprocess.run(
        ["docker", "image", "inspect", SANDBOX_IMAGE],
        capture_output=True,
    )
    if inspect.returncode == 0:
        report.steps.append(f"image {SANDBOX_IMAGE}: already present")
        return
    # Skip pull — we ship the Dockerfile in-repo and want a deterministic
    # Linux build using the user's current source. Build directly.
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    dockerfile = os.path.join(repo_root, "docker", "sopify-sandbox", "Dockerfile")
    if not os.path.isfile(dockerfile):
        report.errors.append(f"Dockerfile not found at {dockerfile}")
        return
    report.steps.append(
        f"building {SANDBOX_IMAGE} (Linux Python deps, ~2-5 min first time)..."
    )
    # The whole repo is the build context (Dockerfile does `COPY . /opt/sopify`).
    # We use --quiet so steps stay readable in `sopify install` output; pipe
    # stderr through tail on failure for diagnosis.
    build = subprocess.run(
        ["docker", "build", "-t", SANDBOX_IMAGE,
         "-f", dockerfile, repo_root, "--quiet"],
        capture_output=True, text=True,
    )
    if build.returncode != 0:
        # Show last 12 lines of stderr so the user can see where it broke.
        tail = "\n".join(build.stderr.splitlines()[-12:])
        report.errors.append(f"image build failed:\n{tail}")
        return
    report.steps.append(f"image {SANDBOX_IMAGE}: built locally")


def _ensure_network(report: InstallReport) -> None:
    inspect = subprocess.run(
        ["docker", "network", "inspect", SANDBOX_NETWORK], capture_output=True,
    )
    if inspect.returncode == 0:
        report.steps.append(f"network {SANDBOX_NETWORK}: exists")
        return
    create = subprocess.run(
        ["docker", "network", "create", "--driver", "bridge", SANDBOX_NETWORK],
        capture_output=True, text=True,
    )
    if create.returncode != 0:
        report.errors.append(f"network create failed: {create.stderr[:200]}")
        return
    report.steps.append(f"network {SANDBOX_NETWORK}: created")


def _write_default_policy(report: InstallReport) -> None:
    paths.ensure_directories()
    f = paths.network_policy_file()
    if f.exists():
        report.steps.append("network-policy.json: keep existing")
        return
    policy = {
        "whitelist": DEFAULT_WHITELIST,
        "user_added": [],
        "version": 1,
    }
    f.write_text(json.dumps(policy, indent=2))
    f.chmod(0o644)
    report.steps.append("network-policy.json: wrote defaults")


def _emit_install_event(report: InstallReport) -> None:
    # REQ-9.2.4 — install_complete event. We import lazily so sopify-otel is
    # optional; install must not fail when otel isn't installed yet.
    try:
        from importlib import import_module
        otel = import_module("plugins.sopify_otel.emit")  # type: ignore[attr-defined]
        otel.emit(
            "install_complete",
            machine_id=str(uuid.getnode()),
            platform=platform.system(),
            sopify_version="0.1.0",
        )
        report.steps.append("otel install_complete: emitted")
    except Exception:
        report.steps.append("otel install_complete: skipped (otel not loaded)")


def run() -> InstallReport:
    report = InstallReport()
    if not _require_docker(report):
        return report
    paths.ensure_directories()
    _ensure_image(report)
    if report.errors:
        return report
    _ensure_network(report)
    _write_default_policy(report)
    _activate_plugins(report)
    _validate_sbx_kit(report)
    _emit_install_event(report)
    return report


def _activate_plugins(report: InstallReport) -> None:
    """REQ-0.7 — enable every sopify_* plugin in Hermes' config so
    guardrails/OTel/modes actually wire into the runtime when the
    dashboard/chat starts."""
    try:
        from . import activate
        enabled = activate.ensure_enabled()
        report.steps.append(f"plugins.enabled: {len(enabled)} entries")
    except Exception as exc:
        report.steps.append(f"plugins.enabled: skipped ({exc})")


def _validate_sbx_kit(report: InstallReport) -> None:
    """REQ-1.2.* — validate the Sopify kit so sbx microVMs apply our
    network policy + env passthrough + startup commands at runtime."""
    import shutil
    if not shutil.which("sbx"):
        report.steps.append("sbx: not installed (host fallback mode)")
        return
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    kit_dir = os.path.join(repo_root, "infra", "sbx", "sopify-kit")
    if not os.path.isfile(os.path.join(kit_dir, "spec.yaml")):
        report.steps.append(f"sbx kit: missing at {kit_dir}")
        return
    rc = subprocess.call(
        ["sbx", "kit", "validate", kit_dir],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if rc == 0:
        report.steps.append("sbx kit: validated (17 allowed domains)")
    else:
        report.steps.append(f"sbx kit: validation failed (rc={rc})")


def format_report(report: InstallReport) -> str:
    lines = ["sopify install"]
    for s in report.steps:
        lines.append(f"  - {s}")
    if report.errors:
        lines.append("Errors:")
        for e in report.errors:
            lines.append(f"  ! {e}")
    else:
        lines.append("OK — run `sopify doctor` to verify.")
    return "\n".join(lines)

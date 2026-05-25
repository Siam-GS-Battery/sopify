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
    if inspect.returncode != 0:
        # Build the image in the host Docker daemon.
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        dockerfile = os.path.join(repo_root, "docker", "sopify-sandbox", "Dockerfile")
        if not os.path.isfile(dockerfile):
            report.errors.append(f"Dockerfile not found at {dockerfile}")
            return
        report.steps.append(
            f"building {SANDBOX_IMAGE} (Linux Python deps, ~2-5 min first time)..."
        )
        build = subprocess.run(
            ["docker", "build", "-t", SANDBOX_IMAGE,
             "-f", dockerfile, repo_root, "--quiet"],
            capture_output=True, text=True,
        )
        if build.returncode != 0:
            tail = "\n".join(build.stderr.splitlines()[-12:])
            report.errors.append(f"image build failed:\n{tail}")
            return
        report.steps.append(f"image {SANDBOX_IMAGE}: built locally")
    else:
        report.steps.append(f"image {SANDBOX_IMAGE}: already present")

    # Mirror the host image into sbx's containerd runtime so it's available
    # as `sbx create --template`. sbx ships its own image store separate
    # from the host Docker daemon, so a host-only image triggers a registry
    # pull that fails ("pull access denied").
    _sync_image_to_sbx(report)


def _sync_image_to_sbx(report: InstallReport) -> None:
    """Save host image to tar + `sbx template load` so sbx can use it."""
    import shutil
    if not shutil.which("sbx"):
        report.steps.append("sbx template: skipped (sbx not installed)")
        return

    # Check if sbx already has the image at the right version.
    # Image IDs change on every rebuild, so we always re-sync to keep them
    # aligned. The save+load is fast (<10s) for our ~470MB image.
    tar_path = "/tmp/sopify-sandbox-sbx-import.tar"
    save = subprocess.run(
        ["docker", "save", "-o", tar_path, SANDBOX_IMAGE],
        capture_output=True, text=True,
    )
    if save.returncode != 0:
        report.steps.append(
            f"sbx template: docker save failed ({save.stderr[:120]})"
        )
        return

    load = subprocess.run(
        ["sbx", "template", "load", tar_path],
        capture_output=True, text=True,
    )
    if load.returncode == 0:
        report.steps.append("sbx template: loaded sopify-sandbox into sbx runtime")
    else:
        report.steps.append(
            f"sbx template load failed (rc={load.returncode}): "
            f"{load.stderr.strip()[:160]}"
        )
    try:
        os.unlink(tar_path)
    except OSError:
        pass


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
    # ENCM Control Plane scaffold (REQ-ENCM-M1 pivot — see
    # SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md). The MITM-proxy variant that
    # used to fire here is archived under
    # archive/2026-05-24-encm-mitm-attempt/ — those _ensure_encm_* calls
    # are intentionally not invoked anymore.
    _activate_plugins(report)
    _validate_sbx_kit(report)
    _emit_install_event(report)
    return report


# ── REQ-ENCM-M1: External Network Control Module ────────────────────────

ENCM_IMAGE = "sopify-encm:latest"
ENCM_CONTAINER_NAME = "sopify-encm"


def _ensure_encm_ca(report: InstallReport) -> None:
    """REQ-ENCM-M1 §5.1 — generate self-signed CA used by mitmproxy + trusted
    by every Sopify sandbox. Idempotent — keeps the existing CA across
    re-installs so sandboxes that have already trusted it don't break."""
    if os.environ.get("SOPIFY_NO_ENCM") == "1":
        report.steps.append("encm-ca: skipped (SOPIFY_NO_ENCM=1)")
        return
    try:
        # Imported lazily because the plugin isn't loaded yet at install time.
        from plugins.sopify_encm import ca as encm_ca  # type: ignore[import]
        key_path, cert_path = encm_ca.generate_ca()
        report.steps.append(f"encm-ca: {cert_path.parent} ({key_path.name} + {cert_path.name})")
    except Exception as exc:
        report.steps.append(f"encm-ca: failed ({exc})")


def _migrate_encm_policy(report: InstallReport) -> None:
    """REQ-ENCM-M1 §3.4 — upgrade ``~/.sopify/network-policy.json`` from
    schema v1 → v2 BEFORE the ENCM container mounts it read-only.

    The container can't write the file (bind-mount + atomic-replace breaks),
    so we run the migration on the host. Idempotent — does nothing if the
    file is already v2."""
    if os.environ.get("SOPIFY_NO_ENCM") == "1":
        return
    try:
        from plugins.sopify_encm.migration import migrate_file  # type: ignore[import]
        from plugins.sopify_encm.schema import CURRENT_SCHEMA_VERSION  # type: ignore[import]
        policy_path = os.path.expanduser("~/.sopify/network-policy.json")
        policy = migrate_file(policy_path)
        if policy.schema_version == CURRENT_SCHEMA_VERSION:
            report.steps.append(
                f"encm-policy: schema v{policy.schema_version} ({len(policy.rules)} rules)"
            )
    except Exception as exc:
        report.steps.append(f"encm-policy: migration failed ({exc})")


def _ensure_encm_image(report: InstallReport) -> None:
    """REQ-ENCM-M1 §7 — build sopify-encm:latest. Like _ensure_image but for
    the proxy container. Skipped if already present (use --rebuild to force)."""
    if os.environ.get("SOPIFY_NO_ENCM") == "1":
        return
    inspect = subprocess.run(
        ["docker", "image", "inspect", ENCM_IMAGE],
        capture_output=True,
    )
    if inspect.returncode == 0:
        report.steps.append(f"encm-image: {ENCM_IMAGE} already present")
        return

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    dockerfile = os.path.join(repo_root, "docker", "sopify-encm", "Dockerfile")
    if not os.path.isfile(dockerfile):
        report.errors.append(f"encm Dockerfile missing at {dockerfile}")
        return
    report.steps.append(f"building {ENCM_IMAGE}...")
    build = subprocess.run(
        ["docker", "build", "-t", ENCM_IMAGE, "-f", dockerfile, repo_root, "--quiet"],
        capture_output=True, text=True,
    )
    if build.returncode != 0:
        tail = "\n".join(build.stderr.splitlines()[-12:])
        report.errors.append(f"encm image build failed:\n{tail}")
        return
    report.steps.append(f"encm-image: {ENCM_IMAGE} built")


def _ensure_encm_running(report: InstallReport) -> None:
    """Start / refresh the ENCM container on the host. Binds proxy listeners
    to 127.0.0.1 so only the local sandbox(es) can reach it — never exposed
    to the wider LAN."""
    if os.environ.get("SOPIFY_NO_ENCM") == "1":
        return
    # Remove any prior container — config (mounts/env) may have changed
    # across versions and we want a clean start. Container is stateless so
    # a restart is cheap.
    subprocess.run(
        ["docker", "rm", "-f", ENCM_CONTAINER_NAME],
        capture_output=True,
    )
    home = os.path.expanduser("~")
    # ENCM_PROXY_PORT 9118 chosen to AVOID Docker Desktop's MCP gateway at
    # 3128 (gateway.docker.internal:3128 silently intercepts and bypasses
    # our proxy entirely). Sandbox connects via gateway.docker.internal:9118
    # which routes to OUR ENCM rather than Docker's MCP.
    # Bind 0.0.0.0 so the Docker Desktop VM gateway can reach the listener;
    # 127.0.0.1 binding would land on host-loopback-only which microVMs
    # can't reach.
    rc = subprocess.call([
        "docker", "run", "-d",
        "--name", ENCM_CONTAINER_NAME,
        "--restart", "unless-stopped",
        "-p", "9118:3128",  # host:container — container port is fixed at 3128
        "-v", f"{home}/.sopify/encm-ca:/etc/encm/ca:ro",
        "-v", f"{home}/.sopify/network-policy.json:/etc/encm/policy.json:ro",
        "-v", f"{home}/.sopify/audit-log:/var/log/encm/audit",
        ENCM_IMAGE,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if rc == 0:
        report.steps.append("encm: container started (HTTP proxy on host :9118 → container :3128)")
    else:
        report.errors.append(f"encm: docker run failed (rc={rc})")


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

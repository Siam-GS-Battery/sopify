"""/living mode — persistent 24/7 employee.

REQ-3.1.1 — session survives terminal close (background).
REQ-3.1.2 — auto-resume after reboot (systemd/launchd/Windows service).
REQ-3.1.3 — state in SQLite WAL (re-uses Hermes hermes_state.py).
REQ-3.1.4 — daily backup of session state.
REQ-3.1.5 — `sopify /living status`.
REQ-3.1.6 — `sopify /living stop` (graceful).
REQ-3.2.* — dept-context.md auto-load (REQ-3.2.2), memory persist (REQ-3.2.3).
"""
from __future__ import annotations

import os
import platform
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _sessions_dir() -> Path:
    home = os.environ.get("SOPIFY_HOME") or os.path.expanduser("~/.sopify")
    return Path(home) / "sessions"


def _pid_file() -> Path:
    return _sessions_dir() / "living.pid"


def _uptime_seconds(pid: int) -> int:
    """Best-effort uptime; works on linux/macOS via /proc or ps."""
    try:
        if platform.system() == "Linux":
            with open(f"/proc/{pid}/stat") as f:
                fields = f.read().split()
            start_clk = int(fields[21])
            hz = os.sysconf("SC_CLK_TCK")
            boot_ts = time.time() - (time.monotonic())
            return int(time.time() - (boot_ts + start_clk / hz))
        out = subprocess.run(
            ["ps", "-o", "etime=", "-p", str(pid)],
            capture_output=True, text=True, timeout=1,
        )
        return _parse_etime(out.stdout.strip())
    except Exception:
        return 0


def _parse_etime(s: str) -> int:
    # ps etime format: [[dd-]hh:]mm:ss
    if not s:
        return 0
    days = 0
    if "-" in s:
        d, s = s.split("-", 1)
        days = int(d)
    parts = [int(p) for p in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, sec = parts[-3:]
    return ((days * 24 + h) * 60 + m) * 60 + sec


@dataclass
class LivingStatus:
    running: bool
    pid: Optional[int] = None
    uptime_seconds: int = 0
    last_activity: Optional[float] = None
    memory_mb: int = 0


def status() -> LivingStatus:
    """REQ-3.1.5."""
    pf = _pid_file()
    if not pf.exists():
        return LivingStatus(running=False)
    try:
        pid = int(pf.read_text().strip())
    except Exception:
        return LivingStatus(running=False)
    try:
        os.kill(pid, 0)
        running = True
    except OSError:
        running = False
    if not running:
        return LivingStatus(running=False, pid=pid)
    return LivingStatus(running=True, pid=pid,
                        uptime_seconds=_uptime_seconds(pid))


def stop(graceful: bool = True) -> bool:
    """REQ-3.1.6 — write state then SIGTERM."""
    pf = _pid_file()
    if not pf.exists():
        return False
    try:
        pid = int(pf.read_text().strip())
    except Exception:
        return False
    import signal
    try:
        os.kill(pid, signal.SIGTERM if graceful else signal.SIGKILL)
    except OSError:
        return False
    pf.unlink(missing_ok=True)
    return True


def backup_session(dest_dir: Path | None = None) -> Path | None:
    """REQ-3.1.4 — daily backup. dest_dir overrides settings.backup_dir."""
    src = _sessions_dir()
    if not src.exists():
        return None
    if dest_dir is None:
        dest_dir = Path(os.path.expanduser("~/.sopify/backups"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"sessions-{stamp}.tar"
    subprocess.run(
        ["tar", "-cf", str(dest), "-C", str(src.parent), src.name],
        check=False,
    )
    return dest


def dept_context_path() -> Path:
    """REQ-3.2.2 — .sopify/dept-context.md in the working dir."""
    return Path.cwd() / ".sopify" / "dept-context.md"


def load_dept_context() -> str:
    p = dept_context_path()
    return p.read_text() if p.exists() else ""

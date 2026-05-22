#!/usr/bin/env python3
"""Daily backup of /living session state (REQ-3.1.4).

Designed to run via cron at 02:00 local time:

  # crontab -e (run as the user who owns ~/.sopify)
  0 2 * * * /usr/local/bin/python3 /opt/sopify/cron/daily-backup.py

Or via systemd timer (see packaging/sopify-backup.service + .timer).

Behaviour:
  1. tar of ~/.sopify/sessions/ → ~/.sopify/backups/sessions-YYYYMMDD-HHMMSS.tar
  2. Prune backups older than RETENTION_DAYS (default 14)
  3. Emit OTel `tool_decision` event (decision=daily_backup, success=bool)

Failures never block; the next day's run will try again.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger("sopify.cron.daily-backup")
logging.basicConfig(
    level=os.environ.get("SOPIFY_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)

RETENTION_DAYS = int(os.environ.get("SOPIFY_BACKUP_RETENTION_DAYS", "14"))


def _sopify_home() -> Path:
    return Path(os.environ.get("SOPIFY_HOME") or os.path.expanduser("~/.sopify"))


def _backup_dir() -> Path:
    return _sopify_home() / "backups"


def _emit(success: bool, detail: str) -> None:
    """Fire-and-forget OTel emit. Best effort only."""
    try:
        # Make plugins importable in case we're run via cron (no PYTHONPATH).
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from plugins.sopify_otel import emit
        emit.emit("tool_decision",
                  decision="daily_backup",
                  tool_name="cron",
                  success=success,
                  args_summary=detail)
    except Exception as exc:
        logger.warning("OTel emit failed: %s", exc)


def make_backup() -> Path | None:
    """tar -cf the sessions dir. Returns the backup path or None on failure."""
    home = _sopify_home()
    src = home / "sessions"
    if not src.exists():
        logger.info("Nothing to back up (sessions dir missing).")
        return None
    dest_dir = _backup_dir()
    dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"sessions-{stamp}.tar"
    rc = subprocess.call(["tar", "-cf", str(dest), "-C", str(src.parent), src.name])
    if rc != 0:
        logger.error("tar exited with %s", rc)
        return None
    logger.info("backup: %s (%d bytes)", dest, dest.stat().st_size)
    return dest


def prune() -> int:
    """Delete backups older than RETENTION_DAYS. Returns count removed."""
    cutoff = time.time() - RETENTION_DAYS * 86400
    dest_dir = _backup_dir()
    if not dest_dir.exists():
        return 0
    removed = 0
    for f in dest_dir.glob("sessions-*.tar"):
        if f.stat().st_mtime < cutoff:
            try:
                f.unlink()
                removed += 1
            except OSError as exc:
                logger.warning("prune failed for %s: %s", f, exc)
    if removed:
        logger.info("pruned %d backups older than %d days", removed, RETENTION_DAYS)
    return removed


def main() -> int:
    try:
        backup = make_backup()
        n_pruned = prune()
        ok = backup is not None
        _emit(success=ok, detail=f"backup={backup} pruned={n_pruned}")
        return 0 if ok else 1
    except Exception as exc:
        logger.exception("daily-backup failed: %s", exc)
        _emit(success=False, detail=f"exception={exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

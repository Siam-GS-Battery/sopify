"""
Retention rotator — delete audit logs older than ``retention_days``.

Designed to be called periodically (every hour by the ENCM container's
background tick) or as a one-off from tests. Names files must follow
``YYYY-MM-DD.jsonl`` — anything else in the dir is left untouched.

Why this lives separately from the writer: the rotator may be invoked from
a different process (e.g. ``sopify doctor`` cleaning up after a crash), so
it shouldn't touch the writer's open file handle.
"""
from __future__ import annotations
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

_FILENAME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.jsonl$")


def purge_old_logs(log_dir: str | Path, retention_days: int) -> list[Path]:
    """
    Delete files older than ``retention_days``. Returns the paths that
    were removed (for logging / tests).

    Files older than the cutoff are removed; files exactly at the cutoff
    boundary are kept. The "current day" file is never deleted even if
    retention_days=0, so a misconfigured value doesn't wipe today's logs.
    """
    
    # Find logs file 
    log_dir = Path(log_dir).expanduser()
    if not log_dir.is_dir():
        return []

    # Get date now - time from logs -> Find diff
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=retention_days)).date()
    today = datetime.now(timezone.utc).date()
    removed: list[Path] = []

    for entry in log_dir.iterdir():

        # Checking File existed
        if not entry.is_file():
            continue

        # Fine the name of the logs file
        m = _FILENAME_RE.match(entry.name)
        if not m:
            continue


        try:
            file_date = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except ValueError:
            continue

        if file_date == today:
            continue  # always preserve current day

        if file_date < cutoff_date:
            try:
                entry.unlink()
                removed.append(entry)
            except OSError:
                # Don't crash the proxy loop if a file is locked / permission denied.
                pass
            
    return removed

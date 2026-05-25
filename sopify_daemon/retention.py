"""Audit log retention — daily roll-up of stale JSONL files into gzip archives.

The audit ingester writes one ``YYYY-MM-DD.jsonl`` file per UTC day under
``~/.sopify/encm/audit/``. Without rotation those files grow unbounded —
on a busy day they can hit hundreds of MB, and a one-time linear scan to
back-fill historical queries becomes intolerably slow.

This module:

  * Once a day (and once at startup), scans ``audit/*.jsonl``.
  * Anything whose date is older than ``audit_retention_days`` (default 90)
    is gzipped into ``audit/archive/YYYY-MM-DD.jsonl.gz`` and the original
    removed. Atomicity is via ``os.rename`` on the ``.gz.tmp`` artefact.
  * Already-archived files stay archived; we never re-compress on re-run.

Why not roll on size: per the plan §8 Q9 we're keeping JSONL files
single-day-per-file as the integrity contract. Size limits trip a
follow-up SQLite indexing task — out of scope here.
"""
from __future__ import annotations

import asyncio
import functools
import gzip
import logging
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from . import paths

log = logging.getLogger(__name__)

# Files we manage are exactly ``YYYY-MM-DD.jsonl``. We refuse to touch
# anything else — protects against typos / user-dropped logs.
_DATE_FILE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.jsonl$")
_DAY_SECONDS = 24 * 3600
_ARCHIVE_SUBDIR = "archive"


def _audit_root() -> Path:
    return paths.audit_dir()


def _archive_root() -> Path:
    return _audit_root() / _ARCHIVE_SUBDIR


def _file_date(path: Path) -> datetime | None:
    m = _DATE_FILE_RE.match(path.name)
    if not m:
        return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc)
    except ValueError:
        return None


def _gzip_compress(source: Path, dest: Path) -> None:
    """Atomic gzip: write to ``dest.tmp`` then rename. Same-filesystem rename
    is POSIX-atomic — no partial archive on power loss."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with source.open("rb") as src_f, gzip.open(tmp, "wb", compresslevel=6) as dst_f:
        shutil.copyfileobj(src_f, dst_f, length=64 * 1024)
    os.replace(tmp, dest)


def _list_candidate_files(now: datetime, retention_days: int) -> Iterable[Path]:
    """Yield JSONL files whose date is at least ``retention_days`` in the past."""
    cutoff = now - timedelta(days=retention_days)
    root = _audit_root()
    if not root.is_dir():
        return []
    out: list[Path] = []
    for entry in root.iterdir():
        if not entry.is_file():
            continue
        file_date = _file_date(entry)
        if file_date is None:
            continue
        if file_date < cutoff:
            out.append(entry)
    return out


def rotate_once(*, retention_days: int, now: datetime | None = None) -> dict[str, int]:
    """Single sweep: archive everything older than the retention window.

    Returns a counter dict for tests + status reporting:
    ``{"archived": N, "skipped": M, "errors": K}``.
    """
    now = now or datetime.now(timezone.utc)
    archived = 0
    skipped = 0
    errors = 0
    archive_dir = _archive_root()

    for jsonl in _list_candidate_files(now, retention_days):
        gz_target = archive_dir / f"{jsonl.stem}.jsonl.gz"
        if gz_target.exists():
            # Already archived — leave the .jsonl in place untouched so
            # we don't double-delete. This branch hits if an earlier run
            # archived but failed to unlink the source; the next run
            # picks the unlink up.
            try:
                jsonl.unlink()
                skipped += 1
            except OSError as exc:
                log.warning("retention: failed to remove %s after existing archive: %s", jsonl, exc)
                errors += 1
            continue
        try:
            _gzip_compress(jsonl, gz_target)
            jsonl.unlink()
            archived += 1
            log.info(
                "retention: archived %s -> %s",
                jsonl.name,
                gz_target.relative_to(_audit_root()),
            )
        except OSError as exc:
            log.warning("retention: failed to archive %s: %s", jsonl, exc)
            errors += 1

    return {"archived": archived, "skipped": skipped, "errors": errors}


class AuditRetentionTask:
    """Background asyncio task: sweeps once at startup, then daily.

    Failures (file IO, permission, whatever) are logged but never propagate —
    retention is housekeeping, not on the critical path. ``stop()`` cancels
    the next sleep so daemon shutdown is prompt.
    """

    def __init__(self, *, retention_days: int) -> None:
        self.retention_days = retention_days
        self._stop = asyncio.Event()
        self.last_run_at: datetime | None = None
        self.last_result: dict[str, int] | None = None
        self.last_error: str | None = None

    def stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        # First sweep immediately (catches the case where the daemon was
        # offline for >1 day and stale files have piled up). Then sleep a
        # full day between subsequent sweeps.
        try:
            await self._tick()
        except Exception as exc:  # noqa: BLE001
            log.exception("retention: initial sweep failed")
            self.last_error = str(exc)

        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=_DAY_SECONDS)
                # _stop was set → exit cleanly
                return
            except asyncio.TimeoutError:
                pass
            try:
                await self._tick()
            except Exception as exc:  # noqa: BLE001
                log.exception("retention: sweep failed")
                self.last_error = str(exc)

    async def _tick(self) -> None:
        # ``run_in_executor`` only takes positional args, so bind kwargs via
        # ``functools.partial`` — keeps ``rotate_once`` keyword-only so unit
        # tests can call it directly without juggling positional ordering.
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            functools.partial(rotate_once, retention_days=self.retention_days),
        )
        self.last_run_at = datetime.now(timezone.utc)
        self.last_result = result
        self.last_error = None

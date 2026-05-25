"""JSONL audit-log writer.

Writes one event per line to ``{log_dir}/YYYY-MM-DD.jsonl``. The file is
opened append-only and re-opened on UTC date rollover so each day's events
land in their own file (required by the retention rotator).

Threading model:
  - Multiple proxy workers may call ``write()`` concurrently. We guard
    appends with a single lock — JSONL appends are small (<2KB typically)
    and fsync-free, so contention is minimal.

Payload redaction:
  - HTTP req/resp bodies and headers are not touched here — the caller (the
    HTTP addon) is responsible for redacting `Authorization` / `Cookie` /
    `X-API-Key` before passing the body into ``AuditEvent``.
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional


@dataclass(slots=True)
class AuditEvent:
    """One row in the JSONL audit log.

    Required fields for every event:
      - ``ts`` (auto-filled if missing)
      - ``decision``
      - ``protocol``
      - ``src``
      - ``dst``

    Everything else is optional and protocol-specific. Extra fields go into
    ``extras`` and are flattened on serialise.
    """

    decision: Literal["allow", "deny", "rate_limited", "policy_blocked"]
    protocol: str
    src: str
    dst: str
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"))
    rule_id: Optional[str] = None
    reason: Optional[str] = None

    # HTTP-specific
    method: Optional[str] = None
    path: Optional[str] = None
    status: Optional[int] = None
    duration_ms: Optional[int] = None
    bytes_sent: Optional[int] = None
    bytes_recv: Optional[int] = None

    # TCP / SQL
    wire_protocol: Optional[str] = None
    query_sample: Optional[str] = None

    # MQTT
    mqtt_action: Optional[Literal["connect", "sub", "pub", "unsub"]] = None
    mqtt_topic: Optional[str] = None

    # Payload viewer (opt-in per rule)
    req_body_b64: Optional[str] = None
    resp_body_b64: Optional[str] = None

    extras: dict[str, Any] = field(default_factory=dict)

    def to_jsonl(self) -> str:
        """One compact JSON line — no extra whitespace, ensure_ascii=False so
        non-ASCII paths/queries stay readable in `tail -f`."""
        d = {k: v for k, v in asdict(self).items() if v is not None and k != "extras"}
        if self.extras:
            d.update(self.extras)
        return json.dumps(d, separators=(",", ":"), ensure_ascii=False) + "\n"


class AuditWriter:
    """Append-only JSONL writer with daily rotation by UTC date."""

    def __init__(self, log_dir: str | Path) -> None:
        self._log_dir = Path(log_dir).expanduser()
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._current_date: str | None = None
        self._fh = None

    def _today_path(self) -> Path:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._log_dir / f"{today}.jsonl"

    def _ensure_fh(self) -> None:
        """Open or re-open the file when the UTC date rolls over. Called inside
        the lock — don't call from outside."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._current_date != today:
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:
                    pass
            path = self._log_dir / f"{today}.jsonl"
            self._fh = open(path, "a", encoding="utf-8", buffering=1)  # line-buffered
            self._current_date = today

    def write(self, event: AuditEvent) -> None:
        """Append one event. Safe to call from any thread."""
        line = event.to_jsonl()
        with self._lock:
            self._ensure_fh()
            assert self._fh is not None  # set by _ensure_fh
            self._fh.write(line)

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None
                self._current_date = None

    def __enter__(self) -> "AuditWriter":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

"""
Policy file store with hot-reload via mtime polling.

The proxy reads the policy via :class:`PolicyStore` and gets a callback
every time the file changes. Polling (vs inotify/fsevents) keeps it
cross-platform and reliable when the file lives on a bind-mount.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from ..migration import migrate_file
from ..schema import NetworkPolicy

log = logging.getLogger(__name__)

# Polling cadence — 1s is fast enough for human edits via the dashboard
# UI; CPU cost is negligible (one stat call).
DEFAULT_POLL_INTERVAL = 1.0


class PolicyStore:
    """
    Auto-reloading wrapper around the on-disk policy file.

    Usage:
        store = PolicyStore("~/.sopify/network-policy.json")
        store.on_change(lambda p: matcher.update_policy(p))
        store.start()  # background polling thread
        ...
        store.stop()
    """

    def __init__(self, path: str | Path, poll_interval: float = DEFAULT_POLL_INTERVAL) -> None:
        self._path = Path(path).expanduser()
        self._poll_interval = poll_interval
        self._policy: NetworkPolicy = migrate_file(self._path)
        self._mtime = self._stat_mtime()
        self._listeners: list[Callable[[NetworkPolicy], None]] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def policy(self) -> NetworkPolicy:
        with self._lock:
            return self._policy

    def on_change(self, callback: Callable[[NetworkPolicy], None]) -> None:
        """Register a listener. Called once immediately with the current
        policy, then on every reload."""
        self._listeners.append(callback)
        callback(self.policy)



    def reload(self) -> NetworkPolicy:
        """Force a reload regardless of mtime. Useful from tests / signal
        handlers."""
        policy = migrate_file(self._path)
        with self._lock:
            self._policy = policy
            self._mtime = self._stat_mtime()
        for cb in self._listeners:
            try:
                cb(policy)
            except Exception:
                log.exception("policy listener raised")
        return policy



    def _stat_mtime(self) -> float:
        try:
            return self._path.stat().st_mtime
        except FileNotFoundError:
            return 0.0



    def _poll_loop(self) -> None:
        while not self._stop.wait(self._poll_interval):
            current = self._stat_mtime()
            if current != self._mtime and current > 0:
                # File changed — try to reload. Validation errors land in
                # the log but don't crash the proxy.
                try:
                    self.reload()
                except Exception:
                    log.exception("policy reload failed; keeping previous version")
                    # Update mtime anyway so we don't retry every second on
                    # the same broken file.
                    self._mtime = current



    def start(self) -> None:
        """Spawn the background polling thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, name="encm-policy-watcher", daemon=True
        )
        self._thread.start()



    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None



    def __enter__(self) -> "PolicyStore":
        self.start()
        return self



    def __exit__(self, *_exc: object) -> None:
        self.stop()

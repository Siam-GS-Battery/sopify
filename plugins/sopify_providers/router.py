"""ProviderRouter — handles cascade + 1h blacklist on failure.

REQ traceability:
  REQ-2.1.1 — class exists, owns priority cascade
  REQ-2.1.2 — default: Anthropic → OpenRouter → any Hermes provider
  REQ-2.1.3 — 401/403 → blacklist 1h → next provider
  REQ-2.1.4 — quota/rate-limit → blacklist 1h → failover
  REQ-2.1.6 — chain override via settings.json `provider_chain`
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

BLACKLIST_TTL_SECONDS = 60 * 60  # REQ-2.1.3/4 — 1 hour

DEFAULT_CHAIN: List[str] = ["anthropic", "openrouter"]  # REQ-2.1.2


@dataclass
class ProviderRouter:
    """Decides which provider to use given a chain + transient blacklist."""

    chain: List[str] = field(default_factory=lambda: list(DEFAULT_CHAIN))
    # provider_name -> unix-ts when it becomes usable again
    blacklist: Dict[str, float] = field(default_factory=dict)
    _now = staticmethod(time.time)

    @classmethod
    def from_settings(cls, settings_path: Optional[str] = None) -> "ProviderRouter":
        path = settings_path or os.path.join(
            os.environ.get("SOPIFY_HOME") or os.path.expanduser("~/.sopify"),
            "settings.json",
        )
        if os.path.exists(path):
            try:
                data = json.loads(open(path).read())
                chain = data.get("provider_chain") or DEFAULT_CHAIN
                # Always append fallthrough Hermes-default at the tail so we can
                # honor REQ-2.1.2's "any Hermes provider" trailing clause.
                if "hermes_default" not in chain:
                    chain = list(chain) + ["hermes_default"]
                return cls(chain=list(chain))
            except Exception:
                pass
        return cls(chain=list(DEFAULT_CHAIN) + ["hermes_default"])

    def pick(self) -> Optional[str]:
        """Return the first non-blacklisted provider in the chain, or None."""
        now = self._now()
        for name in self.chain:
            until = self.blacklist.get(name, 0)
            if until and until <= now:
                self.blacklist.pop(name, None)  # expired
                until = 0
            if not until:
                return name
        return None

    def record_failure(self, name: str, *, status: Optional[int] = None,
                       reason: str = "") -> None:
        """REQ-2.1.3/4 — blacklist on auth or quota failure."""
        blacklistable = status in (401, 403, 429) or "quota" in reason.lower() or \
            "rate" in reason.lower()
        if blacklistable:
            self.blacklist[name] = self._now() + BLACKLIST_TTL_SECONDS

    def status_summary(self) -> str:
        """REQ-2.1.5 — TUI footer string."""
        active = self.pick() or "(none)"
        blocked = ", ".join(
            f"{k}(retry in {int(v - self._now())}s)"
            for k, v in self.blacklist.items() if v > self._now()
        )
        if blocked:
            return f"active={active} blacklisted=[{blocked}]"
        return f"active={active}"

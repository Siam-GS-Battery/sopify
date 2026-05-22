"""Read/write ~/.hermes/.env so changes propagate into the microVM.

The microVM mounts ~/.hermes/ as :ro and Hermes' env_loader reads .env on
boot — so writing to this file is the canonical way to make a credential
visible to slash_workers inside the sandbox.

This is a thin wrapper that:
  * preserves comments + ordering of existing entries
  * rewrites an existing assignment in-place
  * appends new entries at the end
  * enforces file mode 0600

REQ-2.2.1 / REQ-11.1 — credentials live at 0600.
REQ-11.2          — never log values; only names + lengths.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

_ASSIGN_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*=(.*)$")


def env_path() -> Path:
    return Path.home() / ".hermes" / ".env"


def read_keys() -> dict[str, str]:
    """Return {VAR: value} from ~/.hermes/.env (raw, no .env expansion)."""
    p = env_path()
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        m = _ASSIGN_RE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def set_keys(updates: dict[str, str], *, strip: Iterable[str] = ()) -> bool:
    """Write or rewrite entries in ~/.hermes/.env.

    Args:
      updates: VAR -> value pairs to write. Empty value deletes the entry.
      strip:   VAR names to remove entirely (regardless of value).

    Returns True if the file was modified.
    """
    p = env_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    strip_set = set(strip)

    lines = text.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = _ASSIGN_RE.match(line)
        if not m:
            out.append(line)
            continue
        var = m.group(1)
        if var in strip_set:
            continue
        if var in updates:
            value = updates[var]
            if value == "":
                # explicit empty == delete
                continue
            out.append(f"{var}={value}")
            seen.add(var)
        else:
            out.append(line)
    for var, value in updates.items():
        if var in seen or value == "":
            continue
        out.append(f"{var}={value}")

    new_text = "\n".join(out)
    if new_text and not new_text.endswith("\n"):
        new_text += "\n"
    if new_text == text:
        return False

    p.write_text(new_text, encoding="utf-8")
    try:
        p.chmod(0o600)
    except Exception:
        pass
    logger.info("sopify-providers: wrote %d keys to %s",
                len([v for v in updates.values() if v]), p)
    return True

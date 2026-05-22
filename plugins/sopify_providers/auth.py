"""Auth file management.

REQ-2.2.1 — ~/.sopify/auth.json at file mode 0600.
REQ-2.2.2 — ANTHROPIC_API_KEY env var overrides auth.json.
REQ-2.2.3 — `sopify login` (interactive).
REQ-2.2.4 — `sopify logout` (zero-fill before unlink).
REQ-11.1  — file permission 0600 enforced on write.
REQ-11.2  — never log the key (redaction lives in sopify-otel).
"""
from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
from typing import Dict, Optional


def _auth_path() -> Path:
    home = os.environ.get("SOPIFY_HOME") or os.path.expanduser("~/.sopify")
    return Path(home) / "auth.json"


def load() -> Dict[str, str]:
    """Return {provider: api_key}. Env var ANTHROPIC_API_KEY overrides."""
    p = _auth_path()
    data: Dict[str, str] = {}
    if p.exists():
        try:
            data = json.loads(p.read_text())
        except Exception:
            data = {}
    if os.environ.get("ANTHROPIC_API_KEY"):  # REQ-2.2.2
        data["anthropic"] = os.environ["ANTHROPIC_API_KEY"]
    return data


def get(provider: str) -> Optional[str]:
    return load().get(provider)


def _write_atomic(data: Dict[str, str]) -> None:
    p = _auth_path()
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Docker bind-mounting a non-existent file path creates a directory at
    # that path. Detect + repair so `sopify login` works on machines that
    # ran the sandbox once before auth was set up.
    if p.is_dir():
        import shutil
        shutil.rmtree(p)
    tmp = p.with_suffix(".json.tmp")
    if tmp.is_dir():
        import shutil
        shutil.rmtree(tmp)
    tmp.write_text(json.dumps(data, indent=2))
    tmp.chmod(0o600)  # REQ-2.2.1 / REQ-11.1
    tmp.replace(p)


def set_key(provider: str, key: str) -> None:
    data = load()
    data[provider] = key
    _write_atomic(data)


def login_interactive() -> None:
    """REQ-2.2.3 — interactive setup."""
    print()
    print("┌────────────────────────────────────────────────────────────┐")
    print("│  sopify login — store an API key in ~/.sopify/auth.json    │")
    print("│                                                            │")
    print("│  Common providers (press Enter for default 'anthropic'):   │")
    print("│    anthropic   — get key at console.anthropic.com/settings │")
    print("│    openrouter  — get key at openrouter.ai/keys             │")
    print("│    novita      — get key at novita.ai/settings/key         │")
    print("│    openai      — get key at platform.openai.com/api-keys   │")
    print("│                                                            │")
    print("│  Step 1 — pick a provider (just press Enter for anthropic) │")
    print("│  Step 2 — paste the API key. The terminal HIDES typing for │")
    print("│           security, so you won't see characters appear.    │")
    print("│           Just paste + Enter.                              │")
    print("└────────────────────────────────────────────────────────────┘")
    print()

    provider = input("[1/2] Provider [anthropic]: ").strip() or "anthropic"

    print(f"\n[2/2] Paste {provider} API key and press Enter")
    print("      (input is hidden — no characters will appear as you type)")
    key = getpass.getpass(f"      {provider} key: ").strip()
    if not key:
        print("\n✗ no key entered — aborting. Run `sopify login` again to retry.")
        return
    set_key(provider, key)
    print(f"\n✓ Saved {provider} key to {_auth_path()} (mode 0600)")
    print("   Run `sopify doctor` to verify, then `sopify dashboard` to use it.")


def logout(provider: Optional[str] = None) -> None:
    """REQ-2.2.4 — zero-fill before delete."""
    p = _auth_path()
    if not p.exists():
        return
    data = load()
    if provider:
        data.pop(provider, None)
        # Zero-fill the file first then overwrite with new content.
        try:
            with open(p, "r+b") as f:
                size = p.stat().st_size
                f.write(b"\x00" * size)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            pass
        if data:
            _write_atomic(data)
        else:
            p.unlink()
    else:
        try:
            with open(p, "r+b") as f:
                size = p.stat().st_size
                f.write(b"\x00" * size)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            pass
        p.unlink()

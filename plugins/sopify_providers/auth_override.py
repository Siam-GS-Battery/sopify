"""Force Hermes to use the API key from `~/.sopify/auth.json`.

Hermes' `resolve_anthropic_token` has this priority (anthropic_adapter.py):
  1. ANTHROPIC_TOKEN env
  2. CLAUDE_CODE_OAUTH_TOKEN env
  3. ~/.claude/.credentials.json  (Claude Code Pro subscription OAuth)
  4. ANTHROPIC_API_KEY env

If the user has Claude Code installed + logged in, step 3 wins and the
API key the user just `sopify login`'d with (step 4 / auth.json) never
gets used. The symptom is Anthropic returning "out of extra usage"
because requests bill against the Pro subscription quota.

For Sopify we want explicit `sopify login` to ALWAYS win. We achieve
this by:
  - Reading the key from `~/.sopify/auth.json` at startup
  - Exporting it as `ANTHROPIC_API_KEY` so step 4 is populated
  - Monkey-patching `read_claude_code_credentials` to return None,
    so steps 1-3 short-circuit and Hermes falls through to step 4

REQ traceability:
  REQ-0.3 — we never modify hermes_cli/agent/* source files. The
            monkey-patch swaps a function object at runtime, which is
            allowed.
  REQ-2.2.1 — the key still lives at ~/.sopify/auth.json mode 0600.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from . import auth

logger = logging.getLogger(__name__)


def apply() -> Optional[str]:
    """Promote ~/.sopify/auth.json key to ANTHROPIC_API_KEY and mask
    Claude Code OAuth credentials. Returns the resolved key or None.
    """
    creds = auth.load()
    key = creds.get("anthropic")
    if not key:
        return None

    # CRITICAL: set ANTHROPIC_TOKEN to the API key. resolve_anthropic_token
    # checks ANTHROPIC_TOKEN FIRST (step 1 of 4). Its OAuth-preference helper
    # `_prefer_refreshable_claude_code_token` only kicks in when the env
    # token is OAuth-shaped — an API key (sk-ant-api*) short-circuits the
    # helper, so step 1 returns our key directly.
    os.environ["ANTHROPIC_TOKEN"] = key
    # Belt-and-braces for any caller that reads ANTHROPIC_API_KEY directly.
    os.environ["ANTHROPIC_API_KEY"] = key

    # Drop the OAuth-only token (so step 2 doesn't pick up anything stale).
    os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)

    # CRITICAL #2: persist to ~/.hermes/.env. Hermes' env_loader.py:168 does
    # `load_dotenv(user_env, override=True)` at startup — this clobbers
    # whatever we set in os.environ with the .env file's value. If the user
    # is running inside a Claude Code session, ANTHROPIC_TOKEN in .env may
    # be a stale OAuth setup-token (sk-ant-oat01-...) from a previous flow,
    # and Hermes would override our API key right back to that OAuth token.
    # PTY subprocesses (TUI chat) get the .env-promoted value because the
    # subprocess re-runs the same env_loader at startup.
    _sync_hermes_env_file(key)

    # Mask Claude Code credentials at the function level. This makes
    # _resolve_claude_code_token_from_credentials() return None for any
    # caller, including the Anthropic adapter.
    try:
        from agent import anthropic_adapter  # type: ignore
        _original = getattr(anthropic_adapter, "read_claude_code_credentials", None)
        if _original is not None and not getattr(_original, "_sopify_masked", False):
            def _masked() -> None:
                # Returning None forces Hermes to fall through to step 4
                # (ANTHROPIC_API_KEY) which we just set.
                return None
            _masked._sopify_masked = True  # type: ignore[attr-defined]
            anthropic_adapter.read_claude_code_credentials = _masked  # type: ignore[assignment]
            logger.info("sopify-providers: masked Claude Code creds; "
                        "using auth.json key for Anthropic")
    except Exception as exc:
        logger.warning("sopify-providers: failed to mask Claude Code creds: %s", exc)

    return key


def _sync_hermes_env_file(api_key: str) -> None:
    """Rewrite ~/.hermes/.env so the API key wins after Hermes' env_loader.

    Sets ANTHROPIC_TOKEN and ANTHROPIC_API_KEY both to the API key.
    Removes CLAUDE_CODE_OAUTH_TOKEN if present (it would lose to step 4
    via `_prefer_refreshable_claude_code_token`, but we strip it anyway
    to be belt-and-braces).
    """
    import re
    from pathlib import Path

    env_path = Path.home() / ".hermes" / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""

    keys_to_set = {
        "ANTHROPIC_TOKEN": api_key,
        "ANTHROPIC_API_KEY": api_key,
    }
    keys_to_strip = {"CLAUDE_CODE_OAUTH_TOKEN"}

    lines = text.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=", line)
        if not m:
            out.append(line)
            continue
        var = m.group(1)
        if var in keys_to_set:
            out.append(f"{var}={keys_to_set[var]}")
            seen.add(var)
        elif var in keys_to_strip:
            # Drop the line entirely.
            continue
        else:
            out.append(line)
    for var, value in keys_to_set.items():
        if var not in seen:
            out.append(f"{var}={value}")

    new_text = "\n".join(out)
    if not new_text.endswith("\n"):
        new_text += "\n"
    if new_text != text:
        env_path.write_text(new_text, encoding="utf-8")
        try:
            env_path.chmod(0o600)
        except Exception:
            pass
        logger.info("sopify-providers: synced ANTHROPIC_* to %s", env_path)

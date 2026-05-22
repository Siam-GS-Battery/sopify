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

    # Always set ANTHROPIC_API_KEY so step 4 of Hermes resolution succeeds.
    os.environ["ANTHROPIC_API_KEY"] = key

    # Don't let stale env vars trick Hermes into OAuth mode.
    for var in ("ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        os.environ.pop(var, None)

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

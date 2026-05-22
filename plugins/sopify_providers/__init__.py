"""sopify-providers — provider cascade + auth.

Hooks:
  pre_api_request   — choose provider; rewrite ctx.provider to ROUTER.pick()
  post_api_request  — release on success
  api_error         — record_failure(status, reason)
"""
from __future__ import annotations

import logging
from typing import Any

from . import auth, auth_override, router

logger = logging.getLogger(__name__)

ROUTER: router.ProviderRouter = router.ProviderRouter.from_settings()

# Apply at import time — before Hermes' Anthropic adapter is touched.
# When user does `sopify login`, that key MUST win over any Claude Code
# OAuth credentials that happen to be on the host (REQ-2.2.2 spirit).
_AUTH_OVERRIDE_KEY = auth_override.apply()


def reload_router() -> None:
    """REQ-9.1.3 — managed-settings change pickup without restart."""
    global ROUTER
    ROUTER = router.ProviderRouter.from_settings()


def _on_pre_api_request(*, provider: str = "", **kw: Any):
    if provider in ROUTER.blacklist:
        chosen = ROUTER.pick()
        if chosen and chosen != provider:
            logger.info("sopify-providers: rerouting %s → %s", provider, chosen)
            return {"override_provider": chosen}
    return None


def _on_post_api_request(*, provider: str = "", status: int = 200, **_: Any):
    if status >= 400:
        ROUTER.record_failure(provider, status=status)


def _on_api_error(*, provider: str = "", status: int = 0, message: str = "", **_: Any):
    ROUTER.record_failure(provider, status=status, reason=message)


def register(ctx) -> None:
    ctx.register_hook("pre_api_request", _on_pre_api_request)
    ctx.register_hook("post_api_request", _on_post_api_request)
    ctx.register_hook("api_error", _on_api_error)


__all__ = ["auth", "router", "ROUTER", "reload_router", "register"]

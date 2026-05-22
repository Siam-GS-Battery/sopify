"""sopify-management — managed settings + onboard + quota + admin.

Subscribes plugins to settings changes so REQ-9.1.3 ("no restart") works.
"""
from __future__ import annotations

import logging
from typing import Any

from . import admin, onboard, quota, settings

logger = logging.getLogger(__name__)


def _wire_subscribers() -> None:
    """Tell every sopify-* plugin that cares about settings to reload."""
    try:
        from importlib import import_module
        providers = import_module("plugins.sopify_providers")
        settings.subscribe(lambda _: providers.reload_router())
    except Exception:
        pass
    try:
        from importlib import import_module
        otel = import_module("plugins.sopify_otel.emit")
        settings.subscribe(lambda _: otel.reload_settings())
    except Exception:
        pass


def _on_post_api_request(*, provider: str = "", input_tokens: int = 0,
                        output_tokens: int = 0, cost_usd: float = 0.0,
                        **_: Any):
    quota.record(provider,
                 input_tokens=input_tokens,
                 output_tokens=output_tokens,
                 cost_usd=cost_usd)


def register(ctx) -> None:
    _wire_subscribers()
    settings.poll_for_changes()
    ctx.register_hook("post_api_request", _on_post_api_request)

    def _on_startup(**_: Any) -> None:
        logger.info("sopify-management loaded; settings polling active")
    ctx.register_hook("on_startup", _on_startup)


__all__ = ["admin", "onboard", "quota", "settings", "register"]

"""sopify-core — foundation plugin.

Loaded first. Exposes:
  * paths       — canonical ~/.sopify/* file locations
  * version     — sopify + runtime version string
  * doctor      — health check (auth / sandbox / OTel)
  * install     — one-shot bootstrap

Other sopify-* plugins import these helpers; they should not duplicate
path constants. See plugin.yaml for REQ traceability.
"""
from __future__ import annotations

import logging

from . import paths, version  # re-export for `from sopify_core import paths`

logger = logging.getLogger(__name__)

__all__ = ["paths", "version", "register"]


def register(ctx) -> None:
    """Plugin entry point called by Sopify plugin manager."""
    # sopify-core has no runtime hooks; it's a library namespace for the rest
    # of the sopify-* family. We still register on_startup so its presence is
    # recorded by the plugin status reporter.
    def _on_startup(**_: object) -> None:
        logger.info("sopify-core loaded (version=%s)", version.sopify_version())

    ctx.register_hook("on_startup", _on_startup)

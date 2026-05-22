"""Write Hermes config so all sopify_* plugins are enabled.

Hermes plugins are opt-in via `plugins.enabled` in `~/.hermes/config.yaml`.
Without this entry, `register(ctx)` is never called, which means the
sopify hooks (guardrails / OTel / mode / skill injection) never fire —
even though the modules are importable.

This module ensures sopify_* plugins are in that list so guardrails
ACTUALLY block dangerous commands, OTel ACTUALLY emits, etc.

REQ traceability:
  REQ-0.7 — `sopify install` does everything one-shot. Activation is
            now part of install.run().
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Set

logger = logging.getLogger(__name__)


SOPIFY_PLUGIN_KEYS: List[str] = [
    "sopify_core",
    "sopify_sandbox",
    "sopify_providers",
    "sopify_guardrails",
    "sopify_otel",
    "sopify_skills",
    "sopify_modes",
    "sopify_management",
    "sopify_tui",
]


def ensure_enabled() -> Set[str]:
    """Add every sopify_* plugin to Hermes' `plugins.enabled` allow-list.

    Returns the set of plugin keys that ended up enabled (whether by us
    or already present). Idempotent — safe to call from every `sopify
    install` run.
    """
    try:
        from hermes_cli.config import load_config, save_config
    except ImportError:
        logger.warning("hermes_cli.config not importable — activation skipped.")
        return set()

    config = load_config() or {}
    plugins_cfg = config.get("plugins")
    if not isinstance(plugins_cfg, dict):
        plugins_cfg = {}
    enabled = plugins_cfg.get("enabled")
    if not isinstance(enabled, list):
        enabled = []

    before = set(enabled)
    for key in SOPIFY_PLUGIN_KEYS:
        if key not in enabled:
            enabled.append(key)
    after = set(enabled)

    if after == before:
        return after  # nothing to do

    plugins_cfg["enabled"] = enabled
    config["plugins"] = plugins_cfg
    try:
        save_config(config)
    except Exception as exc:
        logger.warning("save_config failed: %s", exc)
        return before
    return after


def disable_all() -> None:
    """For uninstall: drop sopify_* keys from `plugins.enabled`."""
    try:
        from hermes_cli.config import load_config, save_config
    except ImportError:
        return
    config = load_config() or {}
    plugins_cfg = config.get("plugins") or {}
    enabled = plugins_cfg.get("enabled") or []
    kept = [k for k in enabled if not k.startswith("sopify_")]
    plugins_cfg["enabled"] = kept
    config["plugins"] = plugins_cfg
    save_config(config)

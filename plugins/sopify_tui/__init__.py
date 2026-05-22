"""sopify-tui — wire UI callbacks to other sopify-* plugins.

This plugin owns the *only* place that prints to the user. Other plugins are
UI-agnostic; they expose `set_*_callback` hooks that this plugin fills in.
"""
from __future__ import annotations

import logging
from typing import Any

from . import dialogs, footer

logger = logging.getLogger(__name__)


HELP_TEXT = """\
sopify — quick reference

Modes:
  /vibe            guided app builder
  /living          24/7 AI employee
  /code-with-you   pair programming

Useful:
  /status          current mode, provider, quota, sandbox
  /help            this message
  /tree            session branch tree (vibe mode)
  /compress        compact context

Keyboard:
  Ctrl-C           interrupt
  Ctrl-D           end session
"""


def _wire_callbacks() -> None:
    """Inject this plugin's dialogs into every other sopify-* plugin."""
    try:
        from importlib import import_module
        sandbox = import_module("plugins.sopify_sandbox")
        sandbox.set_dialog_callback(_network_dialog)
    except Exception:
        pass

    try:
        from importlib import import_module
        guards = import_module("plugins.sopify_guardrails")
        guards.set_confirm_callback(dialogs.confirm_destructive)
    except Exception:
        pass

    try:
        from importlib import import_module
        cwy = import_module("plugins.sopify_modes.code_with_you")
        cwy.set_confirm_callback(dialogs.confirm_step)
    except Exception:
        pass

    try:
        from importlib import import_module
        q = import_module("plugins.sopify_management.quota")
        q.set_warning_callback(_quota_warning)
    except Exception:
        pass


def _network_dialog(host: str) -> str:
    return dialogs.ask_network_permission(host)


def _quota_warning(provider: str, used: int, budget: int) -> None:
    pct = int(used * 100 / budget) if budget else 0
    print(f"\n⚠  {provider}: {used:,}/{budget:,} tokens ({pct}%) — daily budget nearly hit")


def _on_slash_command(*, command: str = "", **_: Any):
    cmd = command.lstrip("/")
    if cmd == "status":
        return {"render": footer.render_status()}
    if cmd == "help":
        return {"render": HELP_TEXT}
    return None


def _on_render_footer(**_: Any):
    return {"render": footer.render()}


def register(ctx) -> None:
    _wire_callbacks()
    ctx.register_hook("on_slash_command", _on_slash_command)
    ctx.register_hook("on_render_footer", _on_render_footer)

    def _on_startup(**_: Any) -> None:
        logger.info("sopify-tui loaded; dialogs wired")
    ctx.register_hook("on_startup", _on_startup)


__all__ = ["dialogs", "footer", "register"]

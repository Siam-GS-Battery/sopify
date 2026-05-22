"""sopify-skills — discover + inject sopify_skills bundles per mode."""
from __future__ import annotations

import logging
from typing import Any

from . import loader

logger = logging.getLogger(__name__)


def _on_mode_change(*, mode: str = "", **_: Any):
    """Sopify calls this when /vibe, /living, /code-with-you is entered."""
    prompt = loader.render_system_prompt(mode)
    if not prompt:
        return None
    return {"inject_system_prompt": prompt}


def _on_skill_index(**_: Any):
    """Optional: contribute Sopify skills into the global skill index."""
    return list(loader.all_skills().values())


def register(ctx) -> None:
    # Hermes' own SKILL_DIRS will pick up sopify_skills/ once we add the path;
    # in the meantime we expose it via this hook so sopify-modes can call it.
    ctx.register_hook("on_mode_change", _on_mode_change)
    ctx.register_hook("on_skill_index", _on_skill_index)


__all__ = ["loader", "register"]

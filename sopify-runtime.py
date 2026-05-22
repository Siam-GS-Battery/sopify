"""In-sandbox runtime entry. Called by docker/sopify-sandbox/entrypoint.sh.

Loads every `plugins/sopify-*` plugin then hands off to the Hermes CLI.
The host-side `sopify` shim never runs this; the launcher spawns the
container which runs this.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("sopify.runtime")
logging.basicConfig(level=os.environ.get("SOPIFY_LOG_LEVEL", "INFO"))


def _load_sopify_plugins() -> None:
    """Import every plugins/sopify-* package so their `register` runs.

    Hermes' own plugin manager will then call `register(ctx)` on each.
    We import here (before handing off to Hermes) so that even sopify-*
    modules that *don't* register with Hermes (libraries like sopify-core)
    are still resolvable.
    """
    repo_root = Path(__file__).resolve().parent
    plugin_dir = repo_root / "plugins"
    sys.path.insert(0, str(repo_root))
    for child in sorted(plugin_dir.iterdir()):
        if not child.is_dir() or not child.name.startswith("sopify_"):
            continue
        try:
            mod = importlib.import_module(f"plugins.{child.name}")
        except Exception as exc:
            # REQ-7.2.4 vibe — never crash the whole runtime over one plugin.
            logger.warning("sopify plugin %s failed to import: %s", child.name, exc)
            continue
        logger.info("loaded %s", mod.__name__)


def main() -> int:
    _load_sopify_plugins()
    # Hand off to Hermes' main entrypoint with the remaining argv.
    try:
        from hermes_cli import main as hermes_main
    except ImportError as exc:
        print(f"sopify-runtime: cannot import Hermes ({exc})", file=sys.stderr)
        return 2
    return hermes_main.main(sys.argv[1:])  # type: ignore[attr-defined]


if __name__ == "__main__":
    sys.exit(main())

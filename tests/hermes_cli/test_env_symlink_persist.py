"""save_env_value / remove_env_value must write THROUGH a symlinked .env.

Regression for: env set on the dashboard Keys page disappearing on refresh —
the sandbox links ~/.hermes/.env to the host file, and an atomic replace onto
the symlink path replaced it with a sandbox-local file (lost on re-link).

Runnable under pytest OR directly:
    python tests/hermes_cli/test_env_symlink_persist.py
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _reload_config(hermes_home: Path):
    os.environ["HERMES_HOME"] = str(hermes_home)
    import hermes_constants
    importlib.reload(hermes_constants)
    import hermes_cli.config as C
    importlib.reload(C)
    return C


def test_save_and_remove_write_through_symlink():
    with tempfile.TemporaryDirectory() as host, tempfile.TemporaryDirectory() as sbx:
        host_env = Path(host) / ".env"
        host_env.write_text("EXISTING=1\n")
        sbx_env = Path(sbx) / ".env"
        sbx_env.symlink_to(host_env)  # mimic the sandbox link to the host file

        C = _reload_config(Path(sbx))
        C.save_env_value("FOO", "bar")

        # the symlink must survive (not be replaced by a sandbox-local file)
        assert sbx_env.is_symlink(), "symlink was clobbered by the write"
        # the value must land in the HOST file (durable), preserving existing keys
        host_text = host_env.read_text()
        assert "FOO=bar" in host_text and "EXISTING=1" in host_text

        # remove must also go through the symlink to the host file
        C.remove_env_value("FOO")
        assert sbx_env.is_symlink()
        assert "FOO=bar" not in host_env.read_text()
        assert "EXISTING=1" in host_env.read_text()
    print("ok write_through_symlink")


def test_plain_file_still_works():
    with tempfile.TemporaryDirectory() as home:
        (Path(home) / ".env").write_text("A=1\n")
        C = _reload_config(Path(home))
        C.save_env_value("B", "2")
        text = (Path(home) / ".env").read_text()
        assert "A=1" in text and "B=2" in text
    print("ok plain_file")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\nAll {len(fns)} tests passed.")

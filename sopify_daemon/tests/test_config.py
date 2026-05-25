"""Config file lifecycle — generate, persist, reload, reject corrupt."""
from __future__ import annotations

import os
import stat
import sys

import pytest

from sopify_daemon import config as daemon_config
from sopify_daemon import paths


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_CONFIG, str(tmp_path))
    yield tmp_path


def test_first_load_generates_token(isolated_config):
    cfg = daemon_config.load()
    assert cfg.token
    assert len(cfg.token) >= 32
    assert cfg.port == 7777
    assert cfg.bind == "127.0.0.1"
    # File must exist after first load
    assert paths.config_file().exists()


def test_token_is_64_hex_chars(isolated_config):
    cfg = daemon_config.load()
    # 256-bit token in hex = 64 chars
    assert len(cfg.token) == 64
    int(cfg.token, 16)  # raises if not valid hex


def test_file_mode_0600(isolated_config):
    if sys.platform.startswith("win"):
        return
    daemon_config.load()
    mode = stat.S_IMODE(os.stat(paths.config_file()).st_mode)
    assert mode == 0o600


def test_token_stable_across_loads(isolated_config):
    cfg1 = daemon_config.load()
    cfg2 = daemon_config.load()
    assert cfg1.token == cfg2.token


def test_create_if_missing_false_raises(isolated_config):
    with pytest.raises(FileNotFoundError):
        daemon_config.load(create_if_missing=False)


def test_corrupt_config_rejected(isolated_config):
    # Write a file without a token
    paths.config_file().write_text("port: 7777\n")
    with pytest.raises(ValueError):
        daemon_config.load()


def test_save_round_trip(isolated_config):
    cfg = daemon_config.load()
    cfg.port = 9090
    cfg.bind = "127.0.0.1"
    cfg.tags = {"env": "test"}
    daemon_config.save(cfg)
    reloaded = daemon_config.load()
    assert reloaded.port == 9090
    assert reloaded.tags == {"env": "test"}

"""`sopify admin …` subcommands.

REQ-6.3.3 — `sopify admin set-role <user> <user|dev>`.
REQ-9.1.2 — `sopify admin set-setting <key> <value>` (writes managed JSON).
"""
from __future__ import annotations

import json
import sys
from typing import List

from . import settings as managed


def _print_help() -> None:
    print(
        "sopify admin — IT-only commands\n"
        "\n"
        "  sopify admin set-role <user> <user|dev>\n"
        "  sopify admin set-setting <key> <json-value>\n"
        "  sopify admin show-settings\n"
    )


def _set_role(args: List[str]) -> int:
    if len(args) != 2:
        print("usage: sopify admin set-role <user> <user|dev>", file=sys.stderr)
        return 2
    target, role = args
    try:
        from importlib import import_module
        rolemod = import_module("plugins.sopify_guardrails.role")
        rolemod.set_role(target, role)  # type: ignore[arg-type]
    except PermissionError as exc:
        print(str(exc), file=sys.stderr)
        return 13
    except Exception as exc:
        print(f"set-role failed: {exc}", file=sys.stderr)
        return 1
    print(f"set role={role} for user={target}")
    return 0


def _set_setting(args: List[str]) -> int:
    if len(args) != 2:
        print("usage: sopify admin set-setting <key> <json-value>", file=sys.stderr)
        return 2
    key, raw = args
    try:
        value = json.loads(raw)
    except Exception:
        value = raw  # treat as string
    cur = managed.load()
    cur[key] = value
    managed.write_managed(cur)
    print(f"set {key} = {value!r}")
    return 0


def _show_settings(_: List[str]) -> int:
    print(json.dumps(managed.load(), indent=2))
    return 0


def main(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        _print_help()
        return 0
    cmd, rest = argv[0], argv[1:]
    return {
        "set-role": _set_role,
        "set-setting": _set_setting,
        "show-settings": _show_settings,
    }.get(cmd, lambda _: (_print_help(), 2)[1])(rest)

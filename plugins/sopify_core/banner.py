"""Sopify-themed banner for host-side commands.

Renders to a Rich console when `rich` is available, otherwise plain ANSI.
Used by `sopify install`, `sopify doctor`, `sopify --version`, `sopify --help`.
"""
from __future__ import annotations

import os
import shutil
import sys

from . import version

# Caduceus ASCII — Sopify blue palette (cyan→teal gradient).
SOPIFY_CADUCEUS = r'''[#67E8F9]       ,       ,[/]
[#67E8F9]      /|    |\./'.[/]
[#22D3EE]     | |  ,  \|| ,|[/]
[#22D3EE]     \  \_(\.-""\//.  _[/]
[#06B6D4]   .-'`""``"` _   ` `-.`"""--.._      _..----. __[/]
[#06B6D4]   | '~`      o\                `"---"        `. `"-.==,[/]
[#06B6D4]    \,.-;    `"`                                |`""`===`[/]
[#0891B2]      (`            /                           |[/]
[#0891B2]       `-----.____.;          \     |           ;[/]
[#0891B2]                   \__         |    \          /[/]
[#0E7490]                  .'         .'      \        ' `,[/]
[#0E7490]                 /          /         '._        |[/]
[#0E7490]                 |    '.---;`-.____.-'`\ `""`;   |[/]
[#155E75]                 |     _\   \    '.     )   /    \[/]
[#155E75]                 \-,--( /   /    _/   .'   |_ _ .-)[/]
[#155E75]                  '----;)__;    (`.-. ;    `-:.;-'[/]
[#155E75]                                 `""""`[/]'''

SOPIFY_WORDMARK = r'''[bold #67E8F9]   ____             _  __        [/]
[bold #67E8F9]  / ___|  ___  _ __ (_)/ _|_   _   [/]
[bold #22D3EE]  \___ \ / _ \| '_ \| | |_| | | |  [/]
[bold #22D3EE]   ___) | (_) | |_) | |  _| |_| |  [/]
[bold #06B6D4]  |____/ \___/| .__/|_|_|  \__, |  [/]
[bold #06B6D4]              |_|          |___/   [/]'''

TAGLINE = "AI agent + sandbox + 3 modes + org governance"


def _strip_rich(s: str) -> str:
    """Drop [color] tags so plain terminals don't see noise."""
    import re
    return re.sub(r"\[/?[^\]]+\]", "", s)


def _term_width() -> int:
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 80


def _emit_plain(stream=sys.stdout) -> None:
    """Fallback when Rich isn't available — clean ANSI cyan/blue."""
    CYAN = "\x1b[38;5;51m"      # bright cyan, #67E8F9-ish
    TEAL = "\x1b[38;5;45m"      # medium cyan, #22D3EE-ish
    BOLD = "\x1b[1m"
    RESET = "\x1b[0m"
    color_on = stream.isatty() and not os.environ.get("NO_COLOR")
    c = CYAN if color_on else ""
    t = TEAL if color_on else ""
    b = BOLD if color_on else ""
    r = RESET if color_on else ""
    art = _strip_rich(SOPIFY_CADUCEUS)
    print(c + art + r, file=stream)
    print(file=stream)
    print(f"  {b}{t}☤ {version.full_version_string()}{r}", file=stream)
    print(f"  {c}{TAGLINE}{r}", file=stream)
    print(file=stream)


def render(*, subtitle: str = "") -> None:
    """Print the Sopify banner. Quiet automatically when:
      - $SOPIFY_NO_BANNER is set
      - stdout is not a TTY (e.g. piping to a file)
    """
    if os.environ.get("SOPIFY_NO_BANNER"):
        return

    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
    except ImportError:
        _emit_plain()
        if subtitle:
            print(f"  {subtitle}\n")
        return

    console = Console()
    if not console.is_terminal:
        _emit_plain()
        if subtitle:
            print(f"  {subtitle}\n")
        return

    layout = Table.grid(padding=(0, 2))
    layout.add_column("art", justify="left")
    layout.add_column("info", justify="left")

    info_lines = [
        f"[bold #67E8F9]☤[/] [#E0F2FE]{version.full_version_string()}[/]",
        "",
        f"[#22D3EE]{TAGLINE}[/]",
    ]
    if subtitle:
        info_lines.append("")
        info_lines.append(f"[bold #67E8F9]{subtitle}[/]")
    info_lines.extend([
        "",
        "[dim #0E7490]REQ-0 foundation │ REQ-1 sandbox │ REQ-2 providers[/]",
        "[dim #0E7490]REQ-6 guardrails │ REQ-7 OTel    │ REQ-8 skills[/]",
        "[dim #0E7490]REQ-3/4/5 modes  │ REQ-9 mgmt    │ REQ-10 TUI[/]",
    ])
    layout.add_row(SOPIFY_CADUCEUS, "\n".join(info_lines))

    panel = Panel(
        layout,
        title="[bold #67E8F9]☤ Sopify ☤[/]",
        border_style="#06B6D4",
        padding=(0, 2),
    )

    console.print()
    if _term_width() >= 50:
        console.print(SOPIFY_WORDMARK)
        console.print()
    console.print(panel)
    console.print()

"""Sopify-themed banner for host-side commands.

Renders to a Rich console when `rich` is available, otherwise plain ANSI.
Used by `sopify install`, `sopify doctor`, `sopify --version`, `sopify --help`.
"""
from __future__ import annotations

import os
import shutil
import sys

from . import version

# Pixel rhino mascot — Sopify cyan/teal palette with pink ears.
# Half-block compressed (7 rows × 14 cols, was 14×28) — each ▀/▄ encodes two
# vertical pixels via foreground (top) + background (bottom) so the full
# 5-color palette is preserved at a quarter of the original footprint.
SOPIFY_CADUCEUS = (
    " [#164E63]▄[/][#164E63 on #22D3EE]▀▀[/][#164E63]▄[/]    [#164E63]▄[/][#164E63 on #22D3EE]▀▀[/][#164E63]▄[/] \n"
    "[#164E63]█[/][#22D3EE on #67E8F9]▀[/][#67E8F9]██[/][#22D3EE on #67E8F9]▀[/][#164E63 on #67E8F9]▀▀▀▀[/][#22D3EE on #67E8F9]▀[/][#67E8F9]██[/][#22D3EE on #67E8F9]▀[/][#164E63]█[/]\n"
    "[#164E63]█[/][#67E8F9]████[/][#67E8F9 on #0891B2]▀[/][#0891B2]██[/][#67E8F9 on #0891B2]▀[/][#67E8F9]████[/][#164E63]█[/]\n"
    "[#164E63]█[/][#67E8F9]██[/][#67E8F9 on #164E63]▀[/][#0891B2 on #67E8F9]▀▀▀▀▀▀[/][#67E8F9 on #164E63]▀[/][#67E8F9]██[/][#164E63]█[/]\n"
    "[#164E63]█[/][#67E8F9]█[/][#67E8F9 on #F9A8D4]▀▀[/][#67E8F9]██████[/][#67E8F9 on #F9A8D4]▀▀[/][#67E8F9]█[/][#164E63]█[/]\n"
    "[#164E63]█[/][#67E8F9 on #22D3EE]▀[/][#F9A8D4 on #67E8F9]▀▀[/][#67E8F9 on #22D3EE]▀[/][#67E8F9]████[/][#67E8F9 on #22D3EE]▀[/][#F9A8D4 on #67E8F9]▀▀[/][#67E8F9 on #22D3EE]▀[/][#164E63]█[/]\n"
    " [#164E63]▀██▀[/]    [#164E63]▀██▀[/] "
)

SOPIFY_WORDMARK = r'''[bold #67E8F9]      ___           ___           ___                 [/]
[bold #67E8F9]     /\  \         /\  \         /\  \          ___   [/]
[bold #22D3EE]    /::\  \       /::\  \       /::\  \        /\  \  [/]
[bold #22D3EE]   /:/\ \  \     /:/\:\  \     /:/\:\  \       \:\  \ [/]
[bold #06B6D4]  _\:\~\ \  \   /:/  \:\  \   /::\~\:\  \      /::\__\[/]
[bold #06B6D4] /\ \:\ \ \__\ /:/__/ \:\__\ /:/\:\ \:\__\  __/:/\/__/[/]
[bold #0891B2] \:\ \:\ \/__/ \:\  \ /:/  / \/__\:\/:/  / /\/:/  /   [/]
[bold #0891B2]  \:\ \:\__\    \:\  /:/  /       \::/  /  \::/__/    [/]
[bold #0E7490]   \:\/:/  /     \:\/:/  /         \/__/    \:\__\    [/]
[bold #0E7490]    \::/  /       \::/  /                    \/__/    [/]
[bold #155E75]     \/__/         \/__/                              [/]
[bold #67E8F9]      ___           ___     [/]
[bold #22D3EE]     /\  \         |\__\    [/]
[bold #22D3EE]    /::\  \        |:|  |   [/]
[bold #06B6D4]   /:/\:\  \       |:|  |   [/]
[bold #06B6D4]  /::\~\:\  \      |:|__|__ [/]
[bold #0891B2] /:/\:\ \:\__\     /::::\__\[/]
[bold #0891B2] \/__\:\ \/__/    /:/~~/~   [/]
[bold #0E7490]      \:\__\     /:/  /     [/]
[bold #155E75]       \/__/     \/__/      [/]'''

TAGLINE = "AI agent + sandbox + 3 modes + org governance"


_RICH_TAG_RE = None


def _strip_rich(s: str) -> str:
    """Drop [color] tags so plain terminals don't see noise."""
    import re
    return re.sub(r"\[/?[^\]]+\]", "", s)


def _hex_to_ansi(hex_color: str, *, bg: bool = False) -> str:
    """Convert a `#rrggbb` string into a 24-bit ANSI fg (38) or bg (48) sequence."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    if len(hex_color) != 6:
        return ""
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
    except ValueError:
        return ""
    base = 48 if bg else 38
    return f"\x1b[{base};2;{r};{g};{b}m"


def _render_rich_ansi(markup: str, color_on: bool) -> str:
    """Render rich-style markup (`[bold #rrggbb on #rrggbb]text[/]`) to ANSI.

    Supports an optional `on #rrggbb` background segment so the half-block
    mascot keeps its per-pixel-pair palette instead of dropping background
    color in non-Rich terminals.
    """
    import re

    global _RICH_TAG_RE
    if _RICH_TAG_RE is None:
        _RICH_TAG_RE = re.compile(
            r"\[(bold\s+)?(?:dim\s+)?(#(?:[0-9a-fA-F]{3,8}))"
            r"(?:\s+on\s+(#(?:[0-9a-fA-F]{3,8})))?"
            r"\]([\s\S]*?)\[/\]"
        )

    if not color_on:
        return _strip_rich(markup)

    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"

    def repl(m: "re.Match[str]") -> str:
        bold = bool(m.group(1))
        fg = _hex_to_ansi(m.group(2))
        bg = _hex_to_ansi(m.group(3), bg=True) if m.group(3) else ""
        text = m.group(4)
        prefix = (BOLD if bold else "") + fg + bg
        return f"{prefix}{text}{RESET}"

    return _RICH_TAG_RE.sub(repl, markup)


def _term_width() -> int:
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 80


def _emit_plain(stream=sys.stdout) -> None:
    """Fallback when Rich isn't available — render rich markup as raw ANSI."""
    color_on = stream.isatty() and not os.environ.get("NO_COLOR")
    art = _render_rich_ansi(SOPIFY_CADUCEUS, color_on)
    print(art, file=stream)
    print(file=stream)
    BOLD = "\x1b[1m" if color_on else ""
    TEAL = _hex_to_ansi("#22D3EE") if color_on else ""
    CYAN = _hex_to_ansi("#67E8F9") if color_on else ""
    RESET = "\x1b[0m" if color_on else ""
    print(f"  {BOLD}{TEAL}☤ {version.full_version_string()}{RESET}", file=stream)
    print(f"  {CYAN}{TAGLINE}{RESET}", file=stream)
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
    if _term_width() >= 60:
        console.print(SOPIFY_WORDMARK)
        console.print()
    console.print(panel)
    console.print()

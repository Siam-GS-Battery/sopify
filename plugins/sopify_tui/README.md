# sopify-tui

Owns *all* user-visible UI for sopify-* plugins. Every other plugin exposes a
`set_*_callback` hook; this plugin fills them in.

## Modules

| Module       | Purpose                                          | REQ      |
|--------------|--------------------------------------------------|----------|
| dialogs.py   | confirm_destructive / ask_network_permission / confirm_step | REQ-10.3, 10.4, 5.1.3 |
| footer.py    | mode + provider + quota + sandbox status line   | REQ-10.1, 2.1.5 |
| __init__.py  | Wire callbacks + `/status` + `/help`            | REQ-10.5, 10.8 |

## Dialogs wired

| Caller              | Callback                              |
|---------------------|---------------------------------------|
| `sopify-sandbox`    | `network_policy` → `ask_network_permission` |
| `sopify-guardrails` | soft-deny dev confirm → `confirm_destructive` |
| `sopify-modes.code_with_you` | step gate → `confirm_step`     |
| `sopify-management.quota`    | 80% warning → toast print     |

## Slash commands provided

- `/status` — calls `footer.render_status()` (mode, provider, quota, sandbox, living)
- `/help`   — prints `HELP_TEXT`

## Test plan

```bash
SOPIFY_HOME=/tmp/sopify uv run pytest plugins/sopify-tui/tests
```

Covers:
- Network dialog returns once/always/deny correctly
- Empty input on destructive dialog → safe default (no)
- Code-with-you step dialog → execute/skip/stop
- Thai UTF-8 round-trip without garbling

## Deferred

- Real Ink/React TUI (REQ-10 implies `Ink`). Today's dialogs are
  blocking `input()` calls — fine for CLI, but the integration with Hermes' Ink
  UI lives in `tui_gateway/` and is a separate slice.
- Streaming response rendering (REQ-10.7) — Hermes already streams; this
  plugin's footer only needs `on_render_footer` to fire per-token (already does
  via Hermes' lifecycle).
- Dangerous-command **iconography** (REQ-10.3) — using ⚠ + ANSI red today;
  Ink TUI will replace with proper icons.

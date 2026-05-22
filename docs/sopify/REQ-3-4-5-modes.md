# REQ-3 / 4 / 5 — Modes (/living, /vibe, /code-with-you)

> Status: scaffolded. Sources: [DESIGN_ARCHITECTURE.md §REQ-3](../../../DESIGN_ARCHITECTURE.md),
> §REQ-4, §REQ-5.

## What was built

- `plugins/sopify-modes/config.py` — three `ModeProfile` constants exactly
  reflecting the table in DESIGN_ARCHITECTURE (budgets, deny levels,
  parallel/confirm/persistent flags).
- `plugins/sopify-modes/living.py` — process status / graceful stop / daily
  backup / dept-context loader.
- `plugins/sopify-modes/vibe.py` — intake state machine + `app_fingerprint`
  hash for the promotion gate (REQ-4.4.1).
- `plugins/sopify-modes/code_with_you.py` — UI-agnostic confirm-every-step
  gate. Four choices: execute / skip / modify / stop.
- `plugins/sopify-modes/__init__.py` — `on_slash_command` activates a mode,
  notifies `sopify-otel`, and routes `pre_tool_call` to the active mode's
  guard.

## Checkbox coverage (compact)

| REQ section | What's covered                                                  |
|-------------|-----------------------------------------------------------------|
| REQ-3.1.1   | LIVING profile sets `persistent_session=True`                   |
| REQ-3.1.3   | Sessions dir + path constant (Hermes' SQLite WAL reused)        |
| REQ-3.1.5   | `living.status()` + `/living status` slash command              |
| REQ-3.1.6   | `living.stop()` SIGTERM + pidfile cleanup                       |
| REQ-3.3.1/2/3 | Strict deny, approval, no parallel — set in `LIVING` profile  |
| REQ-4.1.1   | `INTAKE_QUESTIONS` list + `render_intake_prompt`                |
| REQ-4.1.2   | `restate(answers)` text                                         |
| REQ-4.4.1   | `app_fingerprint(project_dir)` — sha256 of sorted paths         |
| REQ-5.1.1/2 | `code_with_you.gate(...)` + `explain(tool_name, args)`          |
| REQ-5.1.3   | Four choices in `OPTIONS` constant                              |
| REQ-5.1.4   | CODE_WITH_YOU profile sets `parallel_tool_execution=False`      |
| REQ-5.3.1   | `daily_token_budget = 50_000`                                   |

## Why the design

- **Mode = config + hook**, not = a separate runtime. Hermes already has a
  conversation loop; modes only *configure* it. This keeps mode-switching free
  of state-machine bugs.
- **`app_fingerprint` excludes `node_modules` / `.venv` / `dist`.** Otherwise
  every `npm install` would change the fingerprint and the promotion gate
  (REQ-4.4.2) would never fire.
- **`code_with_you.gate` is pure** and takes a callback. The TUI dialog is
  injected in `sopify-tui`; tests substitute a stub.

## Deferred

- `/tree` session-branching slash command (REQ-4.2.2)
- IT promotion-candidate notification cron (REQ-4.4.4) — lives in
  `cron/promotion-candidates.py`, wired in REQ-9
- Service registration for /living auto-resume (REQ-3.1.2)
- Token-budget watchdog + TUI alert (REQ-5.3.3) — lives in `sopify-tui`

## Verify

```bash
SOPIFY_HOME=/tmp/sopify uv run pytest plugins/sopify-modes/tests   # 7 tests
```

## Next

REQ-9 — `sopify-management`: managed settings + `sopify admin` subcommands +
`sopify onboard` + quota monitor.

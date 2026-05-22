# REQ-10 — TUI & REQ-11 — Security & Compliance

> Status: scaffolded. Sources: [DESIGN_ARCHITECTURE.md §REQ-10](../../../DESIGN_ARCHITECTURE.md),
> §REQ-11.

## REQ-10 — what was built

- `plugins/sopify-tui/dialogs.py` — three terminal dialogs:
  - `confirm_destructive(command, reason)` — soft-deny dev confirm (REQ-10.3)
  - `ask_network_permission(host, reason)` — once/always/deny (REQ-10.4)
  - `confirm_step(tool_name, args, explanation)` — code-with-you four-way
    (REQ-5.1.3)
- `plugins/sopify-tui/footer.py` — `render()` for the always-visible footer
  + `render_status()` for `/status` (REQ-10.1, 10.8, 2.1.5).
- `plugins/sopify-tui/__init__.py` — single `_wire_callbacks()` call on
  startup wires every other sopify-* plugin's UI hooks.
- `/status` and `/help` slash commands.

| REQ-10 checkbox | Coverage                                          |
|-----------------|---------------------------------------------------|
| 10.1            | `footer.render()`                                 |
| 10.2            | `/vibe` / `/living` / `/code-with-you` slash commands (sopify-modes) |
| 10.3            | `confirm_destructive` (ANSI red + ⚠)              |
| 10.4            | `ask_network_permission`                          |
| 10.5            | `HELP_TEXT` + `/help`                             |
| 10.6            | UTF-8 throughout; Thai test in `test_tui.py`      |
| 10.7            | Hermes already streams; we render footer per turn |
| 10.8            | `render_status()` + `/status`                     |

## REQ-11 — what was built (where it lives)

REQ-11 is **cross-cutting**. Each subsection landed in a plugin, not in a
dedicated REQ-11 plugin:

| REQ-11 | Where                                                     |
|--------|-----------------------------------------------------------|
| 11.1   | `sopify-providers/auth.py` — file mode 0600 on every write|
| 11.2   | `sopify-otel/redact.py` — redact runs before every emit   |
| 11.3   | `redact.redact_with_email(scrub_email=True)` option       |
| 11.4   | `docker/sopify-sandbox/Dockerfile` USER sopify (UID 10001)|
| 11.5   | Deferred — CVE scan in CI (REQ-9 follow-up)               |
| 11.6   | Upstream-watch is a process control (no code artifact)    |
| 11.7   | Same — process control (OTel schema watcher cron)         |

## Why split this way

- **TUI = the only printer.** Other plugins are pure. This means we can
  retarget Sopify at non-terminal UIs (Slack, web dashboard) by swapping the
  dialogs module — no other plugin needs to change.
- **Default-deny everywhere.** Empty input on `confirm_destructive` → no.
  Unrecognised network choice → deny. Soft-deny without UI → deny. The pattern
  is enforced consistently: when in doubt, don't.

## Deferred

- Full Ink/React TUI integration (the dialogs work today, but Hermes' rich
  Ink TUI integration is a follow-up).
- CVE-scan CI workflow (REQ-11.5) — `.github/workflows/sopify-cve.yml` not
  yet written.
- Upstream-watch automation (REQ-11.6/7) — these are process controls;
  there will be a `cron/upstream-watch.py` in a future slice but the schedule
  itself is org policy.

## Verify

```bash
SOPIFY_HOME=/tmp/sopify uv run pytest plugins/sopify-tui/tests   # 4 tests
```

## End of scaffold

This is the last REQ block in this pass. The next slices to take on:

1. **CI workflow** — `.github/workflows/sopify.yml` running ruff + mypy + the
   per-plugin pytest dirs.
2. **Hermes-core integration shims** (REQ-0.3-safe single-line additions in
   `agent/conversation_loop.py` to honour `override_provider`).
3. **Packaging scripts** — `packaging/sopify-install.sh` and
   `packaging/sopify-install.ps1` to pre-seed managed settings.

Each will get its own `docs/sopify/REQ-*-*.md` explainer when started.

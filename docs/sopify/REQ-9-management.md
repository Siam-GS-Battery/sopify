# REQ-9 — IT Management & Deployment

> Status: scaffolded. Source: [DESIGN_ARCHITECTURE.md §REQ-9](../../../DESIGN_ARCHITECTURE.md).

## What was built

- `plugins/sopify-management/settings.py` — managed-settings reader/writer.
  Forces mode 0444 on every write. `subscribe(fn)` lets any plugin react to
  changes; `poll_for_changes` runs an mtime-watching daemon so REQ-9.1.3
  ("no restart needed") is satisfied without an OS-level inotify dependency.
- `plugins/sopify-management/onboard.py` — `sopify onboard` consent flow.
  Writes `~/.sopify/consent.json` once accepted (REQ-7.4.4 audit notification).
- `plugins/sopify-management/quota.py` — token tally per provider per session.
  80% warning fires once (REQ-9.3.2). `report_exhausted` cascades into
  `ProviderRouter.record_failure(429)` (REQ-9.3.3).
- `plugins/sopify-management/admin.py` — `sopify admin set-role / set-setting /
  show-settings` subcommands.
- `__init__.py` wires `sopify-providers.reload_router` and
  `sopify-otel.reload_settings` to settings-change broadcasts.

## Checkbox coverage

| Checkbox | Coverage                                                  |
|----------|-----------------------------------------------------------|
| 9.1.1    | `write_managed` enforces 0444                             |
| 9.1.2    | DEFAULTS dict covers all six required keys                |
| 9.1.3    | `poll_for_changes` + `subscribe/broadcast`                |
| 9.2.3    | `onboard.run_interactive(user)`                           |
| 9.2.4    | Install event emitted in `sopify-core/install.py`         |
| 9.3.1    | `quota.record` per-provider tallies                       |
| 9.3.2    | `_maybe_warn` at 80%, dedupe in `_warned_at_80`           |
| 9.3.3    | `report_exhausted` cascades into ProviderRouter           |

## Why

- **mtime polling > inotify** here because: (a) it's cross-platform without
  extra deps; (b) the cost is one stat() every 5 s — negligible; (c) inotify
  inside a Docker container watching a bind mount is unreliable on macOS.
- **Subscriber pattern** keeps coupling one-way — `sopify-management` knows
  about every other plugin's "reload" entry point; the other plugins don't
  need to know about `sopify-management` at all. This makes
  `sopify plugins disable management` safe: nothing else breaks, only the
  live-reload feature is lost.
- **`write_managed` always 0444.** A correctly-MDM-pushed file should already
  be 0444; this enforces it from the admin-CLI side too so manual edits don't
  accidentally leave 0644.

## Deferred

- MDM-side distribution (REQ-9.1.1) — file layout is enforced; the corporate
  push mechanism (Jamf/Intune) lives outside this repo.
- Mass-deploy installer (REQ-9.2.2) — depends on `packaging/sopify-install.*`
  being written.
- Org-spend alerting (REQ-9.3.4) — webhook + threshold check live in
  `cron/org-spend-alert.py`.

## Verify

```bash
SOPIFY_HOME=/tmp/sopify uv run pytest plugins/sopify-management/tests
```

## Next

REQ-10 — `sopify-tui`. Mode badge, quota chip, network-permission dialog,
soft-deny dev confirm dialog.

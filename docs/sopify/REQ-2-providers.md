# REQ-2 — Provider & Auth

> Status: scaffolded.  Source: [DESIGN_ARCHITECTURE.md §REQ-2](../../../DESIGN_ARCHITECTURE.md).

## What was built

- `plugins/sopify-providers/router.py` — `ProviderRouter` dataclass with:
  - `pick()` — first non-blacklisted provider in chain
  - `record_failure(name, status, reason)` — 1h blacklist on 401/403/429 or
    quota/rate keywords
  - `from_settings()` — reads `provider_chain` from managed settings
  - `status_summary()` — for TUI footer
- `plugins/sopify-providers/auth.py` — `load`, `get`, `set_key`,
  `login_interactive`, `logout`. File mode locked to 0600 on every write.
- `plugins/sopify-providers/__init__.py` — Sopify lifecycle hooks:
  - `pre_api_request` → suggest reroute via `override_provider`
  - `post_api_request` / `api_error` → `record_failure`
- `reload_router()` exposed so `sopify-management` can pick up
  `settings.json` changes mid-session (REQ-9.1.3).

## Checkbox coverage

| Checkbox | Coverage                                                        |
|----------|-----------------------------------------------------------------|
| 2.1.1    | `ProviderRouter` class                                          |
| 2.1.2    | DEFAULT_CHAIN + `hermes_default` tail                           |
| 2.1.3    | `record_failure` blacklists 401/403 for 1h                      |
| 2.1.4    | Same path blacklists 429 + quota/rate keyword                   |
| 2.1.5    | `status_summary()` (consumed by sopify-tui)                     |
| 2.1.6    | `from_settings()` reads `provider_chain`                        |
| 2.2.1    | `_write_atomic` chmod 0600                                      |
| 2.2.2    | `load()` honours `ANTHROPIC_API_KEY`                            |
| 2.2.3    | `login_interactive()`                                           |
| 2.2.4    | `logout()` zero-fills then unlinks                              |

## Why

- **Blacklist TTL is a wall clock, not a counter.** A counter-based scheme
  would punish a provider that just blipped; an absolute TTL lets it self-heal
  exactly once an hour after the *latest* failure.
- **`hermes_default` always tail-appended** — without it, an exhausted custom
  chain would silently fail. With it, the user always reaches their pre-Sopify
  Hermes config.
- **Atomic auth.json writes** — never leave a half-written file at 0644 even
  for a microsecond. `tmp.chmod(0o600); tmp.replace(p)` guarantees the file is
  never visible outside 0600.

## Deferred

- **`override_provider` honoured by Hermes** — needs one line in
  `agent/conversation_loop.py`, which is Hermes-core; tracked separately so
  REQ-0.3 stays clean.
- **TUI footer rendering** — landed in `sopify-tui` (REQ-10).
- **Per-user provider quotas** (REQ-9.3) — `sopify-management` owns the daily
  budget watcher; this plugin only handles cascade failure.

## Verify

```bash
SOPIFY_HOME=/tmp/sopify uv run pytest plugins/sopify-providers/tests
SOPIFY_HOME=/tmp/sopify ./sopify login   # interactive; check /tmp/sopify/auth.json mode is 600
```

## Next

REQ-6 — guardrails (HARD_DENY / SOFT_DENY / role gating). These guard *all*
modes so they go in before /vibe etc.

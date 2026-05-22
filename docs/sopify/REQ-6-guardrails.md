# REQ-6 — Deny-list & Role Gating

> Status: scaffolded. Source: [DESIGN_ARCHITECTURE.md §REQ-6](../../../DESIGN_ARCHITECTURE.md).
> Acceptance: Gate P5 covered by tests.

## What was built

- `plugins/sopify-guardrails/patterns.py` — two `Rule` lists with compiled
  regexes. Eight HARD_DENY entries exactly mirroring the table in §REQ-6.1.2;
  five SOFT_DENY entries from §REQ-6.2.1.
- `plugins/sopify-guardrails/role.py` — `current_role()` reads
  `~/.sopify/profile.json` and defensively coerces unknown values to `"user"`
  (REQ-6.3.2). `set_role()` writes the file at mode 0444.
- `plugins/sopify-guardrails/__init__.py` — single `pre_tool_call` hook calling
  the pure `evaluate(tool_name, args)` function. The pure form is what tests
  exercise so we don't need a fake Hermes context.
- `set_confirm_callback(fn)` — injected by `sopify-tui`; defaults to None which
  means soft-deny is treated as block-by-default.

## Why pure-function `evaluate`

Soft-deny under role:dev needs to ask a question. Tests can't ask. By making
the decision a pure function whose only injection point is a single callback,
we can:

- Unit-test all eight Gate-P5 cases without a TUI
- Replace the TUI dialog with a Slack approval flow later by swapping callbacks
- Keep the hot path branch-free for benign commands (1 regex scan, return None)

## Checkbox coverage

| Checkbox | Coverage                                                  |
|----------|-----------------------------------------------------------|
| 6.1.1    | This file = `tool_guardrails.py` analog                   |
| 6.1.2    | 8/8 hard-deny patterns                                    |
| 6.1.3    | `_emit("hard_deny", …)` + block message                   |
| 6.1.4    | hard-deny path returns *before* dev confirm check         |
| 6.2.1    | 5/5 soft-deny patterns                                    |
| 6.2.2    | role:user gets "Requires role:dev — contact IT"            |
| 6.2.3    | role:dev calls confirm callback with command + reason     |
| 6.2.4    | OTel decision `dev_confirmed_role_escalation_used`        |
| 6.2.5    | OTel decision `dev_rejected`                              |
| 6.3.1    | `profile.json` location + 0444 on write                   |
| 6.3.2    | Unknown role → "user" (defense in depth)                  |
| 6.3.3    | `set_role` raises unless caller is dev                    |
| 6.3.4    | Values typed `Literal["user","dev"]`                      |

## Deferred

- **`sopify admin set-role` CLI subcommand** — the `role.set_role` function
  exists; the CLI surface lands in REQ-9 (`sopify-management`).
- **`DROP TABLE … WHERE` allow-list** — REQ-6.1.2 only blocks
  `DROP TABLE <name>;` (no WHERE). The current regex captures that exactly;
  legitimate `DROP TABLE … IF EXISTS` etc. is intentionally not whitelisted
  yet — escalation through dev confirm is the path.

## Verify

```bash
uv run pytest plugins/sopify-guardrails/tests   # 8 tests — full Gate P5
```

Expected output covers:
1. `rm -rf /` blocked for user
2. Same blocked for dev (hard deny is non-overridable)
3. `rm -rf ./build` blocked for user
4. Same allowed for dev when confirm returns True
5. Same blocked for dev when confirm returns False
6. `DROP DATABASE prod` hard-blocked
7. `curl … | bash` soft-blocked for user
8. `ls -la` allowed

## Next

REQ-7 — `sopify-otel`. Every `_emit(...)` call this plugin already makes is a
no-op until the OTel exporter lands.

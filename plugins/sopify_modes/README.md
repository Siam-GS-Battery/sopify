# sopify-modes

Three modes: `/living`, `/vibe`, `/code-with-you`. Each activates a profile
(`config.ModeProfile`), tells `sopify-otel` the current mode, and triggers
`sopify-skills` to inject the right bundles.

## Modules

| Module          | REQ        | What                                              |
|-----------------|------------|---------------------------------------------------|
| config.py       | 3.3, 4, 5  | `ModeProfile` per mode (budget, deny level, …)    |
| living.py       | 3.1, 3.2   | status / stop / backup / dept-context             |
| vibe.py         | 4.1, 4.4   | intake state machine + app_fingerprint            |
| code_with_you.py| 5.1        | confirm-every-step gate + callback contract       |
| __init__.py     | all        | slash-command hook + pre_tool_call gate           |

## Slash commands

| Command          | Effect                                                          |
|------------------|-----------------------------------------------------------------|
| `/living`        | Activate LIVING profile (strict, persistent, no parallel tools) |
| `/living status` | uptime / pid / running (REQ-3.1.5)                              |
| `/living stop`   | graceful SIGTERM (REQ-3.1.6)                                    |
| `/vibe`          | Activate VIBE profile + start guided intake                     |
| `/code-with-you` | Activate code-with-you (50k budget, confirm-every-step)         |

## Mode profiles

| Field                             | living | vibe   | code-with-you |
|-----------------------------------|--------|--------|---------------|
| daily_token_budget                | 300k   | 200k   | 50k           |
| deny_list_level                   | strict | default| default       |
| parallel_tool_execution           | false  | true   | false         |
| require_approval_for_destructive  | true   | false  | true          |
| confirm_every_step                | false  | false  | true          |
| persistent_session                | true   | false  | false         |

## Test plan

```bash
SOPIFY_HOME=/tmp/sopify uv run pytest plugins/sopify-modes/tests
```

Covers:
- Living profile strict + persistent
- Code-with-you budget 50k + confirm-every-step
- Vibe intake question ordering
- Code-with-you gate: skip blocks, execute passes
- App fingerprint stable, changes on file add
- `/vibe` slash command sets `active_mode == "vibe"`

## Deferred

- **systemd / launchd / Windows service** for /living auto-resume (REQ-3.1.2) —
  shipped under `packaging/sopify-living.service`. Registration happens during
  `sopify install` when `mode == "living"` is in settings.json. Out of scope
  for this slice; tracked in REQ-9.
- **Session branching `/tree`** for /vibe (REQ-4.2.2) — Hermes already has a
  session-branching mechanism; the `/tree` slash command itself is added in a
  follow-up.
- **Token-budget enforcement** (REQ-5.3.3 alert) — value lives on the profile;
  enforcement plus TUI alert lives in `sopify-tui` (REQ-10).

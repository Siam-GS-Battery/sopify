# sopify-guardrails

`tool_guardrails.py` (the file DESIGN_ARCHITECTURE.md REQ-6.1.1 calls for) lives
here. Implements HARD_DENY + SOFT_DENY + role gating on every tool call.

## Decision flow

```
pre_tool_call(tool_name, args)
  └─ extract command string from args
       └─ HARD_DENY match? → block + emit hard_deny + return
       └─ SOFT_DENY match?
            ├─ role:user → block + emit soft_deny_blocked
            └─ role:dev  → confirm callback
                  ├─ approved → emit dev_confirmed_role_escalation_used → allow
                  └─ rejected → emit dev_rejected → block
       └─ else → allow
```

## Modules

| Module       | Purpose                                       | REQ            |
|--------------|-----------------------------------------------|----------------|
| patterns.py  | HARD_DENY + SOFT_DENY regex tables            | REQ-6.1.2, 6.2.1 |
| role.py      | profile.json reader + `assert_dev_only`       | REQ-6.3.*      |
| __init__.py  | `evaluate()` pure-function + pre_tool_call hook | REQ-6.1.3, 6.2.4/5 |

## Pattern coverage

Hard deny (uncircumventable, REQ-6.1.4):

| Name              | Regex (summary)                                    |
|-------------------|----------------------------------------------------|
| rm-rf-root        | `rm -rf /`, `rm -rf ~`, `rm -rf $HOME`             |
| drop-database     | `DROP DATABASE`                                    |
| drop-table-no-where | `DROP TABLE <name>;`                             |
| fork-bomb         | `:(){ :|:& };:`                                    |
| mkfs              | `mkfs.*`                                           |
| dd-block-device   | `dd … of=/dev/sd*`                                 |
| chmod-777-root    | `chmod -R 777 /`                                   |
| system-shutdown   | `shutdown` / `reboot` / `halt` / `poweroff`        |

Soft deny (user: block, dev: confirm):

| Name              | Regex (summary)                                    |
|-------------------|----------------------------------------------------|
| delete-no-where   | `DELETE FROM <table>;` (no WHERE)                  |
| truncate          | `TRUNCATE TABLE`                                   |
| rm-rf-any         | `rm -rf <path>`                                    |
| git-force-push    | `git push … --force`                               |
| curl-pipe-shell   | `curl/wget … | bash/sh`                            |

## Confirmation UI

This plugin is UI-agnostic. `sopify-tui` calls
`sopify_guardrails.set_confirm_callback(fn)` on startup. If no UI is wired up,
soft-deny defaults to deny (safer than silent execute).

## Test plan

```bash
uv run pytest plugins/sopify-guardrails/tests
```

Covers Gate P5 verbatim:
- `rm -rf /` blocked even for dev with confirm-True
- role:user `rm -rf ./folder` blocked
- role:dev `rm -rf ./folder` + confirm-True → allowed
- role:dev + confirm-False → blocked

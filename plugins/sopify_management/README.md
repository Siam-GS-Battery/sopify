# sopify-management

IT-controlled surface: managed settings, onboard consent, quota monitor,
`sopify admin` subcommands.

## Modules

| Module       | REQ        | Purpose                                          |
|--------------|------------|--------------------------------------------------|
| settings.py  | 9.1.*      | Load/write `~/.sopify/settings.json` at 0444 + subscribe/broadcast |
| onboard.py   | 9.2.3, 7.4.4 | Welcome flow + audit-consent record           |
| quota.py     | 9.3.*      | Per-provider session token tally + 80% warning  |
| admin.py     | 6.3.3, 9.1.2 | `sopify admin set-role / set-setting / show-settings` |
| __init__.py  | 9.1.3      | Wires subscribers + starts mtime polling        |

## Managed settings keys

```json
{
  "provider_chain": ["anthropic", "openrouter"],
  "otel_endpoint": "http://otel-collector.gsbattery.local:4318/v1/logs",
  "allowed_domains": ["confluence.gsbattery.local"],
  "daily_token_budgets": {"living": 300000, "vibe": 200000, "code-with-you": 50000},
  "log_user_prompts": false,
  "sandbox_enabled": true,
  "org_id": "gsbattery",
  "phase": 1
}
```

File mode is forced to **0444** on every write — user reads only.

## Live reload (REQ-9.1.3)

`poll_for_changes` runs a daemon thread that watches the mtime of
`settings.json`. On change, every subscriber callback is invoked:

- `sopify-providers.reload_router()` — rebuild provider chain
- `sopify-otel.reload_settings()` — pick up new OTel endpoint

No session restart needed.

## Quota

`quota.record(provider, input_tokens, output_tokens, cost_usd)` is called from
the `post_api_request` hook. At 80% of the active mode's daily budget, the
warning callback fires once per provider per session. Exhaustion (caller calls
`report_exhausted`) cascades into `ProviderRouter.record_failure(429)`.

## `sopify admin`

```
sopify admin set-role <user> <user|dev>      # requires caller role:dev
sopify admin set-setting <key> <json>        # writes 0444 settings.json
sopify admin show-settings                   # dumps current merged settings
```

## Test plan

```bash
SOPIFY_HOME=/tmp/sopify uv run pytest plugins/sopify-management/tests
```

Covers:
- Defaults loaded when file missing
- `write_managed` enforces 0444
- Subscriber broadcast on write
- Quota warning fires at 80% and only once
- Onboard consent file written

## Deferred

- **MDM push pipeline** (REQ-9.1.1) — file layout enforced here; the corporate
  push mechanism (Jamf/Intune/Workspace ONE) is org-specific and lives outside
  this repo.
- **Mass-deploy installer** (REQ-9.2.2) — once `packaging/sopify-install.sh`
  exists, pre-seeding `settings.json` is a 3-line shell call.
- **Org-spend Slack alert** (REQ-9.3.4) — webhook wiring goes in the `cron/`
  directory; the threshold is already a settings key (`org_spend_alert_usd`).

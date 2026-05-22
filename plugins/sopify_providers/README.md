# sopify-providers

Provider cascade with 1-hour blacklist on 401/403/rate-limit; auth file at
0600 with env-var override.

## Modules

| Module    | Purpose                                                 | REQ                  |
|-----------|---------------------------------------------------------|----------------------|
| router.py | `ProviderRouter` dataclass: `pick()` + `record_failure` | REQ-2.1.1–2.1.4, 2.1.6 |
| auth.py   | `~/.sopify/auth.json` (0600) + interactive login/logout | REQ-2.2.1–2.2.4      |
| __init__.py | Hooks: pre_api_request rerouting, post-error blacklist | REQ-2.1.3/4         |

## Cascade

Default chain: `["anthropic", "openrouter", "hermes_default"]`. IT can override
via `~/.sopify/settings.json`:

```json
{ "provider_chain": ["openrouter", "anthropic"] }
```

`hermes_default` is auto-appended so the cascade can always fall through to any
remaining Hermes provider (REQ-2.1.2 "any Hermes provider").

## TUI footer (REQ-2.1.5)

`sopify-tui` reads `ROUTER.status_summary()` once per render. Example output:

```
active=anthropic blacklisted=[openrouter(retry in 2873s)]
```

## Auth

- `sopify login` → prompts for provider + key, writes `auth.json` mode 0600.
- `sopify logout` → zero-fills file content before unlinking (REQ-2.2.4).
- `ANTHROPIC_API_KEY` env var overrides file at read time (REQ-2.2.2).

## Test plan

```bash
uv run pytest plugins/sopify-providers/tests
```

## Deferred

- Real `pre_api_request` integration with Hermes' provider transport — needs a
  small patch in `agent/conversation_loop.py` to honour `override_provider`.
  Until that lands, the router is *advisory*: it picks but Hermes still uses
  whatever `/model` was last set to. The integration is one Hermes-core line
  change which is out-of-scope per REQ-0.3; the workaround is documented in
  `docs/sopify/REQ-2-providers.md`.

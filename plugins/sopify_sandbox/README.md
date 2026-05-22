# sopify-sandbox

Docker sandbox launcher + network-egress policy hook (REQ-1).

## Modules

| Module               | Purpose                                                | REQ                       |
|----------------------|--------------------------------------------------------|---------------------------|
| launcher.py          | `docker run` argv builder + spawn + --no-sandbox guard | REQ-1.2.1–1.2.8, 1.3.*    |
| network_policy.py    | Decision engine: whitelist + persisted user_added       | REQ-1.2.2–1.2.6           |
| __init__.py          | `pre_tool_call` hook → block disallowed egress          | REQ-1.2.3, 1.2.7          |

## Image layout

- `docker/sopify-sandbox/Dockerfile` — debian-slim + Sopify runtime, non-root
  user (REQ-11.4), tini PID 1 for zombie reaping.
- `docker/sopify-sandbox/entrypoint.sh` — validates required mounts, symlinks
  `/sopify-*/*` into `$SOPIFY_HOME`, executes `sopify-runtime.py`.

## Lifecycle

```
host: sopify /vibe
        └─ launcher.spawn() builds:
             docker run --rm -i \
               --network sopify-net \
               -v $PWD:/workspace:rw \
               -v ~/.sopify/auth.json:/sopify-auth/auth.json:ro \
               -v ~/.sopify/settings.json:/sopify-config/settings.json:ro \
               -v ~/.sopify/sessions:/sopify-sessions:rw \
               sopify-sandbox:latest /vibe
container: entrypoint.sh validates mounts → python3 sopify-runtime.py /vibe
            └─ loads every plugins/sopify-* → hands off to Sopify
```

## --no-sandbox

`role: "dev"` → bypass sandbox (logged OTel `tool_decision sandbox_disabled`).
`role: "user"` → returns exit 13, no execution.

## Test plan

```bash
uv run pytest plugins/sopify-sandbox/tests
```

- `network_policy.evaluate("api.anthropic.com")` → allow (default)
- `network_policy.evaluate("evil.com")` with ask_user returning "deny" → block
- `network_policy.evaluate("ok.com")` with ask_user returning "always" → allow +
  `network-policy.json.user_added` includes "ok.com"
- Launcher refuses `--no-sandbox` when role=="user"

## Deferred

- **iptables egress enforcement at the network layer** — current behavior blocks
  at the *tool* level (pre_tool_call hook). True L3 enforcement requires either
  a docker network plugin or an outbound proxy sidecar; tracked separately.
- **Container resource limits** (RAM cap for REQ-12) — `--memory 512m` should be
  added to launcher.spawn once we have a per-mode override path from
  sopify-modes.

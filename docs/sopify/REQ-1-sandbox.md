# REQ-1 — Docker Sandbox (Embedded, First-class)

> Status: scaffolded.  Source: [DESIGN_ARCHITECTURE.md §REQ-1](../../../DESIGN_ARCHITECTURE.md).

## What was built

### Image
- `docker/sopify-sandbox/Dockerfile` — debian-slim base, tini PID 1, non-root
  `sopify` user (UID 10001 — satisfies REQ-11.4). Declares the four
  mountpoints up-front so a misconfigured launcher fails fast.
- `docker/sopify-sandbox/entrypoint.sh` — validates mounts, symlinks host
  config into `$SOPIFY_HOME`, execs `sopify-runtime.py`.

### Runtime entry
- `sopify-runtime.py` — in-container entry. Walks `plugins/sopify-*`, imports
  each (best-effort, never fatal), then hands off to `hermes_cli.main`.

### Plugin
- `plugins/sopify-sandbox/launcher.py` — builds the `docker run` argv with all
  four mounts (REQ-1.2.5–1.2.8) and `--rm` (REQ-1.2.4 — no orphan containers).
  Refuses `--no-sandbox` for `role:"user"` (REQ-1.3.3).
- `plugins/sopify-sandbox/network_policy.py` — pure-function decision engine:
  managed allowlist ∪ default whitelist ∪ user-added. Subdomain matching via
  `endswith(".d.com")`.
- `plugins/sopify-sandbox/__init__.py` — `pre_tool_call` hook that intercepts
  network-using tools (`fetch_url`, `web_search`, `browser_*`, `playwright_*`),
  evaluates against policy, returns a `blocked` dict to short-circuit when
  denied + emits `tool_decision` OTel event.

## Checkbox coverage

| Checkbox | How covered                                                          |
|----------|----------------------------------------------------------------------|
| 1.1.1    | `sopify install` pull or build (`plugins/sopify-core/install.py`)    |
| 1.1.2    | Docker check + guide message in install.py + launcher.py             |
| 1.1.3    | Network creation in install.py                                       |
| 1.1.4    | network-policy.json defaults written in install.py                   |
| 1.1.5    | `doctor.run()` includes `sandbox-image` and `sandbox-net` checks     |
| 1.2.1    | All code outside `launcher.py` runs inside the container             |
| 1.2.2    | launcher = `docker run` + `-i`/`-t` + forward, nothing else          |
| 1.2.3    | `SANDBOX_IMAGE = "sopify-sandbox:latest"` constant                   |
| 1.2.4    | `--rm` flag                                                          |
| 1.2.5–8  | Four `-v` mounts with correct ro/rw                                  |
| 1.2.3 (egress) | pre_tool_call hook + ask_user injection                        |
| 1.2.4 (dialog) | Decision: once / always / deny                                 |
| 1.2.5 (persist) | `persist_allow_always`                                        |
| 1.2.6    | Managed `allowed_domains` merged from `settings.json`                |
| 1.2.7    | `_emit("blocked", host, reason)` on denial                           |
| 1.3.1–3  | `--no-sandbox` allowed only when role=="dev", logged via OTel        |

## Why these choices

- **Tool-level egress filtering** (rather than iptables) keeps the plugin pure
  Python and testable. The trade-off is that any AI-spawned subprocess that
  bypasses Hermes' tool registry can still reach the network. That gap is
  closed in a later pass with a proxy sidecar (called out under Deferred).
- **`--rm` always-on** is the simplest cure for orphan containers (REQ-1.2.4).
  If we ever need session resumption, /living mode will pin a named container
  and override this flag explicitly.
- **`SOPIFY_HOME` env var** lets unit tests use a tmpdir without touching real
  user config — a hard requirement for CI.

## Deferred

- L3 egress enforcement (iptables/proxy). Tool-level only today.
- Per-mode resource caps (`--memory`, `--cpus`). Plumbed when sopify-modes lands.
- Container image scanning in CI (REQ-11.5). Belongs in REQ-11 explainer.

## How to verify

```bash
docker build -t sopify-sandbox:latest docker/sopify-sandbox
./sopify install                # creates sopify-net + policy file
./sopify doctor                 # sandbox-image / sandbox-net should be OK
uv run pytest plugins/sopify-sandbox/tests
```

## Next

REQ-2 — `sopify-providers` plugin: `ProviderRouter` with 1-hour blacklist on
401/403/rate-limit, auth.json at 0600.

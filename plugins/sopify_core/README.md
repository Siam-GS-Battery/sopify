# sopify-core

Foundation plugin. Every other `sopify-*` plugin depends on this one for
canonical paths, version reporting, and the install/doctor entry points.

## Modules

| Module      | Purpose                                                   | REQ                 |
|-------------|-----------------------------------------------------------|---------------------|
| paths.py    | `~/.sopify/{settings,profile,auth,network-policy,sessions}` | REQ-1.2.6/7/8, 6.3.1, 9.1.1 |
| version.py  | `sopify --version` — Sopify + runtime version              | REQ-0.5             |
| doctor.py   | `sopify doctor` — auth / sandbox / OTel health             | REQ-0.8, REQ-1.1.5  |
| install.py  | `sopify install` — Docker pull + network + policy + emit  | REQ-0.7, REQ-1.1.*, REQ-9.2.4 |

## Hooks registered

- `on_startup` — log "sopify-core loaded vX.Y.Z" so the plugin registry shows it.

## Env overrides

- `SOPIFY_HOME` — alternate root for tests; defaults to `~/.sopify`.

## Test plan

```bash
uv run pytest plugins/sopify-core/tests
```

Test that:
1. `paths.home()` honours `$SOPIFY_HOME`
2. `version.full_version_string()` contains both "sopify" and "runtime"
3. `doctor.run()` returns within < 3s (Gate P2)
4. `install.run()` is idempotent (running twice → same result, no errors)

## Deferred

- `sopify install` does NOT yet register a systemd / launchd / Windows service
  (REQ-9.2.1 service register). The service hook lives in `sopify-modes` (it is
  /living-specific) and is wired in REQ-3.

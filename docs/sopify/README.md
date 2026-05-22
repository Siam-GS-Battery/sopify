# Sopify — Section Explainers

One markdown per REQ block in DESIGN_ARCHITECTURE.md. Each explainer reports
what was built, why, and what is intentionally deferred.

| Section                                    | Plugin(s)                                  |
|--------------------------------------------|--------------------------------------------|
| [REQ-0 — Foundation](REQ-0-foundation.md)  | `plugins/sopify_core`                      |
| [REQ-1 — Docker Sandbox](REQ-1-sandbox.md) | `plugins/sopify_sandbox`                   |
| [REQ-2 — Provider & Auth](REQ-2-providers.md) | `plugins/sopify_providers`              |
| [REQ-6 — Deny-list & Roles](REQ-6-guardrails.md) | `plugins/sopify_guardrails`          |
| [REQ-7 — OTel Pipeline](REQ-7-otel.md)     | `plugins/sopify_otel`                      |
| [REQ-8 — Skills & Org Context](REQ-8-skills.md) | `plugins/sopify_skills` + `sopify_skill_bundles/` |
| [REQ-3 / 4 / 5 — Modes](REQ-3-4-5-modes.md) | `plugins/sopify_modes`                    |
| [REQ-9 — IT Management](REQ-9-management.md) | `plugins/sopify_management`              |
| [REQ-10 / 11 — TUI + Security](REQ-10-11-tui-security.md) | `plugins/sopify_tui` + cross-plugin |

## Companion documents

- [`SOPIFY_PLAN.md`](../../SOPIFY_PLAN.md) — execution plan (read first)
- [`SOPIFY_ARCH.md`](../../SOPIFY_ARCH.md) — architecture map (REQ-0.2)
- [`../../DESIGN_ARCHITECTURE.md`](../../../DESIGN_ARCHITECTURE.md) — requirements (source of truth)

## Status snapshot

50 tests pass across 9 plugins:

```
plugins/sopify_core/tests              4 passed
plugins/sopify_providers/tests         5 passed
plugins/sopify_guardrails/tests        8 passed
plugins/sopify_otel/tests              6 passed
plugins/sopify_skills/tests            6 passed
plugins/sopify_modes/tests             7 passed
plugins/sopify_management/tests        5 passed
plugins/sopify_tui/tests               4 passed
plugins/sopify_sandbox/tests           5 passed
```

## How to run the test suite

```bash
SOPIFY_HOME=/tmp/sopify-test \
  uv run --with pytest --with pytest-xdist --with pytest-timeout \
  python -m pytest plugins/sopify_*/tests -n0 -o addopts=
```

The `addopts=` clear is required because Hermes' `pyproject.toml` defines
default pytest args (`-n`, `--timeout`) that conflict with running a subset.

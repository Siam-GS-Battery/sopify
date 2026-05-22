# Sopify Implementation Plan

> Source of truth: [DESIGN_ARCHITECTURE.md](../DESIGN_ARCHITECTURE.md)
> Architecture rule (REQ-0.3): **All Sopify code lives in `plugins/sopify-*/`.
> Hermes core is read-only — we only register hooks.**

---

## 1. Strategy

Hermes already has a strong plugin system (`plugins/<category>/<name>/__init__.py` with
a `register(ctx)` entry point that calls `ctx.register_hook(...)`). Sopify is built as a
suite of cooperating plugins that hook into Hermes' existing lifecycle:

```
plugins/
├── sopify-core/         REQ-0   foundation, version, doctor, install
├── sopify-sandbox/      REQ-1   Docker sandbox launcher + network policy
├── sopify-providers/    REQ-2   ProviderRouter (cascade + blacklist)
├── sopify-guardrails/   REQ-6   HARD_DENY / SOFT_DENY + role gating
├── sopify-otel/         REQ-7   5-event OTel pipeline
├── sopify-skills/       REQ-8   org skill bundles (company-sop, living, vibe, …)
├── sopify-modes/        REQ-3/4/5  /living, /vibe, /code-with-you
├── sopify-management/   REQ-9   managed settings + onboard
└── sopify-tui/          REQ-10  TUI overlay (mode badge, quota, dialogs)
```

A thin `sopify` shim CLI lives at the repo root and forwards to the Hermes CLI after
loading all sopify-* plugins.

## 2. Build Order

| Phase | REQs | Why first |
|---|---|---|
| 1 | REQ-0 → REQ-1 → REQ-2 | Nothing runs without foundation, sandbox, and auth |
| 2 | REQ-6 → REQ-7 → REQ-8 | Governance + audit + org context (must precede modes) |
| 3 | REQ-3/4/5 → REQ-9 → REQ-10 | Modes wire everything together; IT mgmt + TUI polish |
| 4 | REQ-11 → REQ-12 | Cross-cutting hardening + non-functional verification |

## 3. Conventions

- **Plugin layout** (mirrors `plugins/observability/langfuse/`):
  ```
  plugins/sopify-<name>/
  ├── __init__.py     # def register(ctx) — registers hooks
  ├── plugin.yaml     # manifest (name, version, hooks, requires_env)
  ├── README.md       # what this plugin does, env vars, traceability
  └── <modules>.py    # implementation
  ```
- **Naming** — `sopify-` prefix mandatory (REQ-0.3 enforces grep-able boundary).
- **Settings** — read from `~/.sopify/settings.json` (managed, 0444) with override from
  `~/.sopify/profile.json` (user role) and `~/.sopify/auth.json` (0600 secrets).
- **OTel** — every plugin emits via `sopify-otel/emit.py` only; never directly.
- **Tests** — each plugin ships `tests/test_<name>.py` runnable from repo root with
  `uv run pytest plugins/sopify-<name>/tests`.

## 4. Acceptance Gate Mapping

Each phase ends at one of the gates in DESIGN_ARCHITECTURE.md §"Acceptance Criteria":
- Phase 1 → Gate P2 (sandbox + doctor)
- Phase 2 → Gate P5 (deny-list)
- Phase 3 → Gate P6 (pilot)

## 5. Per-section Deliverables

For every REQ section we deliver:
1. Plugin source (`plugins/sopify-<name>/`)
2. Plugin README mapping checkboxes → modules
3. A top-level explainer `docs/sopify/REQ-<n>-<slug>.md` that summarises **what was
   built, why, and what is intentionally deferred** so the user can review without
   reading code.

## 6. Out of Scope (this pass)

- Grafana dashboards (REQ-7.3) — declared via `grafana/` JSON, not deployed.
- IT MDM push pipeline (REQ-9.1.1) — file layout enforced, distribution mechanism is
  org-specific and lives outside this repo.
- Windows installer .ps1 deep-test (REQ-0.6) — script stubbed, full Windows CI is a
  follow-up.

Anything deferred is called out in the section explainer with a `**Deferred:**` line.

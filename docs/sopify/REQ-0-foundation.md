# REQ-0 — Foundation (Hermes Base)

> Status: scaffolded. Source: [DESIGN_ARCHITECTURE.md §REQ-0](../../../DESIGN_ARCHITECTURE.md).

## What was built

| Artifact                                              | Checkbox covered                       |
|-------------------------------------------------------|----------------------------------------|
| `SOPIFY_ARCH.md` at repo root                         | REQ-0.2 (SPOF-protection doc first)    |
| `SOPIFY_PLAN.md` at repo root                         | execution roadmap                      |
| `plugins/sopify-core/` plugin (paths/version/doctor/install) | REQ-0.5, REQ-0.7, REQ-0.8       |
| `sopify` shim at repo root                            | host-side launcher (REQ-1.2.2)         |
| `docs/sopify/` directory                              | per-section explainer home             |

### Behavior delivered

1. **`sopify --version`** → prints `sopify 0.1.0 (runtime <ver>)`.
2. **`sopify install`** → checks Docker daemon, pulls/builds `sopify-sandbox:latest`,
   creates `sopify-net` bridge network, writes default
   `~/.sopify/network-policy.json`, emits `install_complete` if `sopify-otel` is
   loaded.
3. **`sopify doctor`** → 5 checks (docker / image / network / auth file mode / OTel
   reachability) returning within < 3 seconds (Gate P2).
4. **`sopify <anything else>`** → routes through the sandbox launcher (REQ-1).

### Architecture rules made enforceable

- REQ-0.3 grep-bait: every Sopify module lives under `plugins/sopify-*/` or
  `sopify_skills/` or `docs/sopify/`. `git grep -L "sopify" plugins/sopify-*` would
  identify any stray Hermes-core edit on review.
- REQ-0.4 — CI hookup pending (no `.github/workflows/sopify.yml` written yet — that
  is a follow-up; the explainer for REQ-9 will own it).

## Why the choices

- **One plugin per REQ section** keeps blast radius small. A bug in
  `sopify-providers` cannot brick `sopify-guardrails`; each can be disabled via
  `sopify plugins disable <name>` and Sopify degrades gracefully.
- **`sopify` shim is intentionally tiny.** Host code must do as little as possible
  (REQ-1.2.2). Anything that could plausibly need network or filesystem rights goes
  inside the sandbox.
- **`SOPIFY_HOME` env override** is added before any code reads `~/.sopify/*` so unit
  tests get a clean tmpdir without touching the developer's real config.

## Deferred / explicitly not in this slice

- **Windows `install.ps1`** (REQ-0.6) — Hermes already ships `scripts/install.ps1`; a
  Sopify-specific wrapper that pre-seeds `~/.sopify/settings.json` is a follow-up in
  REQ-9 (IT Management). Same goes for `install.sh`.
- **`sopify update`** — the upstream runtime already has its own `update`
  command. A Sopify wrapper that pins the sandbox image tag is a 5-line
  follow-up.
- **CI workflow YAML** (REQ-0.4 ruff/mypy/tests gate) — see REQ-9 explainer.

## How to verify locally

```bash
cd sopify-harness
./sopify --version
./sopify doctor           # expect "docker" / "sandbox-image" / "sandbox-net" / "auth" / "otel" rows
SOPIFY_HOME=/tmp/sopify ./sopify install   # idempotent, leaves no state in $HOME
uv run pytest plugins/sopify-core/tests
```

## Next

REQ-1 — `sopify-sandbox` plugin that owns `launcher.py` (the `_spawn_sandbox` call
the shim makes) and `network_policy.py` (egress filtering + allow/deny dialog).

# Sopify ☤

<p align="center">
  <img src="https://img.shields.io/badge/Status-Phase%201-67E8F9?style=for-the-badge" alt="Status: Phase 1">
  <img src="https://img.shields.io/badge/Org-GS%20Battery-22D3EE?style=for-the-badge" alt="GS Battery">
  <img src="https://img.shields.io/badge/License-MIT-06B6D4?style=for-the-badge" alt="License: MIT">
  <a href="DESIGN_ARCHITECTURE.md"><img src="https://img.shields.io/badge/Spec-DESIGN__ARCHITECTURE-0891B2?style=for-the-badge" alt="Spec"></a>
</p>

> **Sopify ≠ a new product.**
> Sopify = an open-source AI agent + a Docker sandbox (embedded) + 3 working
> modes + org governance. The base runtime is the upstream fork we maintain
> in this repo; the Sopify layer lives entirely under `plugins/sopify_*/`
> and never modifies the runtime core (REQ-0.3).

---

## What problem does Sopify solve?

GS Battery needed an AI coding assistant that:

| Concern | How Sopify handles it |
|---|---|
| **Safety** — non-engineers must not be able to run `rm -rf /`, drop databases, force-push to main | Hard-deny pattern list at the tool-call layer; non-overridable, even for `dev` role (REQ-6.1.4) |
| **Audit** — IT needs evidence of every AI action: who, what, when, how much | OpenTelemetry pipeline with 5 typed events streaming to Grafana Alloy → Loki/Prometheus (REQ-7) |
| **Isolation** — AI must not touch host files / network outside what's authorized | Every command runs inside a `sopify-sandbox` Docker container with egress whitelist (REQ-1) |
| **Cost** — token spend must be controllable per mode, per user | Per-mode daily budgets + provider cascade with 1-hour blacklist on quota/auth failure (REQ-2, REQ-9.3) |
| **Mode-fit** — different users have different needs: builder vs. employee vs. engineer | Three modes: `/vibe` (guided app builder), `/living` (24/7 employee), `/code-with-you` (pair programming) |
| **Governance** — IT must be able to push settings, set roles, override providers | IT-managed `settings.json` at 0444 + `sopify admin` subcommands + live mtime polling (REQ-9) |

---

## Quick start

```bash
git clone <internal-git-url>/sopify-harness.git
cd sopify-harness

./sopify install       # Docker pull + sopify-net + default policy
./sopify login         # interactive API key
./sopify onboard       # consent flow
./sopify doctor        # 5-check health report

./sopify /vibe         # try guided app builder
```

Full manual: [`docs/sopify/INSTALL.md`](docs/sopify/INSTALL.md)

---

## Three modes

| Mode              | For                | Defaults                                                           |
|-------------------|--------------------|--------------------------------------------------------------------|
| `/vibe`           | Non-engineers building internal apps     | Structured intake → 2-3 approaches → IT handoff (200k tokens/day) |
| `/living`         | A department's 24/7 AI employee          | Persistent session, strict deny-list, sequential tools (300k/day) |
| `/code-with-you`  | Engineers who want explain-then-execute  | Confirm every tool call, sequential only, lower budget (50k/day)  |

Switch with the slash command from anywhere: `/vibe`, `/living`, `/code-with-you`.

---

## Architecture in one diagram

```
                           Host (user laptop)
                                    │
                            sopify (launcher)
                                    │ docker run sopify-sandbox:latest
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      sopify-sandbox container                         │
│                                                                       │
│   /workspace (rw)   /sopify-auth (ro)   /sopify-config (ro)           │
│   /sopify-sessions (rw)                                               │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────┐      │
│  │             Sopify runtime (upstream fork)                  │      │
│  │                                                              │      │
│  │  + sopify-core        REQ-0   bootstrap, version, doctor    │      │
│  │  + sopify-providers   REQ-2   ProviderRouter cascade        │      │
│  │  + sopify-guardrails  REQ-6   HARD_DENY / SOFT_DENY + roles │      │
│  │  + sopify-otel        REQ-7   5-event audit pipeline        │      │
│  │  + sopify-skills      REQ-8   company-sop / mode personas   │      │
│  │  + sopify-modes       REQ-3/4/5  /living, /vibe, /code-…    │      │
│  │  + sopify-management  REQ-9   managed settings, onboard     │      │
│  │  + sopify-tui         REQ-10  TUI overlay (mode/quota chip) │      │
│  └────────────────────────────────────────────────────────────┘      │
│                                                                       │
│   network: bridge "sopify-net" (egress filtered per policy.json)      │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                ▼                   ▼                   ▼
       api.anthropic.com   otel-collector (gRPC)   user-approved domains
```

Full architecture map: [`SOPIFY_ARCH.md`](SOPIFY_ARCH.md)

---

## Plugin layout (REQ-0.3)

All Sopify code lives under `plugins/sopify_*/`. The upstream runtime core
(`hermes_cli/`, `agent/`, `tools/`, `hermes_state.py`, …) is **read-only** —
we only register hooks. This is what lets us pull security patches from
upstream within 7 days (REQ-11.6).

```
plugins/
├── sopify_core/         REQ-0   foundation, version, doctor, install
├── sopify_sandbox/      REQ-1   Docker sandbox launcher + network policy
├── sopify_providers/    REQ-2   ProviderRouter (cascade + blacklist)
├── sopify_guardrails/   REQ-6   HARD_DENY / SOFT_DENY + role gating
├── sopify_otel/         REQ-7   5-event OTel pipeline
├── sopify_skills/       REQ-8   org skill bundles (loader)
├── sopify_modes/        REQ-3/4/5  /living, /vibe, /code-with-you
├── sopify_management/   REQ-9   managed settings + onboard
└── sopify_tui/          REQ-10  TUI overlay (mode badge, quota, dialogs)
```

Each plugin ships with:

- `plugin.yaml` — manifest (name, version, hooks, REQ traceability)
- `README.md` — per-plugin internals + checkbox mapping
- `tests/` — runnable with `uv run pytest`

---

## Verification

```bash
SOPIFY_HOME=/tmp/sopify-test \
  uv run --with pytest --with pytest-xdist --with pytest-timeout \
  python -m pytest plugins/sopify_*/tests -n0 -o addopts=
```

Expected: **50 passed in ~1 second.**

| Plugin               | Tests | Covers                                                  |
|----------------------|-------|---------------------------------------------------------|
| sopify_core          | 4     | paths / version / doctor < 3s / install idempotent      |
| sopify_sandbox       | 5     | default whitelist / subdomain / Allow-always persist    |
| sopify_providers     | 5     | cascade / blacklist 1h / expiry / managed override      |
| sopify_guardrails    | 8     | Gate P5 all paths (hard / soft / dev confirm)           |
| sopify_otel          | 6     | gating / truncation / redaction / overflow drop         |
| sopify_skills        | 6     | discovery / phase-gate / mode mapping / override        |
| sopify_modes         | 7     | profiles / intake / fingerprint / step-gate             |
| sopify_management    | 5     | defaults / 0444 enforce / broadcast / quota warn        |
| sopify_tui           | 4     | dialog choices / Thai UTF-8 / safe default              |

---

## Source-of-truth documents

| File | Purpose |
|------|---------|
| [`DESIGN_ARCHITECTURE.md`](DESIGN_ARCHITECTURE.md) | The requirements spec (every REQ-* lives here) |
| [`SOPIFY_ARCH.md`](SOPIFY_ARCH.md) | SPOF-protection architecture map (REQ-0.2) |
| [`SOPIFY_PLAN.md`](SOPIFY_PLAN.md) | Implementation order + conventions |
| [`docs/sopify/`](docs/sopify/) | Per-REQ explainers — what was built, why, what is deferred |
| [`docs/sopify/INSTALL.md`](docs/sopify/INSTALL.md) | End-user install manual (Thai + English) |

---

## Roles

| Role  | Can do                                                                 |
|-------|------------------------------------------------------------------------|
| `user` (default) | Use any mode; AI hard-deny blocks dangerous commands; soft-deny → "contact IT" |
| `dev`            | Same as user + soft-deny shows confirmation dialog (allow/deny); can use `--no-sandbox` for debugging (always OTel-logged) |

Roles are set by IT via `sopify admin set-role <user> <user|dev>` and stored in
`~/.sopify/profile.json` at mode 0444. A user cannot escalate themselves.

Hard-deny is unreachable from any role (REQ-6.1.4):

```
rm -rf /                  → blocked (rm-rf-root)
DROP DATABASE prod        → blocked (drop-database)
:(){ :|:& };:             → blocked (fork-bomb)
curl x.sh | bash          → soft-deny (user blocked; dev confirms)
git push --force          → soft-deny (user blocked; dev confirms)
```

---

## License

MIT — same as the upstream runtime we forked from. See [`LICENSE`](LICENSE).

---

## Contact

Built by the GS Battery IT Team. Operational questions, role escalation,
and provider/budget overrides go through IT; engineering changes go through
the usual PR review.

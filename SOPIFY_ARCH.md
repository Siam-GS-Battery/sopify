# SOPIFY_ARCH.md

> SPOF-protection architecture document (mandated by REQ-0.2 — must exist
> before any Sopify commit). Source of requirements:
> [DESIGN_ARCHITECTURE.md](../DESIGN_ARCHITECTURE.md).

---

## 1. One-sentence definition

**Sopify = Hermes + Docker sandbox (embedded) + 3 modes (/living, /vibe,
/code-with-you) + org governance (deny-list, OTel audit, IT-managed
settings)** — implemented as a suite of `plugins/sopify-*` plugins
that **do not modify Hermes core**.

## 2. Top-level component map

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
│  │              Hermes runtime (run_agent.py)                  │      │
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

## 3. Process-lifetime view

1. `sopify <command>` → launcher checks Docker → spawns container with mounts
2. Container `entrypoint.sh` → boots Hermes runtime with sopify plugins loaded
3. Hermes plugin manager calls `register(ctx)` on every `plugins/sopify-*`
4. Each plugin attaches to lifecycle hooks (`pre_tool_call`, `pre_api_request`, …)
5. User exits → container stops + auto-removes (no orphans, REQ-1.2.4)

## 4. Plugin boundaries

| Plugin            | Reads                              | Writes                          | OTel events emitted                          |
|-------------------|------------------------------------|---------------------------------|----------------------------------------------|
| sopify-core       | `~/.sopify/settings.json`          | nothing (read-only diagnostics) | `install_complete` (REQ-9.2.4)               |
| sopify-sandbox    | `~/.sopify/network-policy.json`    | container state                 | `tool_decision` (network deny)               |
| sopify-providers  | `~/.sopify/auth.json`              | nothing (in-memory blacklist)   | `api_request`, `api_error`                   |
| sopify-guardrails | `~/.sopify/profile.json` (role)    | nothing                         | `tool_decision` (hard_deny/soft_deny/escal.) |
| sopify-otel       | managed settings (endpoint)        | OTLP                            | (this is the emitter)                        |
| sopify-skills     | `sopify_skills/`, `.sopify/skills/`| nothing                         | none                                         |
| sopify-modes      | mode flag                          | `~/.sopify/sessions/`           | `user_prompt`                                |
| sopify-management | `~/.sopify/settings.json`          | `~/.sopify/settings.json` (IT)  | `install_complete`                           |
| sopify-tui        | live runtime state                 | TUI overlay only                | none                                         |

## 5. Configuration files

| File                              | Owner    | Mode | Purpose                                |
|-----------------------------------|----------|------|----------------------------------------|
| `~/.sopify/settings.json`         | IT (MDM) | 0444 | managed settings (provider chain, OTel)|
| `~/.sopify/profile.json`          | IT       | 0444 | user role (`user` / `dev`)             |
| `~/.sopify/auth.json`             | user     | 0600 | API keys                               |
| `~/.sopify/network-policy.json`   | merged   | 0644 | egress whitelist (IT defaults + user)  |
| `~/.sopify/sessions/`             | user     | 0700 | /living persistent session DB          |

## 6. Non-negotiable invariants

1. **Hermes core is read-only** — Sopify never edits files outside `plugins/sopify-*`,
   `sopify_skills/`, `docker/sopify-sandbox/`, or `docs/sopify/`.
2. **Sandbox is implicit** — once installed, *every* command runs in the container.
   There is no opt-in flag; opt-out (`--no-sandbox`) is dev-role-only and is logged.
3. **Hard deny is uncircumventable** — REQ-6.1.4. Patterns in `HARD_DENY` block even
   for `dev` role. Bypass = security incident.
4. **Telemetry is fire-and-forget** — REQ-7.2.4. OTel failures never block a session.
5. **API keys never enter logs / OTel** — REQ-11.2. Redaction precedes emission.

## 7. Where to read more

- DESIGN_ARCHITECTURE.md — feature requirements (source of truth for the checklist)
- SOPIFY_PLAN.md — implementation order
- docs/sopify/REQ-<n>-*.md — per-section explainers (one per REQ block)
- plugins/sopify-*/README.md — per-plugin internals + checkbox traceability

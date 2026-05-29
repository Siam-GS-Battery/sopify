<p align="center">
  <img src="assets/icon-background-transparent.png" alt="Sopify" width="200" />
</p>

<h1 align="center">Sopify</h1>

<p align="center">
  <em>AI agent + sandbox + 3 modes + org governance.<br/>
  GS Battery's branded distribution of the Hermes AI agent.</em>
</p>

<p align="center">
  <a href="MANUAL.md">User Manual</a> ·
  <a href="SYSTEM_ARCHITECTURE.md">Architecture</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="SECURITY.md">Security</a>
</p>

---

## What it is

Sopify is a **branded fork of the [Hermes](https://github.com/NousResearch/hermes-agent) AI agent**, packaged for GS Battery with three opinionated additions:

1. **Docker sandbox by default.** Every command runs in an [`sbx`](https://docs.docker.com/sandboxes/) microVM. Org-managed network policy, egress audit, and credential mounts are applied automatically.
2. **Three working modes** for different audiences:
   - **`/vibe`** — guided app builder (non-engineer scaffolds dashboards, forms, landing pages end-to-end)
   - **`/living`** — persistent AI employee (24/7 background presence per department)
   - **`/code-with-you`** — pair-programming with explicit approval on every tool call
3. **ENCM control plane** — host-side daemon (FastAPI on `127.0.0.1:7777`) that owns network rules, audit, and reconciliation against `sandboxd`.

A web dashboard, terminal TUI, and JSON-RPC gateway all share the same agent runtime; the dashboard is the recommended UX for non-engineers.

---

## Quick start

### Install (one-liner)

```bash
curl -fsSL https://raw.githubusercontent.com/Siam-GS-Battery/sopify/main/scripts/sopify-install.sh | bash
```

The installer checks for Docker / `sbx` / `uv` / `git`, installs anything missing (via Homebrew on macOS, apt on Debian/Ubuntu), clones the repo to `~/.sopify-app`, sets up the Python venv, writes a `sopify` wrapper to `~/.local/bin`, and runs `sopify install` (Docker image build + sbx template load + network setup).

Environment overrides:

```bash
SOPIFY_REPO=https://github.com/<org>/<repo>.git \
SOPIFY_BRANCH=develop \
curl -fsSL <url>/scripts/sopify-install.sh | bash
```

### First-time API key

Open the dashboard, then add a key through the UI — `~/.hermes/.env` is mounted writable so saving from inside the sandbox just works:

```bash
sopify dashboard           # opens http://127.0.0.1:9119
```

In the browser → **Models** → **API Keys** → pick a provider (e.g. **Alibaba (Qwen Cloud)** for Qwen models, or **Anthropic** for Claude) → paste → **Save** → **Test**.

Provider keys go into `~/.hermes/.env`; Sopify's own creds live in `~/.sopify/auth.json` (mode 0600).

### Vibe Code (the flagship)

`Vibe Code` is the dashboard's guided AI-DLC flow — it scaffolds a complete web project end-to-end through chat. The current production phases are `brainstorm → planning → development` (single coding step). **PR [`feat/vibe-phase-prompts-and-supabase`](https://github.com/Siam-GS-Battery/sopify/pulls)** ships the artifact-side foundation for the upcoming 4-stage build flow: `design → database → api → verify`, with a user-approval gate between each.

When the `database-supabase` add-on is on, bring up Supabase Local before entering the database phase:

```bash
docker compose -f ~/.sopify-app/docker/supabase/docker-compose.yaml up -d
open http://127.0.0.1:54323     # Studio UI
```

---

## Features

| Surface | What it does |
|---|---|
| **Dashboard** (`sopify dashboard`) | React SPA at `127.0.0.1:9119`. Chat, Sessions, Models, Vibe Code, Files, Logs, Network, Skills, Plugins, Profiles, Config, Keys. Single Sopify theme. |
| **TUI chat** (`sopify chat`) | Terminal chat over the JSON-RPC gateway. Same agent runtime as the dashboard. |
| **`/vibe`** (`sopify /vibe`) | Guided app builder mode. Loads the `sopify-sdlc` skill (GS Battery SOP-DEV-001) and the vendored `frontend-design` skill from Anthropic. |
| **`/living`** | Persistent AI-employee mode (service-style, survives terminal close). |
| **`/code-with-you`** | Pair-programming with explicit per-tool-call approval. |
| **ENCM** (`sopify start` / `sopify rules` / `sopify audit`) | Egress network control + daily JSONL audit at `~/.sopify/encm/audit/`. |
| **Per-session dev server** | `BuildingPane` and `/panel`'s `CanvasPanel` auto-detect the agent's `npm run dev` URL from tool output; switching sessions pauses one and revives the other. |
| **Plugin system** | `~/.hermes/plugins/<name>/` — JS bundles register tab + slot components; Python modules export FastAPI routers mounted under `/api/plugins/<name>/`. |

Documentation: **[MANUAL.md](MANUAL.md)** is the user-facing reference (install, dashboard, API keys, troubleshooting, dev workflow). **[SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md)** is the file:line-cited deep dive for engineers picking the code up cold.

---

## Layout

```
sopify-harness/
├── sopify                       # host-side entry-point shim
├── hermes_cli/                  # Hermes runtime (upstream — do not edit)
├── tui_gateway/                 # JSON-RPC server bridging TUI ↔ agent
├── agent/                       # agent core (tools, conversation, providers)
├── plugins/
│   ├── sopify_core/             #   install, doctor, banner, version
│   ├── sopify_sandbox/          #   sbx launcher + network policy
│   ├── sopify_providers/        #   provider registry, .env writer, sbx-secret sync
│   ├── sopify_guardrails/       #   request/response guardrails
│   ├── sopify_otel/             #   OTel telemetry emitter
│   ├── sopify_management/       #   onboarding flow
│   ├── sopify_encm/             #   ENCM agent-side hooks
│   └── sopify_modes/            #   /vibe, /living, /code-with-you profiles
├── sopify_daemon/               # host-side ENCM FastAPI daemon (port 7777)
├── web/                         # React 19 + Vite + Tailwind 4 SPA
├── ui-tui/                      # Node TUI parent (xterm-fed PTY)
├── prompts/vibe/
│   ├── base.md                  #   general Vibe agent rules
│   ├── modes/                   #   dashboard / form-registration / landing-page / web-app
│   ├── add-ons/                 #   auth-jwt / database-supabase / dark-mode / ...
│   └── phases/                  #   design / database / api / verify (rev 2.1)
├── skills/
│   ├── sopify-sdlc/             #   GS Battery SOP-DEV-001 standards
│   └── frontend-design/         #   Anthropic-vendored design skill (rev 2.1)
├── docker/
│   ├── sopify-sandbox/          #   the sandbox image
│   └── supabase/                #   Supabase Local stack for Vibe (rev 2.1)
├── infra/sbx/sopify-kit/        # sbx kit (allowed domains + env passthrough)
└── scripts/
    └── sopify-install.sh        # curl-installable bootstrap
```

---

## Prerequisites

| Tool | Tested version | Install |
|---|---|---|
| Docker Desktop | 29.x | https://www.docker.com/products/docker-desktop |
| sbx (Docker Sandboxes) | 0.29.x | `brew install docker/tap/sbx` then `sbx login` |
| Python | 3.10+ | `brew install python@3.13` |
| `uv` | 0.5+ | bundled by the curl installer |
| Disk | ~6 GB | sopify-sandbox image (~2.5 GB) + Supabase images (~2.5 GB) |

---

## Common commands

```bash
# Daily
sopify dashboard           # web UI in the browser — recommended entry point
sopify chat                # terminal chat
sopify /vibe               # guided app builder

# Install / health
sopify install             # one-shot: Docker build + sbx template + network
sopify doctor              # auth / sandbox image / network / OTel
sopify --version

# API keys (CLI alternative to the Web UI)
sopify login               # interactive setup → ~/.sopify/auth.json
sopify env list            # list ~/.hermes/.env (lengths only)
sopify env set <provider>  # add a key
sopify env unset <provider>

# ENCM
sopify start               # host daemon (FastAPI :7777)
sopify status              # daemon + sandboxd + reconciler
sopify rules list
sopify audit
```

Full reference: **[MANUAL.md](MANUAL.md)**.

---

## Documentation map

| File | Purpose |
|---|---|
| [MANUAL.md](MANUAL.md) | User-facing reference — install, dashboard, API keys, troubleshooting |
| [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) | Engineer reference — file:line citations across the whole stack |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Hermes core architecture (upstream — do not edit per REQ-0.3) |
| [AGENTS.md](AGENTS.md) | Inventory of agent tools and skills |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Branch policy, commit style, review checklist |
| [SECURITY.md](SECURITY.md) | Disclosure policy and threat model |
| [docker/supabase/README.md](docker/supabase/README.md) | Supabase Local service map + credentials |
| [skills/frontend-design/VENDOR.md](skills/frontend-design/VENDOR.md) | Upstream source for the Anthropic-vendored design skill |

---

## License

Sopify inherits Hermes' license from `NousResearch/hermes-agent`. See [LICENSE](LICENSE) (when present in this checkout) or the upstream repo for terms. Vendored third-party skills retain their own licenses — see each `VENDOR.md`.

---

<p align="center">
  Built by GS Battery on top of the <a href="https://github.com/NousResearch/hermes-agent">Hermes</a> runtime.
</p>

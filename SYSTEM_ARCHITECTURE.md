# Sopify — System Architecture

<p align="center">
  <img src="assets/icon-background-transparent.png" alt="Sopify" width="120" />
</p>

**Status:** Audit current as of 2026-05-30 (rev 2.1). Reconstructed by reading source. Where the live system diverges from this doc, trust the source — see file:line citations on every claim.

**What's new in rev 2 (2026-05-29 — already on `main`):**
- Per-session dev server lifecycle (kill on session switch + auto revive). See [§9](#9-dev-server-lifecycle-per-session).
- Frontend `BuildingPane` port selector replaced with auto-detection from chat tool output.
- `CanvasPanel` in /panel adopts the same auto-detected URL.
- Alibaba (Qwen Cloud) provider in the API Keys registry; `env_writable` probe in the form so the UI gates Save when `~/.hermes/.env` isn't writable.
- Theme picker collapsed to a single Sopify theme.
- `~/.hermes` mounted into the sandbox as `rw` (was `:ro`) so the API Keys form can persist keys from inside the microVM.

**What's new in rev 2.1 (PR `feat/vibe-phase-prompts-and-supabase`, 2026-05-30):**
- **Vibe Code phase artifacts** — `prompts/vibe/phases/{design,database,api,verify}.md` define a 4-stage building flow (design → database → api → verify) with strict do/don't boundaries per phase. **The backend phase machine still ships the legacy `development` step**; wiring `_VIBE_BUILDING_PHASES` + new accept endpoints into `_vibe_compose_system_prompt` is the next PR.
- **`skills/frontend-design/`** — Anthropic's `frontend-design` skill vendored verbatim from `anthropics/claude-code` (plugins/frontend-design). Reserved for the design phase as the visual-quality bar (avoid Inter/Roboto generic look). `VENDOR.md` documents source URL + sync rules.
- **`docker/supabase/`** — minimal Supabase Local stack for Vibe's `database` phase. Services bound 127.0.0.1, reached from inside the sandbox via `host.docker.internal`:

  | Service | Host port | Container port | Purpose |
  |---|:-:|:-:|---|
  | postgres | 5432 | 5432 | Raw DB (`postgres` / `sopify-supabase-dev`) |
  | rest (PostgREST) | 54321 | 3000 | `VITE_SUPABASE_URL` target |
  | auth (GoTrue) | 54320 | 9999 | JWT signup / signin |
  | meta (postgres-meta) | 54322 | 8080 | Studio backend |
  | **studio** | **54323** | 3000 | Browser UI |

- Nav: "Virtual Office" → "Dashboard"; reordered ahead of "Vibe Code" in `EVERYDAY_NAV_ORDER`.

**Scope:** End-to-end picture of the running Sopify dashboard: host launcher, Docker sandbox, FastAPI dashboard, TUI gateway, React SPA, ENCM daemon, plus the supporting data model, auth chain, and recent Vibe Code work.

**Repo root:** `~/ai_engineer/gs/project-based/sopify/`
Most paths below are relative to `sopify-harness/` unless noted (`~/.hermes/`, `~/.sopify/` for runtime state).

---

## Table of contents

1. [Overview & core concepts](#1-overview--core-concepts)
2. [Process topology — host, sandbox, dashboard, gateway](#2-process-topology)
3. [Storage layout — on-disk state](#3-storage-layout)
4. [Auth & security model](#4-auth--security-model)
5. [Backend HTTP API surface](#5-backend-http-api-surface)
6. [Gateway JSON-RPC protocol](#6-gateway-jsonrpc-protocol)
7. [Frontend architecture (React SPA)](#7-frontend-architecture)
8. [Vibe Code feature — flagship AI-DLC flow](#8-vibe-code-feature)
9. [Dev server lifecycle (per-session)](#9-dev-server-lifecycle-per-session)
10. [Plugin system](#10-plugin-system)
11. [Theme & i18n](#11-theme--i18n)
12. [ENCM control plane (network policy)](#12-encm-control-plane)
13. [Dev workflow & build pipeline](#13-dev-workflow--build-pipeline)
14. [Known quirks & gotchas](#14-known-quirks--gotchas)
15. [Model selection strategy](#15-model-selection-strategy)

---

## 1. Overview & core concepts

Sopify is **GS Battery's branded fork of the Hermes AI agent**, run inside a Docker sandbox (`sbx`) with org governance overlays (ENCM = Egress Network Control Module, auth-managed providers, sbx port publishing). It is a multi-process system spanning **host** and **sandbox**:

- A user types `sopify dashboard` on the host.
- A host-side **ENCM daemon** boots (FastAPI, port `7777`) if not already running — owns network policy, audit, and reconciliation against `sandboxd`.
- The launcher delegates to **sbx** (`Docker Sandboxes`) which boots a persistent microVM-style container per cwd. Bind mounts: user cwd (rw), installed Sopify source (ro), `~/.hermes` (ro), `~/.sopify` (ro).
- Inside the container, **Hermes web_server** (FastAPI, port `9119`) starts and serves the dashboard SPA + REST + WebSocket endpoints.
- Inside the same container, a **TUI gateway** (`tui_gateway`) speaks JSON-RPC to drive the agent — spawned per chat session as a Python subprocess from a Node TUI parent.
- The host launcher **publishes ports** 9119, 5173, 4173, 3000, 4321, 8000, 8080 from container → host loopback so the user's browser + agent dev servers are reachable from outside the sandbox.

```
host browser ──HTTP──> 127.0.0.1:9119 ──sbx port-publish──> sandbox 9119 (web_server)
                                                                  │
                                                                  ├─ /api/* REST + /api/ws WS + /api/pty WS
                                                                  ├─ /preview/* iframe-friendly file server
                                                                  └─ /api/encm/* proxy ──> host 127.0.0.1:7777 (sopify_daemon)
                                                                                                  │
                                                                                                  └─ Unix socket ──> sandboxd
```

**Key concepts to know before reading the rest:**

| Concept | What it is | File:line anchor |
|---|---|---|
| `HERMES_HOME` | Hermes state root, default `~/.hermes` | [hermes_constants.py:43](sopify-harness/hermes_constants.py#L43) |
| `_FILES_ROOT` | Workspace exposed by `/api/files/*`, set to `Path.cwd().resolve()` at server start | [hermes_cli/web_server.py:4715](sopify-harness/hermes_cli/web_server.py#L4715) |
| Session token | 32-byte `secrets.token_urlsafe`, generated per process, injected into `index.html` as `window.__HERMES_SESSION_TOKEN__` | [web_server.py:90](sopify-harness/hermes_cli/web_server.py#L90), [web_server.py:3905](sopify-harness/hermes_cli/web_server.py#L3905) |
| `session_id` vs `session_key` | Gateway sid (8-char hex, in-memory) vs DB key (`YYYYMMDD_HHMMSS_xxxxxx`, durable). Conflating them broke chat resume until recent fix. | [tui_gateway/server.py:1986](sopify-harness/tui_gateway/server.py#L1986), [useChatStream.ts:52-67](sopify-harness/web/src/hooks/useChatStream.ts#L52-L67) |
| Vibe phase machine | brainstorm → requirements → planning → development → improvement → security → approve. The UI collapses to 6 visible steps. | [web_server.py:5484](sopify-harness/hermes_cli/web_server.py#L5484), [VerticalStepper.tsx:104](sopify-harness/web/src/components/vibe/VerticalStepper.tsx#L104) |

**Naming clarifications** the codebase will throw at you:

- `~/.hermes` = Hermes state. `~/.sopify` = ENCM daemon + sbx config. **Two different homes.**
- "Hermes" code is upstream (`hermes_cli/`, `agent/`, `tui_gateway/`); "Sopify" code is the GS-branded fork (`sopify`, `plugins/sopify_*/`, `sopify_daemon/`).
- `sbx` is the `Docker Sandboxes` CLI — not part of Hermes/Sopify; it's a Docker-published tool that hosts the runtime.

---

## 2. Process topology

### 2.1 Launcher chain — `sopify` script

The launcher ([sopify](sopify-harness/sopify)) is a Python script (not a wheel entrypoint) that dispatches subcommands without importing the heavy Hermes runtime upfront. Top-level commands:

| Command | Routes to | Where it runs |
|---|---|---|
| `sopify install` | `plugins.sopify_core.install.run()` | host |
| `sopify doctor` | `plugins.sopify_core.doctor.run()` | host |
| `sopify login` / `logout` / `env` | host credential management; writes `~/.hermes/.env`, `~/.sopify/auth.json` | host |
| `sopify onboard` | host welcome flow | host |
| **`sopify dashboard`** | auto-starts ENCM daemon, then `_delegate_to_hermes(["dashboard"], publish_ports=[9119, 5173, 4173, 3000, 4321, 8000, 8080])` | **inside sandbox** |
| `sopify chat` | `_delegate_to_hermes(argv)` | inside sandbox |
| `sopify /vibe` / `/living` / `/code-with-you` | mode profile activation then delegate | sandbox (scaffolded) |
| **`sopify start`** | `sopify_daemon.cli.dispatch(start)` — boots ENCM daemon | **host (foreground)** |
| `sopify stop` / `status` / `rules` / `audit` / `reconcile` / `drift` | daemon CLI sub-commands | host |

Dispatch in `main()` at [sopify:369-427](sopify-harness/sopify#L369-L427). The typo guard at [sopify:384-401](sopify-harness/sopify#L384-L401) rewrites common slips (`rule → rules`, `auditing → audit`) before falling through to the slow Hermes path.

### 2.2 Sandbox launching — `plugins/sopify_sandbox/sbx_launcher.py`

`_delegate_to_hermes` → `sbx.spawn(argv, publish_ports=…)` ([sbx_launcher.py:505-713](sopify-harness/plugins/sopify_sandbox/sbx_launcher.py#L505)) walks through:

1. **Sandbox name** = SHA1(cwd)[:10], prefixed `sopify-` ([sbx_launcher.py:112-116](sopify-harness/plugins/sopify_sandbox/sbx_launcher.py#L112)). Stable per cwd, so re-running reuses the same container.
2. **Workspace mounts** ([sbx_launcher.py:547-562](sopify-harness/plugins/sopify_sandbox/sbx_launcher.py#L547)):
   - `cwd` → same absolute path, rw (user's project).
   - `~/.sopify-app` (installed source) → same path, ro. Skipped when equal to cwd.
   - `~/.hermes` → same path, ro (`.env`, `auth.json`).
   - `~/.sopify` → same path, ro (daemon bearer token + ENCM config so dashboard's `/api/encm/*` proxy can read it).
3. **Stale sandbox check** — if existing container lacks `/usr/local/bin/sopify`, force-remove + recreate ([sbx_launcher.py:567-571](sopify-harness/plugins/sopify_sandbox/sbx_launcher.py#L567)).
4. **`_ensure_sandbox()`** runs `sbx create shell <mounts...> --name sopify-<hash> [--template sopify-sandbox:latest] [--kit infra/sbx/sopify-kit]` ([sbx_launcher.py:194-210](sopify-harness/plugins/sopify_sandbox/sbx_launcher.py#L194)). Idempotent.
5. **`_link_hermes_into_sandbox()`** symlinks mounted host `~/.hermes/{.env,auth.json}` into the sopify user's `$HOME/.hermes/` ([sbx_launcher.py:443-502](sopify-harness/plugins/sopify_sandbox/sbx_launcher.py#L443)) — needed because sbx kit schema v1 silently drops `startup:` blocks.
6. **Port-publish background thread** spawned (see §2.3).
7. **`inner_cmd`** assembled as a single `bash -lc` string ([sbx_launcher.py:638-700](sopify-harness/plugins/sopify_sandbox/sbx_launcher.py#L638)):
   - `cd` into user cwd, export `COLORTERM=truecolor`, `TERM=xterm-256color`, `HERMES_PYTHON=/opt/sopify/.venv/bin/python3`, `SOPIFY_TUI_TRACE=1`.
   - Re-apply `no_proxy`/`NO_PROXY` (constant `_AI_NO_PROXY` at [sbx_launcher.py:51-58](sopify-harness/plugins/sopify_sandbox/sbx_launcher.py#L51)) — sbx kit v1 drops the spec `env:` block.
   - Strip sentinel `ANTHROPIC_API_KEY="proxy-managed"`.
   - **Dev-mode detection** — shell globs `/Users/*/ai_engineer/*/project-based/sopify/sopify-harness/sopify`, `/home/*/sopify-harness/sopify`, etc. ([sbx_launcher.py:675-699](sopify-harness/plugins/sopify_sandbox/sbx_launcher.py#L675)). If found → exec `python $DEV_SOPIFY ...`; otherwise `/usr/local/bin/sopify ...`. There is **no `DEV_SOPIFY` env var** — only a shell-local variable inside `inner_cmd`.
8. **`sbx exec -it <sandbox> bash -lc <inner_cmd>`** — attaches PTY and blocks until exit ([sbx_launcher.py:707-711](sopify-harness/plugins/sopify_sandbox/sbx_launcher.py#L707)).

### 2.3 Port publishing — `_publish_ports_when_ready`

The publish thread ([sbx_launcher.py:270-389](sopify-harness/plugins/sopify_sandbox/sbx_launcher.py#L270)) keeps `sbx ports --publish` alive against sbx's container-reaping behavior:

- **Cadence:** every 3.0s while sandbox is running.
- **HTTP probe** for browser-open trigger: `GET http://127.0.0.1:<port>/health` then `/`, 1.5s timeout. Accepts 2xx/3xx as success and 4xx/5xx as proof-of-life (FastAPI's 401 still counts).
- **Bind host** from `_publish_bind_host()` ([sbx_launcher.py:230-249](sopify-harness/plugins/sopify_sandbox/sbx_launcher.py#L230)) — `127.0.0.1` on macOS/Linux, `0.0.0.0` on WSL (WSL2 auto-forwarding can't catch loopback ports).

`_publish_port()` ([sbx_launcher.py:392-440](sopify-harness/plugins/sopify_sandbox/sbx_launcher.py#L392)) has up-to-3 retries:
- `"already published"` → benign, return 0.
- `"no container endpoint"` → container reaped between exec; wake it with `sbx exec <name> true`, retry.

**Currently published for `sopify dashboard`** ([sopify:296-299](sopify-harness/sopify#L296-L299)):
```python
[9119, 5173, 4173, 3000, 4321, 8000, 8080]
```
Rationale: 9119 = dashboard; 5173/4173 = Vite dev/preview; 3000 = Next/CRA/Express; 4321 = Astro; 8000/8080 = generic Python/Java. Bound 127.0.0.1 so nothing leaks to LAN.

### 2.4 Inside the sandbox — `--host 0.0.0.0 --insecure --no-open`

The launcher injects these when `SOPIFY_IN_SANDBOX=1` ([sopify:280-287](sopify-harness/sopify#L280)):

- **`--host 0.0.0.0`** — default `127.0.0.1` binds to microVM loopback, which the host can't reach through sbx publish. Must bind all interfaces.
- **`--insecure`** — `start_server` refuses non-loopback binds without it ([web_server.py:5842-5848](sopify-harness/hermes_cli/web_server.py#L5842)). Safety: only the host network sees the sandbox via the explicit sbx publish.
- **`--no-open`** — no browser inside microVM; host launcher opens it via `_publish_ports_when_ready`.

### 2.5 Dashboard process — `hermes_cli/web_server.py`

`start_server()` at [web_server.py:5828-5897](sopify-harness/hermes_cli/web_server.py#L5828):
```python
uvicorn.run(app, host=host, port=port, log_level="warning", proxy_headers=False)
```
- **Default `127.0.0.1:9119`** ([web_server.py:5829-5830](sopify-harness/hermes_cli/web_server.py#L5829)).
- `proxy_headers=False` so `host_header_middleware` and WS allowlist see the real peer, not `X-Forwarded-For`.
- `app.state.bound_host` / `bound_port` stashed for middleware ([web_server.py:5859-5860](sopify-harness/hermes_cli/web_server.py#L5859)).
- Browser auto-open via daemon thread after 1.0s delay ([web_server.py:5879-5886](sopify-harness/hermes_cli/web_server.py#L5879)).
- `--tui` flag (or `HERMES_DASHBOARD_TUI=1`) sets `embedded_chat=True` → gates `/api/pty` ([web_server.py:3625-3627](sopify-harness/hermes_cli/web_server.py#L3625)).

Middleware chain (FastAPI executes in **reverse** registration order):
1. **CORS** ([web_server.py:106-111](sopify-harness/hermes_cli/web_server.py#L106)) — loopback origin regex.
2. **`host_header_middleware`** ([web_server.py:225-252](sopify-harness/hermes_cli/web_server.py#L225)) — DNS-rebinding defense.
3. **`auth_middleware`** ([web_server.py:255-268](sopify-harness/hermes_cli/web_server.py#L255)) — `/api/*` requires session token unless in `_PUBLIC_API_PATHS`.

### 2.6 TUI Gateway — `tui_gateway/server.py`

The gateway is a **separate Python subprocess**, not in-process with the web server.

**Two spawn paths:**

1. **Terminal `sopify chat`**: Node TUI parent (`ui-tui/dist/entry.js`) → `spawn(python, ['-m', 'tui_gateway.entry'], stdio: ['pipe','pipe','pipe'])` ([gatewayClient.ts:319-329](sopify-harness/ui-tui/src/gatewayClient.ts#L319)). Communication: stdio JSON-RPC.

2. **Dashboard Chat tab (`--tui`)**: `/api/pty` WS ([web_server.py:3623-3697](sopify-harness/hermes_cli/web_server.py#L3623)) → `PtyBridge.spawn()` ([pty_bridge.py:100-128](sopify-harness/hermes_cli/pty_bridge.py#L100)) → `ptyprocess.PtyProcess.spawn([node, entry.js])` → which then spawns `python -m tui_gateway.entry`. Communication: PTY-wrapped chain.

So the dashboard's Chat tab is **uvicorn → PtyProcess → Node TUI → Python gateway**.

**Transports** ([tui_gateway/entry.py:227-247](sopify-harness/tui_gateway/entry.py#L227), [tui_gateway/ws.py:116-178](sopify-harness/tui_gateway/ws.py#L116)):
- **stdio**: newline-delimited JSON; `sys.stdout` rebound to stderr so library prints don't corrupt the protocol ([tui_gateway/server.py:171-180](sopify-harness/tui_gateway/server.py#L171)).
- **websocket**: `@app.websocket("/api/ws")` accepts, emits `gateway.ready`, loops on `receive_text()`. Same `server.dispatch(req, transport)`.

A `TeeTransport` ([tui_gateway/transport.py:186-220](sopify-harness/tui_gateway/transport.py#L186)) mirrors events to two sinks (stdio + sidecar WS) when launched with `HERMES_TUI_SIDECAR_URL` — used by the dashboard PTY path so chat events also reach the dashboard sidebar via `/api/pub`.

### 2.7 At-runtime process tree

```
HOST
 ├── sopify start  (ENCM daemon, detached)                            [pid X]
 │     └── uvicorn sopify_daemon.app  127.0.0.1:7777
 │            ├── asyncio tasks: encm-reconciler / audit-ingester / retention
 │            └── httpx Unix-socket client → sandboxd.sock
 │
 └── sopify dashboard                                                  [pid Y]
        └── sbx exec -it sopify-<hash> bash -lc "<inner_cmd>"          [pid Z]
               │
               ▼  inside microVM (sopify-<hash>)
               bash → /usr/local/bin/sopify dashboard --tui --host 0.0.0.0 --insecure --no-open
                      └── python hermes_cli.main dashboard
                             └── uvicorn 0.0.0.0:9119  (web_server.app)
                                    ├── middleware: host_header, auth
                                    └── on /api/pty WS:
                                           └── PtyProcess.spawn([node ui-tui/dist/entry.js])
                                                  └── node → spawns python -m tui_gateway.entry
                                                         (stdio JSON-RPC + optional sidecar WS)

publish-port threads in pid Y: re-publish [9119, 5173, 4173, 3000, 4321, 8000, 8080] every 3s
```

### 2.8 Communication paths summary

| From | To | Channel | Crosses sandbox? |
|---|---|---|---|
| Browser | dashboard | HTTP loopback 9119 via sbx publish | YES |
| Browser SPA | `/api/*` REST | HTTP + `X-Hermes-Session-Token` header | YES |
| Browser SPA | `/api/pty` (chat tab) | WS `?token=&channel=` | YES |
| Browser SPA | `/api/ws` (gateway WS) | WS `?token=` | YES |
| Dashboard `/api/encm/*` | sopify daemon | HTTP `host.docker.internal:7777` (from sandbox) with `Authorization: Bearer <daemon-token>` | YES (sandbox → host) |
| sopify daemon | sandboxd | Unix socket via httpx | NO (host-only) |
| Node TUI parent | python tui_gateway | stdio pipes | NO (both in sandbox) |
| python tui_gateway | dashboard sidebar | optional WS to `/api/pub` set via `HERMES_TUI_SIDECAR_URL` | NO |
| Agent | LLM providers | HTTPS using `~/.hermes/.env` key; `no_proxy` bypasses sbx MITM proxy | YES (allowlisted) |
| Agent | filesystem | Bind-mounted host paths — preserves absolute paths | n/a |

---

## 3. Storage layout

### 3.1 `~/.hermes/` — Hermes state root

Resolved by `get_hermes_home()` ([hermes_constants.py:43](sopify-harness/hermes_constants.py#L43)). Env override: `HERMES_HOME`. Default `~/.hermes`.

| Path | Purpose | Source |
|---|---|---|
| `~/.hermes/state.db` | **SQLite** (sessions, messages, FTS, kanban, telegram bindings, etc.) | [hermes_state.py:34](sopify-harness/hermes_state.py#L34) |
| `~/.hermes/logs/` | Action + agent logs | [web_server.py:675](sopify-harness/hermes_cli/web_server.py#L675) |
| `~/.hermes/logs/gateway-restart.log`, `hermes-update.log`, `preview-server.log` | Action transcripts | [web_server.py:678-681](sopify-harness/hermes_cli/web_server.py#L678) |
| `~/.hermes/vibe-projects/<name>/` | **Vibe Code projects** — `project.json` + theme starter + `REQUIREMENTS.md` + `PLANNING.md` + `SECURITY_REVIEW.md` | [web_server.py:5282](sopify-harness/hermes_cli/web_server.py#L5282) |
| `~/.hermes/dashboard-themes/*.yaml` | User-defined themes | [web_server.py:4204](sopify-harness/hermes_cli/web_server.py#L4204) |
| `~/.hermes/plugins/` | User-installed agent plugins | [web_server.py:4296](sopify-harness/hermes_cli/web_server.py#L4296) |
| `~/.hermes/.env` | `OPTIONAL_ENV_VARS` + provider API keys | via `get_env_path()` |
| `~/.hermes/.anthropic_oauth.json` | Hermes-managed Anthropic PKCE credentials | [web_server.py:1696-1709](sopify-harness/hermes_cli/web_server.py#L1696) |
| `~/.hermes/images/clip_*.png` | TUI clipboard paste images | [tui_gateway/server.py:3566-3571](sopify-harness/tui_gateway/server.py#L3566) |
| `~/.hermes/sessions/` | On-disk transcript files (deleted alongside DB row) | [tui_gateway/server.py:2348-2350](sopify-harness/tui_gateway/server.py#L2348) |
| `~/.hermes/active_profile` | Active profile marker (when multi-profile) | [hermes_constants.py:74-80](sopify-harness/hermes_constants.py#L74) |

### 3.2 `~/.sopify/` — ENCM daemon home

Defined in [sopify_daemon/paths.py](sopify-harness/sopify_daemon/paths.py).

| Path | Purpose | Source |
|---|---|---|
| `~/.sopify/config.yaml` | Daemon bearer token + bind/port | [paths.py:80](sopify-harness/sopify_daemon/paths.py#L80) |
| `~/.sopify/daemon.pid` | Daemon PID file (`sopify stop` reads this) | [paths.py:84-87](sopify-harness/sopify_daemon/paths.py#L84) |
| `~/.sopify/daemon.log` | Daemon stdout/stderr (via `sopify start` redirect) | [sopify:215-226](sopify-harness/sopify#L215) |
| `~/.sopify/encm/rules/global/<name>.yaml` | Global ENCM rules | [paths.py:52](sopify-harness/sopify_daemon/paths.py#L52) |
| `~/.sopify/encm/rules/sandboxes/<sandbox-id>/<name>.yaml` | Per-sandbox rules | [paths.py:56](sopify-harness/sopify_daemon/paths.py#L56) |
| `~/.sopify/encm/audit/YYYY-MM-DD.jsonl` | Daily JSONL audit log | [paths.py:60](sopify-harness/sopify_daemon/paths.py#L60) |
| `~/.sopify/encm/audit/archive/` | Compressed older audit files | [paths.py:64](sopify-harness/sopify_daemon/paths.py#L64) |
| `~/.sopify/encm/.state/sync.yaml{,.lock}` | Reconciler-owned sync state | [paths.py:68-77](sopify-harness/sopify_daemon/paths.py#L68) |

Override roots via `SOPIFY_ENCM_ROOT`, `SOPIFY_CONFIG_DIR`.

### 3.3 `~/.sopify-app/` — installed source symlink

`~/.sopify-app` is a **symlink** to a clone of the repo (created by the installer). The `sopify` binary at `~/.local/bin/sopify` is a symlink to `~/.sopify-app/sopify`. `realpath` resolution at [sopify:21-23](sopify-harness/sopify#L21-L23) makes `ROOT` resolve correctly.

In dev mode the symlink is replaced with one pointing to the active repo, so edits to the source take effect immediately.

### 3.4 Workspace root — `_FILES_ROOT`

`_FILES_ROOT = Path.cwd().resolve()` ([web_server.py:4715](sopify-harness/hermes_cli/web_server.py#L4715)) — captured once at server import. Whatever directory `sopify dashboard` was launched from is what the dashboard's `/api/files/*` endpoints see.

Guard: `_files_safe_path` strips leading slashes, resolves the candidate, and rejects anything not under `_FILES_ROOT` — `.resolve()` follows symlinks so a symlink to `~/.ssh` is rejected ([web_server.py:4722-4732](sopify-harness/hermes_cli/web_server.py#L4722)).

### 3.5 Sessions database

**File:** `~/.hermes/state.db` (SQLite, WAL mode with DELETE fallback for NFS/SMB).
**Schema version:** 12 ([hermes_state.py:36](sopify-harness/hermes_state.py#L36)).

`sessions` table ([hermes_state.py:190-222](sopify-harness/hermes_state.py#L190)) — key columns:

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | Format `YYYYMMDD_HHMMSS_xxxxxx` where `xxxxxx = uuid.uuid4().hex[:6]` — see `_new_session_key()` at [tui_gateway/server.py:1986-1987](sopify-harness/tui_gateway/server.py#L1986) |
| `source` | TEXT NOT NULL | Surface tag: `tui`, `cli`, `tool`, platform names. `tool` filtered out of user-facing lists. |
| `parent_session_id` | TEXT FK→sessions(id) | Branching / compression-split chain |
| `started_at`, `ended_at` | REAL | epoch seconds |
| `end_reason` | TEXT | `tui_close`, `compression`, etc. |
| `model`, `model_config`, `system_prompt` | TEXT | snapshot |
| `input_tokens`, `output_tokens`, `cache_*`, `reasoning_tokens` | INTEGER | usage |
| `estimated_cost_usd`, `actual_cost_usd` | REAL | |
| `title` | TEXT | mutable via `set_session_title` |
| `handoff_*` | TEXT | platform handoff machinery |

`messages` table ([hermes_state.py:224-241](sopify-harness/hermes_state.py#L224)) — `id`, `session_id` FK, `role`, `content` (may be JSON for multimodal), `tool_call_id`, `tool_calls` (JSON), `tool_name`, `timestamp`, `token_count`, `finish_reason`, `reasoning*`, `codex_*` (OpenAI Codex replay), `platform_message_id` (yuanbao/telegram/etc.).

FTS:
- `messages_fts` (unicode61) — content + tool_name + tool_calls, kept in sync via 3 triggers ([hermes_state.py:254-277](sopify-harness/hermes_state.py#L254)).
- `messages_fts_trigram` (`tokenize='trigram'`) — CJK substring search ([hermes_state.py:283-307](sopify-harness/hermes_state.py#L283)).

`include_ancestors=True` (used by session.resume display path) walks `parent_session_id` upward with a 100-step cycle guard, then SELECT messages from the full chain ordered by message id ascending. See `_session_lineage_root_to_tip` at [hermes_state.py:1989-2009](sopify-harness/hermes_state.py#L1989).

---

## 4. Auth & security model

### 4.1 Three carriers of the session token

The `_SESSION_TOKEN = secrets.token_urlsafe(32)` ([web_server.py:90](sopify-harness/hermes_cli/web_server.py#L90)) is generated once at process start and dies with it. Three transport mechanisms, all checked via `hmac.compare_digest`:

1. **Header `X-Hermes-Session-Token`** — primary for REST. Fallback: `Authorization: Bearer <token>` for backward compat ([web_server.py:144-161](sopify-harness/hermes_cli/web_server.py#L144)).
2. **Query `?_token=…`** — for `<img>` / `<a>` / iframe top-level navigations (browsers strip custom headers on subresource loads). [web_server.py:129-141](sopify-harness/hermes_cli/web_server.py#L129).
3. **Cookie `hermes_preview`** — set by `/preview/{path}` and `/preview/vibe/{name}` **only** after a header- or query-authenticated top-level navigation. Path-scoped `/preview`, `httponly=True`, `samesite=strict`. The cookie carries the **same** `_SESSION_TOKEN` value (delivery channel only, not separate credential).

The middleware itself only checks header OR query. **Cookie acceptance is a per-handler decision** in `/preview/*` paths (which live outside `/api/`).

### 4.2 Token injection into SPA

`mount_spa._serve_index` rewrites `index.html` on every serve ([web_server.py:3897-3923](sopify-harness/hermes_cli/web_server.py#L3897)):
```html
<script>window.__HERMES_SESSION_TOKEN__="...";
window.__HERMES_DASHBOARD_EMBEDDED_CHAT__=true|false;
window.__HERMES_BASE_PATH__="<prefix>";</script>
```
Served with `Cache-Control: no-store` so stale tokens don't leak.

### 4.3 DNS-rebinding defense (GHSA-ppp5-vxwm-4cf7)

`host_header_middleware` ([web_server.py:225-252](sopify-harness/hermes_cli/web_server.py#L225)) reads `app.state.bound_host` and rejects any request whose `Host` header doesn't match.

`_is_accepted_host` ([web_server.py:181-222](sopify-harness/hermes_cli/web_server.py#L181)):
- Strips port and IPv6 brackets.
- `bound_host ∈ {0.0.0.0, ::}` (the `--insecure` opt-in) → accept anything.
- Loopback bind → accept any of `127.0.0.1` / `localhost` / `::1`.
- Otherwise → exact host match.

Failure: `400 Invalid Host header`.

### 4.4 Public allowlist

```python
_PUBLIC_API_PATHS = frozenset({
    "/api/status",
    "/api/config/defaults",
    "/api/config/schema",
    "/api/model/info",
    "/api/dashboard/themes",
    "/api/dashboard/plugins",
    "/api/dashboard/plugins/rescan",
})
```
([web_server.py:118-126](sopify-harness/hermes_cli/web_server.py#L118)). Everything else under `/api/` is token-gated.

### 4.5 Layered checks

- **Middleware** = floor (everything `/api/*` not in the allowlist).
- **`_require_token(request)` inline** = ceiling — adds an explicit call inside the handler for sensitive endpoints (parity, rate-limit prep, audit).
- **Reveal endpoint** has additional rate limit: `_REVEAL_MAX_PER_WINDOW = 5` over `_REVEAL_WINDOW_SECONDS = 30` ([web_server.py:97-100](sopify-harness/hermes_cli/web_server.py#L97)).

### 4.6 CORS, loopback, and WS

CORS regex `^https?://(localhost|127\.0\.0\.1)(:\d+)?$` ([web_server.py:106-111](sopify-harness/hermes_cli/web_server.py#L106)). No `allow_credentials`.

`start_server` ([web_server.py:5828-5897](sopify-harness/hermes_cli/web_server.py#L5828)) refuses non-loopback binds without `allow_public=True` (the `--insecure` flag). `proxy_headers=False` so `X-Forwarded-For` is ignored.

WS loopback gate: `_ws_client_is_allowed` accepts `{127.0.0.1, ::1, localhost, testclient}` ([web_server.py:3522-3533](sopify-harness/hermes_cli/web_server.py#L3522)).

---

## 5. Backend HTTP API surface

The dashboard backend defines **98 explicit route decorators** + ENCM proxy catch-all + plugin router mounts. Source: [hermes_cli/web_server.py](sopify-harness/hermes_cli/web_server.py) (5,897 LOC).

### 5.1 Status / actions

| Method | Path | Purpose | Auth | Anchor |
|---|---|---|---|---|
| GET | `/api/status` | Version, gateway PID/state, active session count | **public** | [#L646](sopify-harness/hermes_cli/web_server.py#L646) |
| POST | `/api/gateway/restart` | Detached `hermes gateway restart` | token | [#L738](sopify-harness/hermes_cli/web_server.py#L738) |
| POST | `/api/hermes/update` | Detached `hermes update` | token | [#L753](sopify-harness/hermes_cli/web_server.py#L753) |
| GET | `/api/actions/{name}/status` | Tail action log; report running/exit_code | token | [#L768](sopify-harness/hermes_cli/web_server.py#L768) |

### 5.2 Sessions / chat

| Method | Path | Purpose | Anchor |
|---|---|---|---|
| GET | `/api/sessions` | Paginated list with `is_active` | [#L797](sopify-harness/hermes_cli/web_server.py#L797) |
| GET | `/api/sessions/search` | FTS5 across messages, auto-`*` suffix | [#L819](sopify-harness/hermes_cli/web_server.py#L819) |
| GET | `/api/sessions/{id}` | Single row, resolves prefix | [#L2657](sopify-harness/hermes_cli/web_server.py#L2657) |
| GET | `/api/sessions/{id}/latest-descendant` | Walk `parent_session_id` to newest leaf | [#L2672](sopify-harness/hermes_cli/web_server.py#L2672) |
| GET | `/api/sessions/{id}/messages` | Raw message rows | [#L2684](sopify-harness/hermes_cli/web_server.py#L2684) |
| DELETE | `/api/sessions/{id}` | Delete session | [#L2698](sopify-harness/hermes_cli/web_server.py#L2698) |

### 5.3 Config / env

| Method | Path | Purpose | Auth | Anchor |
|---|---|---|---|---|
| GET | `/api/config` | Effective normalised config | token | [#L884](sopify-harness/hermes_cli/web_server.py#L884) |
| GET | `/api/config/defaults` | `DEFAULT_CONFIG` | **public** | [#L891](sopify-harness/hermes_cli/web_server.py#L891) |
| GET | `/api/config/schema` | Schema + category order | **public** | [#L896](sopify-harness/hermes_cli/web_server.py#L896) |
| PUT | `/api/config` | Save (denormalises model dict) | token | [#L1211](sopify-harness/hermes_cli/web_server.py#L1211) |
| GET/PUT | `/api/config/raw` | Raw YAML editor | token | [#L3290-3298](sopify-harness/hermes_cli/web_server.py#L3290) |
| GET | `/api/env` | List `OPTIONAL_ENV_VARS` with redacted values | token | [#L1221](sopify-harness/hermes_cli/web_server.py#L1221) |
| PUT | `/api/env` | Save one value | token | [#L1240](sopify-harness/hermes_cli/web_server.py#L1240) |
| DELETE | `/api/env` | Remove one value | token | [#L1250](sopify-harness/hermes_cli/web_server.py#L1250) |
| POST | `/api/env/reveal` | Return real value (rate-limited 5/30s, audit-logged) | token + reveal | [#L1264](sopify-harness/hermes_cli/web_server.py#L1264) |

### 5.4 Models / providers

| Method | Path | Purpose | Auth | Anchor |
|---|---|---|---|---|
| GET | `/api/model/info` | Resolved model metadata | **public** | [#L911](sopify-harness/hermes_cli/web_server.py#L911) |
| GET | `/api/model/options` | Authenticated providers + curated models | token | [#L1009](sopify-harness/hermes_cli/web_server.py#L1009) |
| GET | `/api/model/auxiliary` | Aux task assignments | token | [#L996](sopify-harness/hermes_cli/web_server.py#L996) |
| POST | `/api/model/set` | `ModelAssignment{scope, provider, model, task}` | token | [#L1071](sopify-harness/hermes_cli/web_server.py#L1071) |

Auxiliary slots ([web_server.py:996](sopify-harness/hermes_cli/web_server.py#L996)): vision, web_extract, compression, session_search, skills_hub, approval, mcp, title_generation, curator.

OAuth providers ([web_server.py:1427](sopify-harness/hermes_cli/web_server.py#L1427)) — anthropic, claude-code, nous, openai-codex, qwen-oauth, minimax-oauth — accessed via `/api/providers/oauth/*` endpoints.

Sopify-specific API key endpoints — `/api/providers/api-key{,/{provider_id},/test/{provider_id}}` — use the registry from `plugins.sopify_providers` ([web_server.py:2385-2393](sopify-harness/hermes_cli/web_server.py#L2385)) and sync to sbx secret store when `sync_to_sbx_secret=True`.

**Which models to expose / use as defaults** is a policy question separate from the wire protocol above. See [§15 Model selection strategy](#15-model-selection-strategy) and the standalone [MODEL_SELECTION.md](sopify-harness/MODEL_SELECTION.md) for the per-use-case mapping, cost rationale, and proposed picker order.

### 5.5 Cron, profiles, skills, tools, logs, analytics

| Group | Endpoints | Reference |
|---|---|---|
| **Cron** | `/api/cron/jobs[/...]` — list, create, get, update, pause, resume, trigger, delete | [#L2864-2953](sopify-harness/hermes_cli/web_server.py#L2864) |
| **Profiles** | `/api/profiles[/{name}/...]` — list, create, rename, delete, soul read/write, setup-command, open-terminal | [#L3059-3210](sopify-harness/hermes_cli/web_server.py#L3059) |
| **Skills** | GET `/api/skills`, PUT `/api/skills/toggle` | [#L3224-3236](sopify-harness/hermes_cli/web_server.py#L3224) |
| **Tools** | GET `/api/tools/toolsets` | [#L3249](sopify-harness/hermes_cli/web_server.py#L3249) |
| **Logs** | GET `/api/logs` — query `file, lines, level, component, search` | [#L2715](sopify-harness/hermes_cli/web_server.py#L2715) |
| **Analytics** | GET `/api/analytics/usage` (daily) + `/api/analytics/models` (per-model) | [#L3315-3384](sopify-harness/hermes_cli/web_server.py#L3315) |

### 5.6 WebSockets

All four require `?token=` (browsers can't set headers on WS upgrade) AND dashboard started with `--tui` / `HERMES_DASHBOARD_TUI=1`.

| Path | Purpose | Anchor |
|---|---|---|
| `/api/pty` | PTY-over-WS bridge that spawns `hermes --tui` | [#L3623](sopify-harness/hermes_cli/web_server.py#L3623) |
| `/api/ws` | Gateway JSON-RPC bridge → `tui_gateway.ws.handle_ws` | [#L3744](sopify-harness/hermes_cli/web_server.py#L3744) |
| `/api/pub` | PTY-side publisher → channel fan-out | [#L3776](sopify-harness/hermes_cli/web_server.py#L3776) |
| `/api/events` | Subscriber on a publish channel | [#L3805](sopify-harness/hermes_cli/web_server.py#L3805) |

### 5.7 Dashboard themes & plugins

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/api/dashboard/themes` | Built-ins + user `~/.hermes/dashboard-themes/*.yaml` | **public** |
| PUT | `/api/dashboard/theme` | Set active theme | token |
| GET | `/api/dashboard/plugins` | Discovered plugins (excludes hidden) | **public** |
| GET | `/api/dashboard/plugins/rescan` | Force re-scan | **public** |
| GET | `/api/dashboard/plugins/hub` | Merged agent + dashboard plugin metadata | token + reveal |
| POST | `/api/dashboard/agent-plugins/{install,...}` | Install / enable / disable / update / remove | token + reveal |
| GET | `/dashboard-plugins/{name}/{file_path}` | Serve plugin static asset (outside `/api/`) | none — relies on host header + path traversal guards |

### 5.8 Files & preview

`_FILES_ROOT = Path.cwd().resolve()` ([#L4715](sopify-harness/hermes_cli/web_server.py#L4715)).

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/api/files` | List dir | token |
| GET | `/api/files/read` | Read text (5 MB cap, binary detection) | token |
| GET | `/api/files/download` | Stream as attachment | token |
| POST | `/api/files/upload` | Multipart upload | token + reveal |
| POST | `/api/files/rename` | Move/rename | token + reveal |
| POST | `/api/files/mkdir` | Create dir | token + reveal |
| DELETE | `/api/files` | Recursive delete | token + reveal |
| GET | `/preview/{path:path}` | Inline workspace file for Canvas iframe (sets `hermes_preview` cookie, supports `?_inspect=1` JS injection) | cookie/qs |

**Preview-server** (dev-server spawner, allow-listed commands at [#L4983](sopify-harness/hermes_cli/web_server.py#L4983)):
- `POST /api/preview-server/start` — spawn `npm run dev` etc.
- `GET /api/preview-server/status` — running + URL + log tail
- `POST /api/preview-server/stop` — SIGTERM process group

### 5.9 Vibe Code endpoints

Constants: `_VIBE_EXAMPLES_DIR = PROJECT_ROOT/"example"`, `_VIBE_PROJECTS_ROOT = ~/.hermes/vibe-projects`, `_VIBE_PROMPTS_DIR = PROJECT_ROOT/"prompts"/"vibe"` ([#L5281-5283](sopify-harness/hermes_cli/web_server.py#L5281)).

| Method | Path | Purpose | Anchor |
|---|---|---|---|
| GET | `/api/vibe/examples` | List built-in modes + thumbnails | [#L5318](sopify-harness/hermes_cli/web_server.py#L5318) |
| GET | `/api/vibe/examples/{name}/image.png` | Mode thumbnail (accepts `?_token=`) | [#L5337](sopify-harness/hermes_cli/web_server.py#L5337) |
| GET | `/preview/vibe/{name}[/{path:path}]` | Serve project file for iframe; resolves directory → `index.html` or first `.html` | [#L5354-5400](sopify-harness/hermes_cli/web_server.py#L5354) |
| POST | `/api/vibe/projects` | Create project + scaffold theme starter | [#L5420](sopify-harness/hermes_cli/web_server.py#L5420) |
| GET | `/api/vibe/projects` | List projects | [#L5527](sopify-harness/hermes_cli/web_server.py#L5527) |
| GET | `/api/vibe/projects/{name}` | Marker + artifact contents | [#L5560](sopify-harness/hermes_cli/web_server.py#L5560) |
| GET | `/api/vibe/projects/{name}/system-prompt` | Composed system prompt | [#L5611](sopify-harness/hermes_cli/web_server.py#L5611) |
| PATCH | `/api/vibe/projects/{name}` | Mutate marker (summary/session_id/phase) | [#L5628](sopify-harness/hermes_cli/web_server.py#L5628) |
| POST | `/api/vibe/projects/{name}/requirements` | Write `REQUIREMENTS.md`, phase→requirements | [#L5650](sopify-harness/hermes_cli/web_server.py#L5650) |
| POST | `/api/vibe/projects/{name}/planning` | Write `PLANNING.md`, phase→development | [#L5676](sopify-harness/hermes_cli/web_server.py#L5676) |
| POST | `/api/vibe/projects/{name}/security-review` | Write `SECURITY_REVIEW.md` (stub) | [#L5694](sopify-harness/hermes_cli/web_server.py#L5694) |
| DELETE | `/api/vibe/projects/{name}` | `shutil.rmtree(project_dir)` | [#L5731](sopify-harness/hermes_cli/web_server.py#L5731) |

### 5.10 ENCM proxy + plugin mount

| Method | Path | Purpose |
|---|---|---|
| ANY | `/api/encm/{path:path}` | Forward to `http://127.0.0.1:7777/api/v1/<path>` with server-side bearer | [#L5752](sopify-harness/hermes_cli/web_server.py#L5752) |
| (mounted) | `/api/plugins/<name>/...` | Routers exported from plugin Python files; inherit middleware auth | [#L5779-5823](sopify-harness/hermes_cli/web_server.py#L5779) |

### 5.11 Pydantic request models

22 BaseModel classes total. Notable for Vibe Code:

```python
class VibeProjectCreate(BaseModel):           # POST /api/vibe/projects
    name: str
    mode: str
    add_ons: List[str] = []

class VibeProjectPatch(BaseModel):            # PATCH /api/vibe/projects/{name}
    summary: Optional[str] = None
    session_id: Optional[str] = None
    phase: Optional[str] = None

class VibeRequirementsAccept(BaseModel):      # POST .../requirements
    content: str

class VibePlanningAccept(BaseModel):          # POST .../planning
    content: str
```
[web_server.py:5312-5672](sopify-harness/hermes_cli/web_server.py#L5312-L5672).

---

## 6. Gateway JSON-RPC protocol

### 6.1 60+ `@method` registrations

Decorator at [tui_gateway/server.py:437](sopify-harness/tui_gateway/server.py#L437). Highlights by domain:

**Session lifecycle** — `session.create`, `session.list`, `session.most_recent`, `session.resume`, `session.delete`, `session.title`, `session.usage`, `session.status`, `session.history`, `session.undo`, `session.compress`, `session.save`, `session.close`, `session.branch`, `session.interrupt`, `session.steer`.

**Prompt + input** — `prompt.submit`, `prompt.background`, `clipboard.paste`, `image.attach`, `input.detect_drop`, `terminal.resize`.

**Approval / clarify** — `clarify.respond`, `sudo.respond`, `secret.respond`, `approval.respond`.

**Config / setup** — `config.set`, `config.get`, `config.show`, `setup.status`, `reload.mcp`, `reload.env`, `commands.catalog`.

**Tab completion** — `complete.path`, `complete.slash`, `paste.collapse`.

**Tools / skills** — `tools.list`, `tools.show`, `tools.configure`, `toolsets.list`, `agents.list`, `skills.manage`, `skills.reload`, `plugins.list`.

**Model picker** — `model.options`, `model.save_key`, `model.disconnect`.

**Slash / cli** — `slash.exec`, `cli.exec`, `command.resolve`, `command.dispatch`.

**Voice** — `voice.toggle`, `voice.record`, `voice.tts`.

**Rollback / spawn-tree** — `rollback.list`, `rollback.restore`, `rollback.diff`, `spawn_tree.save`, `spawn_tree.list`, `spawn_tree.load`, `subagent.interrupt`, `delegation.status`, `delegation.pause`.

**Misc** — `insights.get`, `browser.manage`, `cron.manage`, `shell.exec`, `process.stop`.

Async dispatch: a frozenset of "long handlers" at [tui_gateway/server.py:146-157](sopify-harness/tui_gateway/server.py#L146) (`slash.exec, cli.exec, shell.exec, session.resume, session.branch, session.compress, skills.manage, browser.manage`) routes to a `ThreadPoolExecutor(max_workers=4)` so blocking handlers don't starve interrupt/approval RPCs.

### 6.2 `session_id` vs `session_key` — the resume bug

Two distinct identifiers exposed in both `session.create` and `session.resume` responses ([tui_gateway/server.py:2157-2176](sopify-harness/tui_gateway/server.py#L2157), [#L2301-2314](sopify-harness/tui_gateway/server.py#L2301)):

| Field | Format | Lifetime | Used for |
|---|---|---|---|
| `session_id` | `uuid.uuid4().hex[:8]` — 8-char hex | In-memory only, dies with gateway process | Routing JSON-RPC requests to the right in-flight agent (key into `_sessions` dict) |
| `session_key` | `_new_session_key()` → `20260529_153012_a1b2c3` | Persists across process restarts (DB row) | Durable id callers persist for `session.resume(session_id=<key>)` |

**Important historical bug:** the frontend's `useChatStream` originally stored the **gateway sid** as `project.session_id`, then on reload called `session.resume({session_id: <gateway sid>})` — which fails with `4007 "session not found"` because gateway sid was never written to the DB.

**Fix** (May 2026): the gateway now returns `session_key` alongside `session_id` in both create and resume responses; the frontend tracks them separately and persists `sessionKey` for resume. See [useChatStream.ts:52-67](sopify-harness/web/src/hooks/useChatStream.ts#L52-L67) and [vibe/ProjectView.tsx:174-182](sopify-harness/web/src/components/vibe/ProjectView.tsx#L174-L182).

Compression rotation: when `AIAgent._compress_context` mints a new continuation session row, the gateway re-anchors `session["session_key"]` to the new id via `_sync_session_key_after_compress` ([tui_gateway/server.py:1212-1277](sopify-harness/tui_gateway/server.py#L1212)). The 8-char in-memory `sid` stays the same.

### 6.3 `prompt.submit` event stream

`prompt.submit` ([tui_gateway/server.py:3031-3062](sopify-harness/tui_gateway/server.py#L3031)) acquires `session["history_lock"]` (returns `4009 "session busy"` if already running), spawns a daemon thread, returns `{"status": "streaming"}` immediately. Events emitted to the transport in chronological order per turn:

| Event | Source | Purpose |
|---|---|---|
| `gateway.ready` | once at connection | client may emit RPCs |
| `message.start` | [#L3171](sopify-harness/tui_gateway/server.py#L3171) | turn begins; clear renderer |
| `thinking.delta` | [#L1662](sopify-harness/tui_gateway/server.py#L1662) | reasoning stream (reasoning models) |
| `tool.start` | [#L1528](sopify-harness/tui_gateway/server.py#L1528) | per tool invocation |
| `tool.progress` | [#L1584](sopify-harness/tui_gateway/server.py#L1584) | incremental progress payload |
| `tool.complete` | [#L1570](sopify-harness/tui_gateway/server.py#L1570) | payload: duration, inline_diff, summary |
| `message.delta` | [#L3279](sopify-harness/tui_gateway/server.py#L3279) | each token from `agent.run_conversation` |
| `message.complete` | [#L3359](sopify-harness/tui_gateway/server.py#L3359) | final payload — full text + metadata |
| `status.update` | [#L3095](sopify-harness/tui_gateway/server.py#L3095) | process-registry notifications between turns |
| `error` | [#L3047](sopify-harness/tui_gateway/server.py#L3047) | agent init failure or context-injection refusal |

### 6.4 Image attachment flow

Per-session state in `_sessions[sid]`:
- `attached_images: list[str]` — absolute paths queued for next prompt.
- `image_counter: int` — monotonic per session for clipboard disambiguation.

Add paths via:
- `clipboard.paste` — bumps counter, saves to `~/.hermes/images/clip_*.png`.
- `image.attach` — validates extension, appends.
- `input.detect_drop` — parses drag-drop string, appends.

Consume on `prompt.submit`: snapshot `attached_images`, clear, call `_enrich_with_attached_images(prompt, images)` ([tui_gateway/server.py:3168-3273](sopify-harness/tui_gateway/server.py#L3168)).

---

## 7. Frontend architecture

The dashboard is a **Vite + React 19** SPA at `sopify-harness/web/`. Built into `sopify-harness/hermes_cli/web_dist/` and served by the FastAPI server.

### 7.1 Build & dev setup

[web/package.json](sopify-harness/web/package.json) declares `"sopify-dashboard"` (private, ESM). Scripts: `dev` (Vite), `build` (`vite build`), `type-check` (`tsc -b`), `lint`, `preview`.

Key deps: React 19.2, `react-router-dom@^7.14.1`, **`@nous-research/ui@^0.14.2`** (published npm tarball, NOT a local symlink in this checkout), Tailwind v4 via `@tailwindcss/vite`, Lucide icons, Framer Motion, GSAP, Leva, R3F + Three, Observable Plot, xterm bundle.

**Vite config** ([web/vite.config.ts](sopify-harness/web/vite.config.ts)):
- `BACKEND = process.env.HERMES_DASHBOARD_URL ?? "http://127.0.0.1:9119"`.
- **`hermesDevToken()` plugin** ([#L18-L65](sopify-harness/web/vite.config.ts#L18)) — `apply: "serve"` only. On every `transformIndexHtml`, fetches the running dashboard's index.html, scrapes `window.__HERMES_SESSION_TOKEN__` and `__HERMES_DASHBOARD_EMBEDDED_CHAT__`, re-injects into dev HTML head. Without this, `/api/*` calls in dev would 401.
- Alias `@` → `./src`.
- `dedupe` list: react, react-dom, @react-three/fiber, @observablehq/plot, three, leva, gsap.
- `build.outDir = "../hermes_cli/web_dist"` with `emptyOutDir: true`.
- `server.proxy` rewrites `/api` (WS-enabled) and `/dashboard-plugins/*` to BACKEND.

**Recent npm gotcha**: `@rollup/rollup-darwin-arm64` optional dep can be missing after `npm i` on a Mac if workspace-hoisting is involved. Workaround: `npm i --no-save @rollup/rollup-darwin-arm64@<rollup-version>` before `npm run build`.

### 7.2 App.tsx structure

**Routing** ([App.tsx:118-136](sopify-harness/web/src/App.tsx#L118)):
```typescript
const BUILTIN_ROUTES_CORE: Record<string, ComponentType> = {
  "/": RootRedirect,            // → /sessions
  "/vibe-code": VibeCodePage,
  "/panel": PanelPage,
  "/sessions": SessionsPage,
  "/files": FilesPage,
  "/virtual-office": VirtualOfficePage,
  "/analytics": AnalyticsPage,
  "/models": ModelsPage,
  "/logs": LogsPage,
  "/cron": CronPage,
  "/network": NetworkPage,
  "/skills": SkillsPage,
  "/plugins": PluginsPage,
  "/profiles": ProfilesPage,
  "/config": ConfigPage,
  "/env": EnvPage,
  "/docs": DocsPage,
};
```

`/chat` is **NOT** in this map — it's a `ChatRouteSink` placeholder ([App.tsx:142-144](sopify-harness/web/src/App.tsx#L142)). The real `<ChatPage />` is mounted persistently outside `<Routes>` ([App.tsx:769-795](sopify-harness/web/src/App.tsx#L769)) so the PTY, WebSocket and xterm instance survive tab switches — a `display:none` class hides it without unmounting.

**Nav model** ([App.tsx:146-199](sopify-harness/web/src/App.tsx#L146)) — full ordered list with icons. Plugin nav items inserted by `buildNavItems(builtIn, manifests)` ([#L230-263](sopify-harness/web/src/App.tsx#L230)) supporting `position: "end" | "after:<seg>" | "before:<seg>"`.

**Two nav groups** — Everyday vs Configure ([App.tsx:279-299](sopify-harness/web/src/App.tsx#L279)):
- `EVERYDAY_NAV_ORDER` = `[/vibe-code, /virtual-office, /panel, /sessions, /files, /analytics]`.
- `CONFIGURE_NAV_ORDER` = `[/chat, /network, /models, /logs, /skills, /plugins, /profiles, /config, /env, /kanban, /cron]`.
- `partitionSidebarNav` ([#L301-320](sopify-harness/web/src/App.tsx#L301)) is authoritative — any leftover plugin tabs fall into the **Configure** group.

**Route-shape predicates** ([App.tsx:412-419](sopify-harness/web/src/App.tsx#L412)):
- `isDocsRoute` — keeps iframe flex-stretched.
- `isChatRoute` — toggles persistent ChatPage host's `hidden` class.
- `isPanelRoute` — chat-plus-canvas split layout.
- **`isVibeCodeRoute`** (May 2026 addition) — gives Vibe Code the same height-constrained layout as `/chat` and `/panel`, so its internal chat scrolls in place instead of pushing the page down.

**Plugin slots** — `<PluginSlot name="..." />` rendered at known anchors: `backdrop`, `header-banner`, `header-left`, `header-right`, `pre-main`, `post-main`, `overlay` ([App.tsx:535-803](sopify-harness/web/src/App.tsx#L535-L803)).

**Globals from server-injected HTML**:
- `window.__HERMES_SESSION_TOKEN__` — bearer for `/api/*` calls.
- `window.__HERMES_BASE_PATH__` — URL prefix when reverse-proxied; used as `<BrowserRouter basename>`.
- `window.__HERMES_DASHBOARD_EMBEDDED_CHAT__` — gates the persistent ChatPage host.

### 7.3 API client — `web/src/lib/api.ts`

`fetchJSON<T>(url, init)` ([api.ts:39-52](sopify-harness/web/src/lib/api.ts#L39)) wraps `fetch` with header injection (`X-Hermes-Session-Token`). The exported `api` object has methods grouped by domain:

| Group | Examples |
|---|---|
| Sessions | `getStatus, getSessions, getSessionMessages, deleteSession, searchSessions` |
| Logs/Analytics | `getLogs, getAnalytics, getModelsAnalytics` |
| Config | `getConfig, getDefaults, getSchema, saveConfig, getConfigRaw, saveConfigRaw` |
| Env | `getEnvVars, setEnvVar, deleteEnvVar, revealEnvVar` |
| Providers | `getApiKeyProviders, setApiKey, deleteApiKey, testApiKey` |
| Models | `getModelInfo, getModelOptions, getAuxiliaryModels, setModelAssignment` |
| OAuth | `getOAuthProviders, disconnectOAuthProvider, startOAuthLogin, submitOAuthCode, pollOAuthSession, cancelOAuthSession` |
| Gateway/update | `restartGateway, updateHermes, getActionStatus` |
| Plugins | `getPlugins, rescanPlugins, getPluginsHub, install/enable/disable/update/remove AgentPlugin, savePluginProviders, setPluginVisibility` |
| Themes | `getThemes, setTheme` |
| Files | `listFiles, readFile, downloadFileUrl, previewUrl, startPreviewServer, previewServerStatus, stopPreviewServer, uploadFiles, deleteFile, renameFile, mkdir` |
| Vibe Code | `listVibeExamples, vibeExampleImageUrl, vibePreviewUrl, createVibeProject, listVibeProjects, getVibeProject, patchVibeProject, acceptVibeRequirements, acceptVibePlanning, runVibeSecurityReview, getVibeSystemPrompt, deleteVibeProject` |
| Cron / Profiles / Skills | full CRUD wrappers |

### 7.4 Pages (one-line summaries)

| Page | File | Highlights |
|---|---|---|
| **VibeCodePage** | [pages/VibeCodePage.tsx](sopify-harness/web/src/pages/VibeCodePage.tsx) | Tri-state `list / create / project / loading-project`; active project persisted in localStorage; CreateForm has Name input + ThemeCard grid + Switch-toggled Add-Ons + VerticalStepper |
| **VirtualOfficePage** | [pages/VirtualOfficePage.tsx](sopify-harness/web/src/pages/VirtualOfficePage.tsx) | **Stub** — Briefcase icon + placeholder. Route + nav wired, body not yet built |
| **PanelPage** | [pages/PanelPage.tsx](sopify-harness/web/src/pages/PanelPage.tsx) | Bubble-style chat (left) + Canvas iframe (right) + draggable divider. localStorage `sopify:panelChatPct` for split. Click-to-select via `formatSelection(sel)` feeds Composer prefill |
| **ChatPage** | [pages/ChatPage.tsx](sopify-harness/web/src/pages/ChatPage.tsx) | Embeds `hermes --tui` via xterm + `/api/pty` WebSocket. Custom wheel handler for scroll-in-transcript. Tier-based font sizing. Sopify light ANSI palette. Auto-jumps `?resume` to latest descendant |
| **SessionsPage** | [pages/SessionsPage.tsx](sopify-harness/web/src/pages/SessionsPage.tsx) | Paginated list + FTS5 search. Per-source icons (cli/telegram/discord/slack/whatsapp/cron). Rows link to `/chat?resume=<id>` or `/panel?resume=<id>` |
| **FilesPage** | [pages/FilesPage.tsx](sopify-harness/web/src/pages/FilesPage.tsx) | Tree-style browser anchored at dashboard CWD. Crumbs, image preview, drag-drop upload, rename/delete/mkdir |
| **AnalyticsPage** | [pages/AnalyticsPage.tsx](sopify-harness/web/src/pages/AnalyticsPage.tsx) | 7/30/90-day period. Hand-rolled `useTableSort<T>`. Inline SVG bar chart 160 px tall. Gated by `dashboard.show_token_analytics` |
| **ModelsPage** | [pages/ModelsPage.tsx](sopify-harness/web/src/pages/ModelsPage.tsx) | Current main model card + auxiliary-task assignments. Inlines ApiKeyUploadCard. Uses ModelPickerDialog in standalone mode |
| **LogsPage** | [pages/LogsPage.tsx](sopify-harness/web/src/pages/LogsPage.tsx) | Tail viewer for `{agent, errors, gateway}` files. Severity classifier colors rows |
| **CronPage** | [pages/CronPage.tsx](sopify-harness/web/src/pages/CronPage.tsx) | CRUD for cron jobs with profile selector |
| **NetworkPage** | [pages/NetworkPage.tsx](sopify-harness/web/src/pages/NetworkPage.tsx) | Talks to ENCM daemon via `encmApi` (proxied through `/api/encm/*`). Sub-panes AddRuleWizard, AuditTimeline |
| **SkillsPage** | [pages/SkillsPage.tsx](sopify-harness/web/src/pages/SkillsPage.tsx) | Skill + Toolset registry. Switch toggles → `api.toggleSkill` |
| **PluginsPage** | [pages/PluginsPage.tsx](sopify-harness/web/src/pages/PluginsPage.tsx) | Plugins Hub — install/enable/disable/update/remove, memory-provider + context-engine selects |
| **ProfilesPage** | [pages/ProfilesPage.tsx](sopify-harness/web/src/pages/ProfilesPage.tsx) | Profile CRUD. Braille-spinner loading state honoring `prefers-reduced-motion` |
| **ConfigPage** | [pages/ConfigPage.tsx](sopify-harness/web/src/pages/ConfigPage.tsx) | Schema-driven editor via `<AutoField>` |
| **EnvPage** | [pages/EnvPage.tsx](sopify-harness/web/src/pages/EnvPage.tsx) | API key + env-var editor with `PROVIDER_GROUPS`. Reveal-on-demand via `api.revealEnvVar` |
| **DocsPage** | [pages/DocsPage.tsx](sopify-harness/web/src/pages/DocsPage.tsx) | iframes `https://hermes-agent.nousresearch.com/docs/`. Hidden from sidebar, reachable by direct URL |

### 7.5 Key components

| Component | Purpose |
|---|---|
| [chat/ChatThread](sopify-harness/web/src/components/chat/ChatThread.tsx) | Renders `turns[]` with auto-stick-to-bottom |
| [chat/Composer](sopify-harness/web/src/components/chat/Composer.tsx) | Auto-growing textarea; Enter submits, Shift+Enter newlines; `prefill` + `prefillKey` for injected context |
| [chat/MessageBubble](sopify-harness/web/src/components/chat/MessageBubble.tsx) | UserBubble (right) + AssistantBubble (thinking → tools → answer order) |
| [canvas/PreviewFrame](sopify-harness/web/src/components/canvas/PreviewFrame.tsx) | Sandboxed iframe — Static (opaque origin) vs Live (`allow-same-origin`) |
| [canvas/CanvasPanel](sopify-harness/web/src/components/canvas/CanvasPanel.tsx) | Two-mode preview with click-to-select in Static mode |
| [vibe/VerticalStepper](sopify-harness/web/src/components/vibe/VerticalStepper.tsx) | 6-step rail: name/theme/addons/brainstorm/planning/building |
| [vibe/ThemeCard](sopify-harness/web/src/components/vibe/ThemeCard.tsx) | 4:3 image card with selection state |
| [vibe/ProjectView](sopify-harness/web/src/components/vibe/ProjectView.tsx) | Hosts BrainstormPane / PlanningPane / BuildingPane; shared ChatPanel wraps useChatStream |
| [ApiKeyUploadCard](sopify-harness/web/src/components/ApiKeyUploadCard.tsx) | Per-provider key card with reveal/save/delete/test + sbx-secret sync |
| [ModelPickerDialog](sopify-harness/web/src/components/ModelPickerDialog.tsx) | Two-stage provider→model modal; chat-session vs standalone modes |
| [ThemeSwitcher](sopify-harness/web/src/components/ThemeSwitcher.tsx), [LanguageSwitcher](sopify-harness/web/src/components/LanguageSwitcher.tsx) | Compact dropdowns with mobile bottom-sheet |
| [SidebarFooter](sopify-harness/web/src/components/SidebarFooter.tsx) | `v{version}` left, GS BATTERY link right |
| [SidebarStatusStrip](sopify-harness/web/src/components/SidebarStatusStrip.tsx) | Gateway state + active-session count |

### 7.6 Hooks

| Hook | Purpose |
|---|---|
| [useChatStream](sopify-harness/web/src/hooks/useChatStream.ts) | Wraps `GatewayClient` → `Turn[]` transcript. Exposes `sessionId`, `sessionKey` (the recent fix), `turns`, `send`, `interrupt` |
| [useCanvasPreview](sopify-harness/web/src/hooks/useCanvasPreview.ts) | Scans `turn.tools[]` for HTML paths, bumps version on writes |
| [useBelowBreakpoint](sopify-harness/web/src/hooks/useBelowBreakpoint.ts) | Thin `matchMedia('(max-width: …px)')` wrapper |
| [useDevServer](sopify-harness/web/src/hooks/useDevServer.ts) | Polls `/api/preview-server/status` at 1.5 s; exposes `running`, `url`, `logs`, `start()`, `stop()` |
| [useSidebarStatus](sopify-harness/web/src/hooks/useSidebarStatus.ts) | Polls `/api/status` every 10 s |
| [useConfirmDelete](sopify-harness/web/src/hooks/useConfirmDelete.ts) | Reused by Sessions/Cron/Profiles/Env |
| `useToast`, `useModalBehavior`, `usePageHeader` | Various |

### 7.7 Gateway client — `web/src/lib/gatewayClient.ts`

WebSocket transport, JSON-RPC dialect mirroring the Ink TUI's stdio protocol. Connects to `${scheme}//${host}${HERMES_BASE_PATH}/api/ws?token=${token}` (`wss:` over HTTPS).

**State machine**: `idle → connecting → open → closed | error`. Listener registration before `connect()` returns is load-bearing — the server emits `gateway.ready` immediately on accept.

**Event names** (union at [gatewayClient.ts:18-39](sopify-harness/web/src/lib/gatewayClient.ts#L18)): `gateway.ready, session.info, message.start/.delta/.complete, thinking.delta, reasoning.delta, reasoning.available, status.update, tool.start/.progress/.complete/.generating, clarify.request, approval.request, sudo.request, secret.request, background.complete, error, skin.changed`.

`request()` ([#L196-230](sopify-harness/web/src/lib/gatewayClient.ts#L196)) assigns sequential `id = "w${++reqId}"`, default timeout `120_000 ms`, rejects on server `error`, timeout, or mid-flight close.

---

## 8. Vibe Code feature

The flagship AI-DLC (AI-Driven Development Lifecycle) flow at `/vibe-code`. Lets a non-technical user scaffold a web project end-to-end through a guided chat.

> **Spec:** [`specs/VIBE_CODE_PANEL_SPEC.md`](specs/VIBE_CODE_PANEL_SPEC.md) — state machine, per-phase model assignment, port routing (Vibe=5174 / Panel=5173), background runtime, and compute separation. This section documents what is implemented today; the spec documents the target.

### 8.1 User journey (6 visible steps)

| Step | Backend phase | UI |
|---|---|---|
| 1. **Name** | (pre-creation) | `CreateForm` name input, regex `^[a-z0-9][a-z0-9_-]{0,63}$` |
| 2. **Theme** | (pre-creation) | `ThemeCard` grid: dashboard / form-registration / landing-page / web-app |
| 3. **Add-ons** | (pre-creation) | `Switch` toggles: auth-jwt, database-supabase, file-upload, schedule-job, qr-scan, dark-mode |
| 4. **Brainstorm** | `brainstorm` (+`requirements` hidden) | `BrainstormPane`: chat left, `RequirementsPreview` right (polls `getVibeProject` every 4 s). Approve plan → skips legacy `requirements` phase, jumps to `planning` |
| 5. **Planning** | `planning` | `PlanningPane`: chat + editable `PLANNING.md` textarea |
| 6. **Building** | `development` (+`improvement`/`security`/`approve` hidden) | `BuildingPane`: chat + iframe pointing at `http://localhost:<port>/` (port selector: 5173 Vite / 4173 Vite preview / 3000 Next-CRA / 4321 Astro / 8000 Python / 8080 Generic). Resizable split via `localStorage["sopify:vibeBuildChatPct"]` |

`phaseToStepKey` ([vibe/ProjectView.tsx:50-58](sopify-harness/web/src/components/vibe/ProjectView.tsx#L50-L58)) collapses the 7 backend phases into 3 visible UI steps.

### 8.2 `project.json` marker

Written by `vibe_create_project` ([web_server.py:5465-5474](sopify-harness/hermes_cli/web_server.py#L5465)). Schema:

```json
{
  "name": "<slug>",
  "mode": "dashboard|form-registration|landing-page|web-app",
  "add_ons": ["<sorted unique subset of 6>"],
  "created_at": "<ISO-8601 UTC>",
  "updated_at": "<ISO-8601 UTC>",   // rewritten on every marker write
  "phase": "brainstorm|requirements|planning|development|improvement|security|approve",
  "session_id": "<DB session_key, persisted by ChatPanel>",
  "summary": "<free-text running summary, optional>"
}
```

### 8.3 Theme scaffolding (recent change)

On `POST /api/vibe/projects`, after creating the marker, **copy `example/<mode>/*` into the project folder** (excluding `image.png` — that's the picker thumbnail). [web_server.py:5452-5464](sopify-harness/hermes_cli/web_server.py#L5452):
```python
example_src = _VIBE_EXAMPLES_DIR / body.mode
if example_src.is_dir():
    for entry in example_src.iterdir():
        if entry.name == "image.png":
            continue
        dest = project_dir / entry.name
        if entry.is_dir():
            shutil.copytree(entry, dest)
        else:
            shutil.copy2(entry, dest)
```
This ships each project with `app/`, `assets/`, and the named HTML entry (e.g. `Production Overview.html` for `dashboard` mode). The `/preview/vibe/{name}` endpoint resolves a directory by looking for `index.html` first, then the first `.html` file in lexical order ([web_server.py:5394-5400](sopify-harness/hermes_cli/web_server.py#L5394)).

### 8.4 System prompt composition

`_vibe_compose_system_prompt(marker)` ([web_server.py:5575-5608](sopify-harness/hermes_cli/web_server.py#L5575)):

1. Synthetic preamble (Vibe-specific addition):
   ```
   # Project: <name>
   **Project folder:** `<absolute path>`
   All files for this project — including REQUIREMENTS.md, PLANNING.md, source code, etc. —
   live under that absolute path. Use it directly when reading or writing project files;
   do not assume the current working directory.
   ```
2. `prompts/vibe/base.md` (general Vibe Code agent instructions, including the IPv4 `--host 0.0.0.0` directive for dev servers — recent addition for the Live Preview to work)
3. `prompts/vibe/modes/<mode>.md`
4. For each `addon` in marker.add_ons: `prompts/vibe/add-ons/<addon>.md`

Missing files silently skipped. Sections joined by `\n\n`.

The prompt is sent to the agent as the **kickoff user message** by [vibe/ProjectView.tsx:248-262](sopify-harness/web/src/components/vibe/ProjectView.tsx#L248-L262), not as a true OpenAI/Anthropic system role.

### 8.5 Live Preview port mapping

For the Building step's iframe to load the agent's dev server:

1. **Sopify launcher publishes** common dev ports alongside 9119 ([sopify:296-299](sopify-harness/sopify#L296-L299)): `[9119, 5173, 4173, 3000, 4321, 8000, 8080]`. So when the agent runs `vite`, the host browser can reach `http://localhost:5173`.
2. **Vite must bind IPv4** — Node 18+ resolves `localhost` to IPv6 (`::1`) by default. Docker port-publish forwards IPv4 only. Solution: pass `--host` or set `server.host: '0.0.0.0'` in `vite.config.ts`. The Vibe base prompt now instructs the agent to do this.
3. **iframe sandbox** in BuildingPane uses `allow-scripts allow-forms allow-popups allow-modals allow-same-origin` so SPAs with localStorage / `history.pushState` work.
4. **Reload key** in iframe `src` (`http://localhost:5173/#<key>`) forces re-mount.

**The port the iframe uses is no longer hard-coded.** [BuildingPane](sopify-harness/web/src/components/vibe/ProjectView.tsx) (and /panel's CanvasPanel) auto-detect the current session's dev-server URL from chat tool output, and the dev-server manager handles kill/revive when sessions switch. See [§9. Dev server lifecycle](#9-dev-server-lifecycle-per-session).

If the agent's dev server is on a port outside the publish list, the user can manually run `sbx ports sopify-<hash> --publish 127.0.0.1:<port>:<port>` on the host.

### 8.6 Vibe Code components

| Component | File:line | Notes |
|---|---|---|
| `VibeCodePage` | [pages/VibeCodePage.tsx](sopify-harness/web/src/pages/VibeCodePage.tsx) | Top-level state machine + persistence in `localStorage["sopify:vibeCurrentProject"]` |
| `ProjectsList` | [pages/VibeCodePage.tsx:194-344](sopify-harness/web/src/pages/VibeCodePage.tsx#L194) | 2-up grid of project cards with hover-delete |
| `CreateForm` | [pages/VibeCodePage.tsx:394-550](sopify-harness/web/src/pages/VibeCodePage.tsx#L394) | Name + Theme + Add-Ons + Submit + sticky VerticalStepper |
| `ProjectView` | [components/vibe/ProjectView.tsx:62-123](sopify-harness/web/src/components/vibe/ProjectView.tsx#L62) | Layout container + phase router |
| `ChatPanel` | [components/vibe/ProjectView.tsx:158-236](sopify-harness/web/src/components/vibe/ProjectView.tsx#L158) | Shared chat wrapper around `useChatStream` |
| `RequirementsPreview` | [components/vibe/ProjectView.tsx:312-380](sopify-harness/web/src/components/vibe/ProjectView.tsx#L312) | Read-only `REQUIREMENTS.md`; polls `getVibeProject` every 4s |
| `PlanEditor` | [components/vibe/ProjectView.tsx:421-490](sopify-harness/web/src/components/vibe/ProjectView.tsx#L421) | Editable `PLANNING.md` textarea + Approve button |
| `BuildingPane` | [components/vibe/ProjectView.tsx:494-688](sopify-harness/web/src/components/vibe/ProjectView.tsx#L494) | Chat + iframe + port selector + resizable split |
| `VerticalStepper` | [components/vibe/VerticalStepper.tsx](sopify-harness/web/src/components/vibe/VerticalStepper.tsx) | 6-step rail with `VIBE_STEPS` constant |
| `ThemeCard` | [components/vibe/ThemeCard.tsx](sopify-harness/web/src/components/vibe/ThemeCard.tsx) | 4:3 image card with selection state |

### 8.7 Prompt files

```
prompts/vibe/
├── base.md            # general AI-DLC instructions, dev-server IPv4 bind directive
├── modes/
│   ├── dashboard.md
│   ├── form-registration.md
│   ├── landing-page.md
│   └── web-app.md
└── add-ons/
    ├── auth-jwt.md
    ├── database-supabase.md
    ├── dark-mode.md
    ├── file-upload.md
    ├── qr-scan.md
    └── schedule-job.md
```

Each Vibe project's effective system prompt = `base.md` + `modes/<mode>.md` + each selected add-on, plus the synthetic preamble with the absolute project folder path.

---

## 9. Dev server lifecycle (per-session)

The Vibe Code Building view and /panel's Canvas iframe both want to show whatever HTML the agent's `npm run dev` is serving. Multiple chat sessions share the sandbox's network namespace, so **port 5173 can only host one Vite at a time**. The lifecycle below treats the dev server as a per-session resource: switching the active session pauses one session's servers and revives the other's.

### 9.1 Mental model

```
[idle] ──agent runs `npm run dev` & prints URL──> [running] ──user switches session──> [paused]
                                                       ▲                                  │
                                                       └───user comes back to session─────┘
                                                              (auto-revive, 5173 first)
```

**Active session** is the chat session that most recently received a `session.create` / `session.resume` / `prompt.submit`. Browser URL navigation alone doesn't change active — explicit interaction does. See `_set_active_session_for_sid` at [tui_gateway/server.py](sopify-harness/tui_gateway/server.py).

### 9.2 Components

| File | Role |
|---|---|
| [hermes_cli/dev_server_manager.py](sopify-harness/hermes_cli/dev_server_manager.py) | State, PID/PGID resolution, kill/revive logic. Module-level globals — visible across the FastAPI + in-process gateway path (`/api/ws`). Not visible to subprocess gateway (PTY `/api/pty`) since they're different processes. |
| [tui_gateway/server.py](sopify-harness/tui_gateway/server.py) | URL detection + active-session hooks. `_on_tool_complete` runs `_detect_dev_server_from_tool` which calls `dev_server_manager.register_detected_url` then emits `dev_server.detected`. `session.create / .resume / prompt.submit` call `_set_active_session_for_sid` to trigger the switch. |
| [hermes_cli/web_server.py](sopify-harness/hermes_cli/web_server.py) | 3 endpoints: `GET /api/dev-server`, `POST /api/sessions/set-active`, `POST /api/dev-server/stop`. |
| [web/src/hooks/useChatStream.ts](sopify-harness/web/src/hooks/useChatStream.ts) | Subscribes to `dev_server.detected`, dedupes by port, exposes `devServers: DevServerHint[]` to consumers. Reset on `resumeId` change. |
| [web/src/components/vibe/ProjectView.tsx](sopify-harness/web/src/components/vibe/ProjectView.tsx) | `ChatPanel` bubbles `devServers` up via `onDevServersChange` callback. `BuildingPane` reads `devServers[0]?.url` directly — port selector dropdown was removed. |
| [web/src/components/canvas/CanvasPanel.tsx](sopify-harness/web/src/components/canvas/CanvasPanel.tsx) | New prop `detectedDevUrl` seeds Live mode URL + auto-switches from Static to Live on first detection. |

### 9.3 Detection pipeline

```
Agent calls shell tool → `npm run dev` runs in sandbox → stdout:
  "Local:   http://localhost:5173/"
                  │
                  ▼   tool emits result back through gateway
_on_tool_complete(sid, name, args, result)
                  │
                  ▼
_detect_dev_server_from_tool(sid, session, tool_name, args, result):
   1. strip ANSI from `result`
   2. regex `http://(localhost|0.0.0.0|127.0.0.1|[::1?])(:<port>)?(/...)?`
   3. skip reserved ports (9119 dashboard, 7777 ENCM daemon)
   4. extract command_hint + cwd_hint from tool args (used later for revive)
   5. dev_server_manager.register_detected_url(session_key, port, url, ...)
                  │
                  ▼
register_detected_url:
   - find_pid_for_port(port) via /proc/net/tcp{,6} + /proc/*/fd/* symlinks
   - find_pgid(pid)
   - upsert spec in _session_dev_servers[session_key]
   - status = "running"
                  │
                  ▼
_emit("dev_server.detected", sid, {port, url, session_key, status, pid})
                  │
                  ▼
Browser via /api/ws → useChatStream subscriber → setDevServers([{...}, ...])
                  │
                  ▼
BuildingPane / CanvasPanel iframe src = devServers[0].url
```

URL regex covers Vite (`Local: http://localhost:5173/`), Next.js (`- Local: http://localhost:3000`), CRA (`Local: http://localhost:3000`), Astro (`┃ Local http://localhost:4321/`) after `\x1b[...m` ANSI stripping.

### 9.4 PID / PGID resolution

`find_pid_for_port(port)` ([dev_server_manager.py](sopify-harness/hermes_cli/dev_server_manager.py)):

1. Scan `/proc/net/tcp` + `/proc/net/tcp6` for sockets in state `0A` (LISTEN). Extract `{port: inode}`.
2. Look up the inode for the requested port.
3. Walk `/proc/<pid>/fd/*` for every numeric pid, check if any symlink target equals `socket:[<inode>]`.
4. Return that PID.

PGID is `os.getpgid(pid)`. Subprocess.Popen children spawned by the agent's shell tool *should* inherit a sensible PGID. If the agent backgrounds with `&` or `nohup`, the PID may belong to a different PGID — code falls back to `os.kill(pid, SIGTERM)` for the bare PID.

### 9.5 The switch — `set_active_session(target_key)`

[dev_server_manager.py](sopify-harness/hermes_cli/dev_server_manager.py) — under `_switch_lock` so concurrent session changes serialize:

```
1. Read previous active_session_key under _active_lock; set to target_key.
2. If previous == target → just refresh status (cheap probe), return.
3. Otherwise:
   for spec in (all running specs whose session_key != target_key):
       _pause_spec(spec)
         - killpg(pgid, SIGTERM); poll for up to 3s; killpg(pgid, SIGKILL) if alive
         - wait_for_port_free(port, timeout=5)
         - status = "paused"; pid = pgid = None

   target_specs sorted by (port != 5173, port)   # 5173 first, then ascending
   for spec in target_specs:
       if spec already "running" → verify, skip
       if no command/cwd recorded → mark "failed" (can't revive)
       else:
           _revive_spec(spec):
             - wait_for_port_free(spec.port, timeout=3)
             - subprocess.Popen(spec.command, shell=True, cwd=spec.cwd,
                                 env=spec.env, preexec_fn=os.setsid,
                                 stdout=DEVNULL, stderr=DEVNULL)
             - wait_for_port_listening(spec.port, timeout=20)
             - status = "running"; pid = pgid = proc.pid
```

Returns `{paused, revived, failed, skipped, active_session_key}` for the caller. The gateway's `_set_active_session_for_sid` reads this summary and re-emits `dev_server.detected` for every running spec so the frontend re-hydrates after a `session.resume` (when its devServers state was just cleared).

### 9.6 Frontend wiring

**useChatStream subscribes** ([useChatStream.ts](sopify-harness/web/src/hooks/useChatStream.ts)):

```typescript
gw.on<{port?, url?, status?}>("dev_server.detected", (ev) => {
  if (typeof ev.payload?.port !== "number") return;
  setDevServers((prev) => {
    const filtered = prev.filter((d) => d.port !== ev.payload.port);
    if (ev.payload.status !== "running") return filtered;  // failed → remove
    return [{port, url, status, detectedAt: Date.now()}, ...filtered];
  });
});
```

**BuildingPane** ([ProjectView.tsx](sopify-harness/web/src/components/vibe/ProjectView.tsx)) — port selector dropdown removed:

```typescript
const [devServers, setDevServers] = useState<{port, url}[]>([]);
const currentServer = devServers[0];
const previewSrc = currentServer ? `${currentServer.url}#${reloadKey}` : null;

return (
  <ChatPanel project={project} onDevServersChange={setDevServers} />
  {previewSrc ? <iframe src={previewSrc} ... /> : null}
);
```

When `previewSrc` is null, the chat takes the full row and the divider hides.

**CanvasPanel** ([CanvasPanel.tsx](sopify-harness/web/src/components/canvas/CanvasPanel.tsx)) — accepts `detectedDevUrl` prop:

- Seeds `liveUrl` from the prop (session-detected wins over the `/api/preview-server/status` poll from `useDevServer`).
- Auto-switches from Static to Live mode on first detection (one-time, tracked with `switchedToLiveRef`).

PanelPage passes the URL through:

```typescript
const { devServers, ... } = useChatStream(resumeId);
const detectedDevUrl = devServers[0]?.url ?? null;
<CanvasPanel canvas={canvas} ... detectedDevUrl={detectedDevUrl} />
```

### 9.7 New API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/dev-server?session_key=<key>` | List specs for a session (or all running across sessions if `session_key` omitted) |
| POST | `/api/sessions/set-active` body `{session_key}` | Trigger switch (pause others + revive target). Frontend doesn't currently call this directly — the gateway hooks do it on session.create / .resume / prompt.submit — but it's exposed for explicit out-of-band triggers. |
| POST | `/api/dev-server/stop` body `{session_key, port}` | Manual SIGTERM of one spec without changing active session. |

All token-gated (`_require_token`).

### 9.8 State persistence

**None yet.** `_session_dev_servers` is in-memory in the dashboard process. Implications:

- Dashboard restart → all specs lost → every session reverts to idle. Agent must re-run `npm run dev` next time it's needed. Acceptable for MVP.
- Reviving relies on `command + cwd` having been captured at first detection. If the agent's tool args didn't carry a recognizable `command` field, the revive will mark `failed` with `last_error = "no command/cwd recorded — cannot revive"`.
- Sandbox container recycling (sbx reaping) kills the spec processes too; the dashboard would still try to revive on next session activation, may also fail.

**Persistence path forward** (not implemented): add `dev_command`, `dev_cwd`, `dev_port` columns to the `sessions` table and write them on `register_detected_url`. Mark all as `paused` on dashboard startup. Revive on first set-active.

### 9.9 Edge cases handled

1. **Agent backgrounds with `&` / `nohup`** → PID/PGID may detach. Fallback to bare `os.kill(pid, SIGTERM)` instead of `killpg`.
2. **Spec already running on entering session** → verify port still LISTEN; if not, downgrade to paused and let normal revive flow handle.
3. **Multiple specs in same session** (frontend Vite + backend Node) → revive sequential: 5173 first, then ascending port. Each waits up to 20s for port to bind before moving on.
4. **Revival fail** (deps missing, npm install needed, etc.) → spec marked `status="failed"`, `last_error` populated, event re-emitted with status="failed" so frontend removes the URL from `devServers` and iframe drops.
5. **Subprocess-mode gateway (PTY chat)** → import of `dev_server_manager` swallowed with `try/except ImportError`; tab works as before, just no preview iframe.
6. **macOS dev environment** (no `/proc`) → `find_pid_for_port` returns None, `wait_for_port_listening` falls back to TCP connect probe. Detection still works without PID tracking; kill is impossible (no process to target).

### 9.10 Known limitations

- **Per-tab race**: if two browser tabs each open a different session, both call session.resume → last one wins, the first tab's iframe goes dark mid-use. Add comment to UX, not a hard fix.
- **State stays in dashboard process** — see 9.8.
- **Revive doesn't run through the agent** — backend Popen bypasses the agent's shell. Agent isn't notified; its mental model may say "server still running" while actually it was restarted. Refresh patterns the agent does (e.g. curl localhost:5173) still work, so this is mostly invisible.
- **Vite must `--host`** — IPv4 binding is still required (see §8.5).
- **Same-port collision between sessions** is intentional: kill old, start new. If the user wants both up concurrently they'd need to assign different ports manually in chat — and only one of them would be on a publish-listed port anyway.

---

## 10. Plugin system

### 10.1 Discovery & loading

[web/src/plugins/usePlugins.ts](sopify-harness/web/src/plugins/usePlugins.ts) — on mount:

1. `GET /api/dashboard/plugins` returns manifest list.
2. For each manifest:
   - Inject `<link rel="stylesheet">` for `manifest.css` if set.
   - Load JS bundle as `<script type="module">` from `${HERMES_BASE_PATH}/dashboard-plugins/<name>/<entry>`. Dev: cache-bust via `?hermes_dv=<ms>`; prod: dedupe by base URL.
   - SRI: apply `manifest.integrity` if set.
   - Errors: `onerror` → `setPluginLoadError(name, "LOAD_FAILED")`; `onload` without `register()` → `"NO_REGISTER"`.
   - 2-second safety timeout drops loading state if nothing registers.

### 10.2 PluginManifest shape

[plugins/types.ts:5-32](sopify-harness/web/src/plugins/types.ts#L5-L32):
```typescript
{
  name: string,
  label: string,
  description: string,
  icon: string,                    // string mapped via ICON_MAP
  version: string,
  tab: { path, position?, override?, hidden? },
  slots?: ...,
  entry: string,                   // JS bundle filename
  css?: string,
  has_api: boolean,
  integrity?: string,              // SRI hash
  source: string
}
```

### 10.3 PluginPage rendering

[plugins/PluginPage.tsx](sopify-harness/web/src/plugins/PluginPage.tsx) uses `useSyncExternalStore` to subscribe to the registry **during render** — so a `register()` that lands before the next effect tick is never missed.

### 10.4 Slots

[plugins/slots.ts](sopify-harness/web/src/plugins/slots.ts) — `<PluginSlot name="..." fallback?>` renders all entries stacked, in registration order; falls through to `fallback` when empty.

`KNOWN_SLOT_NAMES`: `backdrop, header-left, header-right, header-banner, sidebar, pre-main, post-main, footer-left, footer-right, overlay` + page-scoped `<page>:top/<page>:bottom` for sessions/analytics/logs/cron/skills/plugins/config/env/docs/chat.

### 10.5 Plugin SDK

`exposePluginSDK()` ([plugins/registry.ts:101-151](sopify-harness/web/src/plugins/registry.ts#L101)) writes:
```typescript
window.__HERMES_PLUGINS__ = { register, registerSlot };
window.__HERMES_PLUGIN_SDK__ = {
  React, hooks, api, fetchJSON,
  components: { Card, CardHeader, CardTitle, CardContent, Badge, Button, Checkbox,
                Input, Label, Select, SelectOption, Separator, Tabs, TabsList, TabsTrigger,
                PluginSlot },
  utils, useI18n
};
```

Plugin bundles call `window.__HERMES_PLUGINS__.register(name, Component)` from inside their entry script.

### 10.6 Backend plugin mount

Plugin Python files can export FastAPI routers that get mounted under `/api/plugins/<name>/...` ([web_server.py:5779-5823](sopify-harness/hermes_cli/web_server.py#L5779)). These inherit middleware auth automatically because they're under `/api/`.

---

## 11. Theme & i18n

### 11.1 Themes

[web/src/themes/presets.ts](sopify-harness/web/src/themes/presets.ts) defines built-ins:

- **sopify** (default, light, Roboto-based — `#F8FAFC` bg / `#03061E` text / blue-tinted glow)
- **default** (Hermes Teal, legacy)
- **default-large** (same palette, bigger fonts + spacious density)
- **midnight**, **ember**, **mono**, **cyberpunk**, **rose**

`DashboardTheme` shape ([themes/types.ts](sopify-harness/web/src/themes/types.ts)): `palette`, `typography`, `layout`, optional `layoutVariant: "standard" | "cockpit" | "tiled"`, `assets`, `customCSS`, `componentStyles`, `colorOverrides`.

**ThemeProvider** ([themes/context.tsx](sopify-harness/web/src/themes/context.tsx)) — persists active theme in `localStorage["sopify-dashboard-theme"]`. Legacy `hermes-dashboard-theme` one-time migrated; legacy Hermes built-in names auto-promote to `sopify` while user themes are preserved.

`applyTheme(theme)` ([themes/context.tsx:305-343](sopify-harness/web/src/themes/context.tsx#L305)) clears prior overrides, emits `--background/midground/foreground` color-mix triples + `--warm-glow`, `--noise-opacity-mul`, typography vars (`--theme-font-*`, `--theme-base-size`, `--theme-line-height`), layout vars (`--radius`, `--theme-spacing-mul`), sets `data-layout-variant` + `data-theme-name` on `<html>`.

User themes from `~/.hermes/dashboard-themes/*.yaml` arrive via `GET /api/dashboard/themes`. Their full definitions are stored in `userThemeDefs` so re-applies work without a second round-trip.

### 11.2 i18n

[web/src/i18n/context.tsx](sopify-harness/web/src/i18n/context.tsx) — 16 locales registered: `en, zh, zh-hant, ja, de, es, fr, tr, uk, af, ko, it, ga, pt, ru, hu`. Each maps to its endonym + ISO 3166 flag-icons country code (`en→gb, ja→jp, ...`).

Persistence key `hermes-locale`. `useI18n()` returns `{ locale, setLocale, t }`. Pages destructure `t.app.nav.<key>`, `t.common.*`, etc.

Note: the project's **website** repo (`sopify-harness/website/`) is limited to English + Japanese — different from the dashboard's 16 locales.

---

## 12. ENCM control plane

ENCM = Egress Network Control Module — host-side daemon governing what egress traffic the sandbox is allowed to make.

### 12.1 Two trees

- **`plugins/sopify_encm/`** — agent-side plugin for in-sandbox hooks (rules schema, audit, migration).
- **`sopify_daemon/`** — host-side FastAPI daemon (the actual control plane).

### 12.2 Daemon lifecycle

[sopify_daemon/app.py:39-95](sopify-harness/sopify_daemon/app.py#L39):

- `lifespan()` async context manager loads config, ensures FS skeleton ([paths.py:90-104](sopify-harness/sopify_daemon/paths.py#L90)), writes `~/.sopify/daemon.pid`.
- Boots `SbxBackend(socket_path=...)` — talks to sandboxd's Unix socket via httpx ([sbx_backend.py:107-120](sopify-harness/sopify_daemon/sbx_backend.py#L107)).
- Starts three background `asyncio.Task`s: `encm-reconciler`, `encm-audit-ingester`, `encm-audit-retention` ([app.py:62-74](sopify-harness/sopify_daemon/app.py#L62)).
- On shutdown: cancels tasks, closes HTTP client, removes pid file.

**Default config** ([sopify_daemon/config.py](sopify-harness/sopify_daemon/config.py)):
- `bind: 127.0.0.1`, `port: 7777`.
- `token`: 64-hex-char (256-bit), generated by `secrets.token_hex(32)` on first run, mode `0o600`.
- `reconciler_interval_seconds: 30`.
- `audit_retention_days: 90`.

### 12.3 Host-only — never in sandbox

The daemon talks to host's sandboxd over Unix socket — that file only exists on the host, so the daemon stays on the host even though the dashboard runs inside a microVM.

### 12.4 Auto-start from `sopify dashboard`

`_ensure_encm_daemon_running()` ([sopify:183-243](sopify-harness/sopify#L183-L243)):

1. Skip when `SOPIFY_IN_SANDBOX=1` or `SOPIFY_NO_ENCM=1`.
2. Probe `http://127.0.0.1:7777/health` (timeout 0.5 s) — return if up.
3. Spawn detached `subprocess.Popen([sys.executable, ROOT/"sopify", "start"])` with `start_new_session=True`, log to `~/.sopify/daemon.log`.
4. Poll `/health` up to 30 × 0.1 s for bind.

### 12.5 Dashboard → daemon proxy

`/api/encm/{path:path}` ([web_server.py:5752-5776](sopify-harness/hermes_cli/web_server.py#L5752)) proxies to daemon `/api/v1/<path>`.

`hermes_cli/encm_client.py` ([encm_client.py:100-149](sopify-harness/hermes_cli/encm_client.py#L100)) reads `~/.sopify/config.yaml`, attaches `Authorization: Bearer <daemon-token>` server-side, forwards the request.

**Host-vs-sandbox address resolution** ([encm_client.py:41-97](sopify-harness/hermes_cli/encm_client.py#L41)):
- Host: `127.0.0.1:7777`.
- Sandbox: rewrites loopback → `host.docker.internal:7777` (so `/api/encm/*` from inside the dashboard reaches the host daemon).

Returns `(503, {detail, reachable: False})` on `httpx.ConnectError` — letting the /network page render an "ENCM daemon down" state.

### 12.6 Reconciler

[sopify_daemon/reconciler.py:159-191](sopify-harness/sopify_daemon/reconciler.py#L159):

- Loop period from `cfg.reconciler_interval_seconds` (30 s default).
- Each tick: walk `~/.sopify/encm/rules/`, load YAML → `NetworkRule`, `GET /policy/rules` from sandboxd, diff, POST/DELETE to converge.
- Filters out sbx baseline rules.

---

## 13. Dev workflow & build pipeline

### 13.1 Frontend

```bash
cd sopify-harness/web

# dev — hot-reload, with token injection from running dashboard
npm run dev

# build — outputs to ../hermes_cli/web_dist/
npm run build

# type-check
npm run type-check

# lint
npm run lint
```

### 13.2 Backend reload

Python modules are loaded once at process start. To pick up edits to `hermes_cli/web_server.py`, `tui_gateway/server.py`, the `sopify` launcher, etc., **kill and restart the dashboard process**:

```bash
# find
ps aux | grep "sopify dashboard" | grep -v grep

# kill (the host launcher; sbx exec child follows)
kill <pid>

# restart
sopify dashboard
```

The web bundle is loaded fresh from `web_dist/` on each browser request, so a `npm run build` + browser hard-reload (Cmd/Ctrl+Shift+R) is enough for frontend-only changes.

### 13.3 Sandbox lifecycle

```bash
# List sandboxes
sbx ls

# Inspect ports
sbx ports sopify-<hash>

# Manually publish a port (if dashboard's default list isn't enough)
sbx ports sopify-<hash> --publish 127.0.0.1:9000:9000

# Remove a stale sandbox (cwd determines which one a fresh `sopify dashboard` reuses)
sbx rm sopify-<hash>
```

### 13.4 Where to start when picking up a session

1. Read [SESSION_HANDOFF.md](sopify-harness/SESSION_HANDOFF.md) if present — single source of truth for current state.
2. Skim [SOPIFY_HERMES_ARCHITECTURE.md](SOPIFY_HERMES_ARCHITECTURE.md) for the upstream relationship.
3. `sbx ls` to check sandbox state.
4. `ps aux | grep sopify` to see what's running.
5. `curl http://127.0.0.1:9119/api/status` to probe the dashboard.

---

## 14. Known quirks & gotchas

1. **Doubled publish-ports thread** — [sbx_launcher.py:385-389](sopify-harness/plugins/sopify_sandbox/sbx_launcher.py#L385) starts the identical `_worker` thread twice. Both compete on `sbx ports --publish` (each idempotent so functionally OK; doubles stderr noise and `sbx ls` load). Likely accidental duplication.

2. **No `DEV_SOPIFY` env var** — the dev-mode "env var" referenced in old session notes is actually a shell-local variable inside `inner_cmd`, computed by globbing `/Users/*/...sopify` paths ([sbx_launcher.py:675-699](sopify-harness/plugins/sopify_sandbox/sbx_launcher.py#L675-L699)).

3. **sbx container reaping between exec calls** — explains why `_publish_ports_when_ready` re-publishes every 3 s. Listing ports via `sbx ports` only proves a publish request was accepted; HTTP probe from host is the only signal that the chain actually works.

4. **Workspace-hoisted node_modules** — `@rollup/rollup-darwin-arm64` optional dep can be missing after `npm i` if workspace hoisting picks Linux-only natives ([sopify-project memory](https://example/memory)). Workaround: `npm i --no-save @rollup/rollup-darwin-arm64@<version>` before `npm run build`.

5. **`@nous-research/ui` is NOT a symlink in this checkout** — `package.json` declares `^0.14.2` resolving to the public npm tarball. The Vite `dedupe` comment ([web/vite.config.ts:73-81](sopify-harness/web/vite.config.ts#L73-L81)) is residual documentation from when it was a `file:` link.

6. **Vite (and Node 18+) bind IPv6 by default** — `localhost` resolves to `::1`. Docker port-publish forwards IPv4 only. Dev servers must bind `0.0.0.0` for the dashboard iframe to reach them. The Vibe base prompt now explicitly tells the agent this; for non-Vibe contexts the user has to know to set `vite --host` or `server.host: '0.0.0.0'`.

7. **`hermes_preview` cookie is the same token** — the `/preview` cookie carries the **same** `_SESSION_TOKEN` value, not a separate credential. It's just a delivery channel for iframe subresources that can't carry custom headers.

8. **Tracing via `patchStderr`/`patchConsole` swallows output silently** — for low-level debugging, write to raw file descriptors instead. (See [feedback-trace-bypass-patching memory](https://example/memory).)

9. **Session resume confusion** — `session_id` from JSON-RPC responses is the **gateway sid** (in-memory only). Callers persisting it for resume will hit `4007 "session not found"`. The fix: persist `session_key` (DB key) instead. See [tui_gateway/server.py:2157-2176](sopify-harness/tui_gateway/server.py#L2157-L2176) and [useChatStream.ts](sopify-harness/web/src/hooks/useChatStream.ts).

10. **`/docs` and `/analytics` are reachable by URL but hidden from sidebar** — `/docs` always; `/analytics` only when `dashboard.show_token_analytics` is true ([App.tsx:478-482](sopify-harness/web/src/App.tsx#L478-L482)).

11. **`SECURITY_REVIEW.md` is a stub** — `POST /api/vibe/projects/{name}/security-review` writes a hard-coded markdown placeholder ([web_server.py:5706-5721](sopify-harness/hermes_cli/web_server.py#L5706-L5721)), not a real security review.

12. **VirtualOfficePage is a stub** — added 2026-05-29 ([pages/VirtualOfficePage.tsx](sopify-harness/web/src/pages/VirtualOfficePage.tsx)). Route + nav entry wired; body is placeholder. Add real content here.

13. **`sopify-harness/ARCHITECTURE.md` is Hermes core — DO NOT EDIT** (REQ-0.3 from memory). Sopify-specific architecture changes belong in this file or in `SOPIFY_HERMES_ARCHITECTURE.md`.

14. **Project folder lives inside the sandbox** — `~/.hermes/vibe-projects/<name>/` is INSIDE the Docker container. To inspect files from the host, use `sbx exec sopify-<hash> ls /home/sopify/.hermes/vibe-projects/<name>/` or copy out via `sbx cp`.

15. **TS warnings the build tolerates** — `npm run type-check` may report stale `variant=` props on `<Badge>` etc. when the design-system API has shifted. The Vite build passes anyway (it doesn't enforce strict types). Fix them when you see them, but the dashboard runs regardless.

16. **Dev server lifecycle state is in-memory only** — `_session_dev_servers` lives in the dashboard Python process. Restart = lose all specs; agent has to re-run `npm run dev` next time. See [§9.8](#98-state-persistence) for the persistence path forward.

17. **Per-session dev-server lifecycle only works on `/api/ws` clients** — Vibe Code and `/panel` use the in-process gateway, so they share `dev_server_manager` state with the FastAPI process. The PTY-mode `/api/pty` chat tab runs a *subprocess* gateway whose imports of `dev_server_manager` fail silently — no preview iframe in that tab anyway, so this is acceptable.

18. **Agent-initiated dev server may have command in args that we can't parse** — `_extract_command_hint` covers the common keys (`command`, `cmd`, `shell`, `script`, `code`), but if a custom tool uses an unusual arg shape the spec's `command` stays empty and revive marks it `failed`. Symptom: agent reports `npm run dev` works, but switching sessions and coming back leaves the iframe blank. Add the missing key to `_extract_command_hint` to fix.

---

## 15. Model selection strategy

**TL;DR:** Sopify currently defaults to `anthropic/claude-opus-4.7` at the top of every provider picker ([models.py:165](sopify-harness/hermes_cli/models.py#L165)). For a corporate deployment driven mostly by non-engineers and routine SDLC tasks, that default is over-priced by 10×–50× vs equally-capable OSS alternatives that already pass the codebase's tool-calling filter ([models.py:1093](sopify-harness/hermes_cli/models.py#L1093)). The proposed policy is **hybrid**: Anthropic where taste/liability matters (Vibe Design, Security review), OSS (Kimi K2.6, DeepSeek V3.2, Qwen3.6-plus) for everything else.

Full rationale, cost numbers, migration plan, and risks live in [**MODEL_SELECTION.md**](sopify-harness/MODEL_SELECTION.md) — this section is the architecture-level summary.

### 15.1 What the runtime already supports

| Capability | Location | Notes |
|---|---|---|
| Provider cascade (primary → fallback) | [router.py:20](sopify-harness/plugins/sopify_providers/router.py#L20) | Default chain `anthropic → openrouter → hermes_default`; 1 h blacklist on 401/403/429 |
| Per-task auxiliary slots | [web_server.py:996](sopify-harness/hermes_cli/web_server.py#L996) | `vision`, `web_extract`, `compression`, `session_search`, `skills_hub`, `approval`, `mcp`, `title_generation`, `curator` — already separable model assignments |
| Curated picker | [models.py:163](sopify-harness/hermes_cli/models.py#L163) | `_PROVIDER_MODELS` — 20+ providers; first entry = picker default |
| Live tool-calling filter | [models.py:1093](sopify-harness/hermes_cli/models.py#L1093) | OpenRouter `/v1/models` items whose `supported_parameters` omit `tools` are hidden |
| Override chain via settings | [router.py:33](sopify-harness/plugins/sopify_providers/router.py#L33) | `~/.sopify/settings.json:provider_chain` |

### 15.2 Per-Vibe-phase model assignment (proposed)

The Vibe phase machine ([web_server.py:5484](sopify-harness/hermes_cli/web_server.py#L5484)) currently uses one model across all phases. Splitting per-phase is the highest-leverage cost lever (Vibe is the flagship flow + the bulk of token spend).

| Phase | System prompt | Workload character | Recommended primary | Rationale |
|---|---|---|---|---|
| **brainstorm** | [prompts/vibe/phases/brainstorm.md](sopify-harness/prompts/vibe/phases/brainstorm.md) | Q&A, short turns | `claude-haiku-4-5` | Cheap, fast, low-stakes |
| **design** | [prompts/vibe/phases/design.md](sopify-harness/prompts/vibe/phases/design.md) | Frontend code + Tailwind taste; uses `frontend-design` skill | `claude-sonnet-4-6` | Anthropic-curated skill expects Claude family; downgrade from Opus is fine |
| **backend** | [prompts/vibe/phases/backend.md](sopify-harness/prompts/vibe/phases/backend.md) | Express + Supabase + SQL | `moonshotai/kimi-k2.6` | Coding-strong OSS; 1/20th the cost of Opus |
| **improvement** | [prompts/vibe/phases/improvement.md](sopify-harness/prompts/vibe/phases/improvement.md) | Iterative refactor | `claude-sonnet-4-6` | Diff-aware edits benefit from tool-calling reliability |
| **security** | [prompts/vibe/phases/security.md](sopify-harness/prompts/vibe/phases/security.md) | `claude-code-security-review` skill | `claude-opus-4-7` | False negatives expensive; do not compromise |
| **approve** | [prompts/vibe/phases/approve.md](sopify-harness/prompts/vibe/phases/approve.md) | Handoff doc generation | `claude-haiku-4-5` | Cheap summary |

The simplest implementation is a `model` field on the phase descriptor in `_VIBE_BUILDING_PHASES` (see `_vibe_compose_system_prompt` in [web_server.py](sopify-harness/hermes_cli/web_server.py#L5484)) plus a passthrough to `pre_api_request`. See MODEL_SELECTION.md §6 for the migration steps.

### 15.3 Non-Vibe workloads

| Workload | Current behaviour | Proposed primary | Cost delta |
|---|---|---|---|
| `code-with-you` mode ([modes/code_with_you.py](sopify-harness/plugins/sopify_modes/code_with_you.py)) | Sonnet 4.6 | `moonshotai/kimi-k2.6` | −85% |
| `company-sop` mode ([modes/config.py](sopify-harness/plugins/sopify_modes/config.py)) | Haiku 4.5 | `qwen/qwen3.6-plus` | −50% + native Thai |
| `living-employee` mode ([modes/living.py](sopify-harness/plugins/sopify_modes/living.py)) | Haiku 4.5 | `qwen/qwen3.6-plus` | −50% |
| `/gs-mad` multi-agent skill | Opus 4.7 | `claude-sonnet-4-6` (default) or `deepseek/deepseek-v4-pro` (cost-tier) | −80% to −97% |
| Auxiliary slots (title gen, compression) | Inherits primary | `claude-haiku-4-5` pinned | Drops aux-slot spend to noise |

### 15.4 Failover behaviour

`ProviderRouter.pick()` already handles 1 h blacklist + cascade ([router.py:51](sopify-harness/plugins/sopify_providers/router.py#L51)). What's missing for an OSS-heavy default is a *capability-preserving* fallback — e.g. if the primary is `kimi-k2.6` (OpenRouter route) and OpenRouter 429s, the current code falls through to the entire Hermes default chain, which may pick something with weaker tool-calling. MODEL_SELECTION.md §5 proposes adding a tier-aware fallback (`primary OSS → equivalent OSS via different provider → Sonnet 4.6`) per scope.

### 15.5 What NOT to substitute

Three places where staying on Anthropic is the right call even at premium cost:

1. **`skills/frontend-design/`** — vendored verbatim from `anthropics/claude-code` ([SYSTEM_ARCHITECTURE.md rev 2.1 changes](#whats-new-in-rev-21-pr-featvibe-phase-prompts-and-supabase-2026-05-30)). Its aesthetic guide is calibrated against Claude; OSS models follow it with measurably lower fidelity (generic Inter/Roboto output recurs).
2. **Security review phase** — false negatives are unbounded liability; OSS models have shorter track records on this specific task class.
3. **`/gs-mad` runs needing 1 M context** — only Claude offers 1 M with maintained quality; DeepSeek/Qwen cap at 200 K–256 K.

### 15.6 Open questions before shipping

- **Pricing freshness** — numbers in MODEL_SELECTION.md are 2026-05 snapshots. Pin a refresh cadence (quarterly?) and a process for who updates it.
- **Picker UX** — flipping the default away from Opus is a breaking expectation change for users who've memorised the picker order. Surface a one-time announcement or banner.
- **Per-phase override telemetry** — once the phase machine pins per-phase models, the `/api/analytics/models` endpoint ([web_server.py:3315-3384](sopify-harness/hermes_cli/web_server.py#L3315)) should attribute spend by phase so we can verify the projected −70% to −80% holds in practice.

---

## Appendix A — File index (most-referenced)

| File | What |
|---|---|
| [sopify](sopify-harness/sopify) | Host-side launcher script |
| [hermes_constants.py](sopify-harness/hermes_constants.py) | `get_hermes_home()`, profile override |
| [hermes_cli/web_server.py](sopify-harness/hermes_cli/web_server.py) | 5897-LOC FastAPI dashboard server |
| [hermes_cli/dev_server_manager.py](sopify-harness/hermes_cli/dev_server_manager.py) | Per-session dev-server lifecycle: detect, kill, revive |
| [hermes_cli/encm_client.py](sopify-harness/hermes_cli/encm_client.py) | Dashboard → daemon proxy helper |
| [hermes_cli/pty_bridge.py](sopify-harness/hermes_cli/pty_bridge.py) | PTY-over-WS bridge |
| [hermes_state.py](sopify-harness/hermes_state.py) | SQLite schema + `get_messages_as_conversation` |
| [plugins/sopify_sandbox/sbx_launcher.py](sopify-harness/plugins/sopify_sandbox/sbx_launcher.py) | sbx orchestration + port publishing |
| [plugins/sopify_core/install.py](sopify-harness/plugins/sopify_core/install.py) | One-time install (Docker image, bridge, policy) |
| [sopify_daemon/app.py](sopify-harness/sopify_daemon/app.py) | ENCM daemon FastAPI app |
| [sopify_daemon/reconciler.py](sopify-harness/sopify_daemon/reconciler.py) | Periodic rule reconciliation |
| [tui_gateway/server.py](sopify-harness/tui_gateway/server.py) | JSON-RPC handlers + agent lifecycle |
| [tui_gateway/entry.py](sopify-harness/tui_gateway/entry.py) | Process entry, stdio transport |
| [tui_gateway/ws.py](sopify-harness/tui_gateway/ws.py) | WebSocket transport adapter |
| [web/src/App.tsx](sopify-harness/web/src/App.tsx) | Top-level routing, nav, layout |
| [web/src/main.tsx](sopify-harness/web/src/main.tsx) | Root render + provider tree |
| [web/src/lib/api.ts](sopify-harness/web/src/lib/api.ts) | REST API client |
| [web/src/lib/gatewayClient.ts](sopify-harness/web/src/lib/gatewayClient.ts) | WebSocket JSON-RPC client |
| [web/src/hooks/useChatStream.ts](sopify-harness/web/src/hooks/useChatStream.ts) | Chat transcript reducer |
| [web/src/pages/VibeCodePage.tsx](sopify-harness/web/src/pages/VibeCodePage.tsx) | Vibe Code flow |
| [web/src/components/vibe/ProjectView.tsx](sopify-harness/web/src/components/vibe/ProjectView.tsx) | Brainstorm / Planning / Building panes |
| [web/src/components/canvas/CanvasPanel.tsx](sopify-harness/web/src/components/canvas/CanvasPanel.tsx) | /panel Canvas with Static/Live mode + click-to-select |
| [web/vite.config.ts](sopify-harness/web/vite.config.ts) | Build + dev token injection |
| [prompts/vibe/base.md](sopify-harness/prompts/vibe/base.md) | Vibe agent base prompt |

## Appendix B — Glossary

- **AI-DLC** — AI-Driven Development Lifecycle. The Vibe Code six-step user journey.
- **ENCM** — Egress Network Control Module. Host-side daemon at `~/.sopify/` governing what the sandbox can reach.
- **sbx** — Docker Sandboxes CLI. The container runtime hosting Sopify.
- **sandboxd** — sbx's host-side daemon process (the thing ENCM daemon talks to over Unix socket).
- **sandbox** — A persistent microVM-style Docker container, one per cwd, name `sopify-<sha1(cwd)[:10]>`.
- **HERMES_HOME** — `~/.hermes/` by default. Hermes state root.
- **SOPIFY_HOME** — `~/.sopify/` by default. ENCM daemon home (different from HERMES_HOME).
- **Gateway sid** — 8-char hex from `uuid.uuid4().hex[:8]`. In-memory routing key for active gateway sessions.
- **Session key** — `YYYYMMDD_HHMMSS_xxxxxx`. Durable DB key for session rehydration via `session.resume`.
- **Mode** — Vibe Code theme (dashboard / form-registration / landing-page / web-app).
- **Add-on** — Vibe Code optional feature (auth-jwt / database-supabase / file-upload / schedule-job / qr-scan / dark-mode).
- **Phase** — Vibe Code lifecycle position (brainstorm → requirements → planning → development → improvement → security → approve).

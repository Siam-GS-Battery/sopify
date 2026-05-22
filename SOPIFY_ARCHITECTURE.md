# Sopify Architecture

Sopify is a governance + UX overlay on top of the **Hermes Agent runtime**.
Hermes is treated as a read-only upstream (REQ-0.3) — Sopify adds plugins,
sandboxing, branding, and an opinionated install path, but never modifies
Hermes' source.

For the Hermes runtime itself, see [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## 1. Layer cake

```
┌──────────────────────────────────────────────────────────────┐
│  User                                                        │
│  ────                                                        │
│  • Terminal (chat / mode slash commands)                     │
│  • Browser (dashboard at http://127.0.0.1:9119)              │
└─────────────────────────────┬────────────────────────────────┘
                              │ sopify dashboard
                              │ sopify chat
                              │ sopify /vibe | /living | /code-with-you
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  Host shim (~/.local/bin/sopify → ~/.sopify-app/sopify)      │
│  ─────────────────────────────────────────────────────────── │
│  • Pure Python entry-point (sopify-harness/sopify)           │
│  • Routes install / doctor / login on the host               │
│  • Every other subcommand → delegates to the sandbox         │
│  • Auto-opens browser when dashboard binds                   │
└─────────────────────────────┬────────────────────────────────┘
                              │ sbx create shell + sbx exec
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  Docker Sandboxes microVM (sbx)                              │
│  ─────────────────────────────                               │
│  • VT-x isolation (stronger than Docker containers)          │
│  • Image: sopify-sandbox:latest (Linux + Python 3.13 + Node) │
│  • Kit (infra/sbx/sopify-kit/spec.yaml):                     │
│      - 17 allowed domains (Anthropic, OpenRouter, GS, …)     │
│      - Env passthrough (ANTHROPIC_TOKEN, …)                  │
│      - Startup commands (symlink wrapper + auth/.env)        │
│  • Workspace mounts (host → microVM, same paths):            │
│      - <cwd>                       (rw)  — user's project    │
│      - ~/.sopify-app/              (ro)  — installed source  │
│      - ~/.hermes/                  (ro)  — credentials/.env  │
└─────────────────────────────┬────────────────────────────────┘
                              │ /usr/local/bin/sopify <argv>
                              │  (bash wrapper → venv python)
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  Hermes runtime (inside microVM)                             │
│  ────────────────────────────────                            │
│  • FastAPI dashboard (uvicorn on 0.0.0.0:9119)               │
│      - Port-published to host via `sbx ports --publish 9119` │
│  • PTY-bridged /chat tab (xterm.js ↔ /api/pty ↔ node TUI)    │
│  • tui_gateway subprocess (JSON-RPC over stdio)              │
│  • slash_workers (one per active session/model)              │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. Repository layout — what Sopify owns vs. what's inherited

```
sopify-harness/
├── sopify                              # host shim (Python entrypoint)
├── plugins/
│   ├── sopify_core/                    # banner, version, install, doctor
│   ├── sopify_sandbox/                 # sbx launcher + docker fallback
│   │   └── sbx_launcher.py             # ← spawns the microVM
│   ├── sopify_providers/               # auth.json + override logic
│   ├── sopify_modes/                   # /vibe, /living, /code-with-you
│   ├── sopify_guardrails/              # input/output filters
│   ├── sopify_otel/                    # telemetry exporter wiring
│   ├── sopify_skills/                  # skill discovery + governance
│   ├── sopify_tui/                     # banner injection into TUI
│   └── sopify_management/              # onboard / consent flow
│
├── infra/sbx/sopify-kit/spec.yaml      # sbx kit: net + env + startup
├── docker/sopify-sandbox/Dockerfile    # microVM image build recipe
│
├── web/                                # React/Vite dashboard frontend
│   └── src/pages/ChatPage.tsx          #   xterm.js + WebSocket /api/pty
├── ui-tui/                             # Ink-based terminal TUI (Node)
│
├── scripts/sopify-install.sh           # curl|bash one-liner installer
├── DESIGN_ARCHITECTURE.md              # 12-section requirements spec
└── SOPIFY_ARCHITECTURE.md              # this file
```

Everything **inherited from Hermes (read-only per REQ-0.3)**:
`hermes_cli/`, `agent/`, `tui_gateway/`, `tools/`, `providers/`, `gateway/`,
`acp_adapter/`, etc. Sopify never edits these — behavior is altered by
registering plugins that monkey-patch at runtime.

---

## 3. Boot sequence (browser path)

```
1.  user: $ sopify dashboard
2.  ~/.local/bin/sopify symlink → ~/.sopify-app/sopify
3.  Python shim: _cmd_dashboard() → injects --tui --host 0.0.0.0
                                    --insecure --no-open
4.  Shim → _delegate_to_hermes(argv, publish_ports=[9119])
5.  sopify_sandbox.sbx_launcher.spawn():
    a. sbx create shell <cwd> ~/.sopify-app:ro ~/.hermes:ro
                       --template sopify-sandbox:latest
                       --kit infra/sbx/sopify-kit
    b. sbx ports <SBX> --publish 9119:9119
    c. _open_browser_when_ready(9119)   # daemon thread polls TCP
    d. sbx exec -it <SBX> bash -lc "/usr/local/bin/sopify dashboard …"

6.  Inside microVM:
    - Kit startup symlinks /Users/<x>/.hermes/.env → ~/.hermes/.env
    - Hermes' env_loader reads .env → ANTHROPIC_TOKEN promoted
    - FastAPI binds 0.0.0.0:9119
    - tui_gateway + slash_worker(s) spawn

7.  Host browser opens http://127.0.0.1:9119
    - React frontend loads from /opt/sopify/hermes_cli/web_dist/
    - /chat tab opens WebSocket /api/pty?token=<session>
    - FastAPI auths, spawns `node ui-tui/dist/entry.js` in a PTY
    - PTY bytes ↔ WebSocket frames ↔ xterm.js
```

---

## 4. Credential flow

```
host: ~/.hermes/.env                # ANTHROPIC_TOKEN=sk-ant-… (real key)
                │
                │ sbx workspace mount (ro)
                ▼
microVM: /Users/<x>/.hermes/.env    # same path preserved by sbx
                │
                │ kit startup symlink
                ▼
microVM: /home/sopify/.hermes/.env  # where env_loader looks
                │
                │ Hermes' run_agent.py imports → load_dotenv(override=True)
                ▼
microVM: os.environ["ANTHROPIC_TOKEN"]  # available to slash_workers
```

A **separate** masking step in `plugins/sopify_providers/auth_override.py`
ensures the API key (sk-ant-api*) wins over any cached Claude Code OAuth
token by monkey-patching `agent.anthropic_adapter.read_claude_code_credentials`.

---

## 5. Network policy (kit-enforced)

`infra/sbx/sopify-kit/spec.yaml` declares the allowlist. sbx blocks
everything else at the microVM's egress.

```yaml
network:
  allowedDomains:
    # LLM providers
    - api.anthropic.com
    - openrouter.ai, *.openrouter.ai
    - api.novita.ai, *.novita.ai
    # GS Battery internal
    - *.gsbattery.local, *.gsbattery.co.th
    - otel-collector.gsbattery.local
    # Build tools
    - pypi.org, files.pythonhosted.org
    - registry.npmjs.org
    - api.github.com, raw.githubusercontent.com
```

To add a domain: edit `spec.yaml` → `sbx rm <SBX>` → `sopify dashboard`
recreates with new policy. IT can centrally manage this via the
Docker Admin Console (REQ-9.1).

---

## 6. Dashboard chat tab — three subsystems

```
Browser                Host                    microVM
───────                ────                    ───────
xterm.js  ──── WS ────────────────────►  FastAPI /api/pty
   │           (token auth + bytes)              │
   │                                             │ PtyBridge.spawn
   │                                             ▼
   │                                       node ui-tui/dist/entry.js
   │                                             │ stdio (pipe)
   │                                             ▼
   │                                       python -m tui_gateway.entry
   │                                             │ (JSON-RPC)
   │                                             ▼
   ◄──── ANSI render bytes ───── PTY ◄──   slash_worker(s)
                                                 │ (one per model)
                                                 ▼
                                          Anthropic / OpenRouter / …
```

- **TUI deps are pre-installed** in the Docker image (`npm install` + esbuild
  at build time). Without this, every first-launch sees `Installing TUI
  dependencies…` for 30-90s and the WebSocket races against the install.
- **Provider health**: each provider is marked unhealthy for 60s after a
  401/402. If all configured providers are unhealthy, chat goes silent
  with no visible error to the user. Check the dashboard stdout for
  `payment / credit error` lines.

---

## 7. Sopify-specific overlays (delta over Hermes)

| Hermes does                          | Sopify adds                                |
| :----------------------------------- | :----------------------------------------- |
| Generic agent runtime                | Three opinionated modes (`/vibe`, `/living`, `/code-with-you`) routed via `sopify_modes._activate()` |
| `~/.hermes/auth.json` API key store  | `~/.sopify/auth.json` override + key masking (Claude Code OAuth bypass) |
| Plain dashboard, dark theme          | Light theme `#1D63ED`, GS Battery sidebar logo, REQ-tagged subtitles |
| `docker run` for sandbox             | sbx microVM (VT-x), kit-managed network policy, IT-pushable |
| Per-call OTel emit                   | Mode-tagged spans + GS-internal exporter (`otel-collector.gsbattery.local`) |
| `pip install hermes-agent`           | `curl \| bash` installer that builds Docker image + installs sbx + login |
| Always-rebuild TUI on launch         | Pre-baked TUI bundle in the Docker image; first-launch is instant |

All overlays live in `plugins/sopify_*` and register via Hermes'
existing `register(ctx)` plugin hook.

---

## 8. Common pitfalls

| Symptom                                    | Likely cause                                                                  |
| :----------------------------------------- | :---------------------------------------------------------------------------- |
| `Installing TUI dependencies…` every boot  | Docker image rebuilt without the `npm install` step in ui-tui/                |
| Chat shows typed text but no response      | Provider unhealthy (no credit / bad key) — check log for `payment / credit`   |
| Chat tab blank, no banner                  | TUI process crashed; check `sbx exec <SBX> ps auxf` for `node dist/entry.js`  |
| Topbar still says "HERMES AGENT"           | Browser cache (Cmd+Shift+R) or web build fell back to stale dist              |
| `ANTHROPIC_API_KEY` is 13 chars in microVM | `~/.hermes/` not mounted — verify with `sbx exec <SBX> mount \| grep hermes`  |
| `ASGI: WebSocket not connected`            | Non-fatal Hermes race during first /chat connection; ignore once deps cached  |
| `sbx ls` shows stale sandbox name          | `sbx rm <name>` forces recreation with new kit/mount on next launch           |
| Edited a plugin but no effect              | Runtime uses `~/.sopify-app/` (a *copy*); `cp` your change there or reinstall |

---

## 9. Where to look first when debugging

| Need to                                   | Look at                                                  |
| :---------------------------------------- | :------------------------------------------------------- |
| Trace a sandbox boot                      | `plugins/sopify_sandbox/sbx_launcher.py:spawn()`         |
| Add a network domain                      | `infra/sbx/sopify-kit/spec.yaml` → `network.allowedDomains` |
| Change the install image contents         | `docker/sopify-sandbox/Dockerfile`                       |
| Tweak the host shim's dispatch            | `sopify-harness/sopify` (Python entry-point)             |
| Change the dashboard chat UI              | `web/src/pages/ChatPage.tsx`                             |
| Replace a TUI render component            | `ui-tui/src/components/` (Ink/React)                     |
| Adjust the credential masking             | `plugins/sopify_providers/auth_override.py`              |
| Update onboarding wording                 | `plugins/sopify_management/onboard.py`                   |

---

## 10. What's intentionally NOT here

- **OAuth flows for individual users.** Sopify is single-tenant per machine;
  org auth is enforced by the network policy + Docker Admin Console, not by
  per-request login.
- **Multi-sandbox orchestration.** One microVM per cwd (named via sha1(cwd)).
  Reuse is automatic; concurrent cwds get separate sandboxes.
- **A custom model proxy.** Sopify routes through Hermes' existing provider
  cascade — `anthropic` first, then `openrouter`, `novita`, etc. The
  cascade order is configured per-mode in `sopify_modes/profiles/`.
- **Modifications to Hermes core.** REQ-0.3 — every behavioral change goes
  through a plugin hook or runtime monkey-patch.

---

## 11. Two-file install vs. source-repo edits

There are **two copies** of the Sopify source on a developer machine:

| Path                                                         | Role                                              |
| :----------------------------------------------------------- | :------------------------------------------------ |
| `~/ai_engineer/gs/project-based/sopify/sopify-harness/`      | Source repo (git-tracked). What you edit.         |
| `~/.sopify-app/`                                             | Runtime copy. What `sopify` actually executes.    |
| `~/.local/bin/sopify` → `~/.sopify-app/sopify`               | Symlink installed by `scripts/sopify-install.sh`. |

When you edit a plugin or kit file in the source repo, the change is
**not active** until you sync it to `~/.sopify-app/`. Either:

```bash
# fast sync (specific files)
cp <repo>/path/to/file ~/.sopify-app/path/to/file

# full reinstall (re-runs `sopify install` + Docker rebuild)
~/ai_engineer/.../scripts/sopify-install.sh
```

Forgetting this is the #1 source of "I changed it but nothing happened"
during development.

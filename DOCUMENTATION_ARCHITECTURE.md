# Documentation Architecture — Sopify Codebase Reading Guide

> **วัตถุประสงค์:** เอกสารนี้ใช้เปิดอ่านโค้ดตามลำดับ ไม่ใช่ spec ของ feature
> ทุกหัวข้อระบุ `path:line` ของฟังก์ชันสำคัญเพื่อกระโดดเข้าไปอ่านได้ทันที
>
> **อ่านเรียงตามลำดับ §1 → §11** เพื่อเข้าใจระบบทั้งภาพรวมและ flow รันจริง
>
> เอกสารคู่กัน:
> - [DESIGN_ARCHITECTURE.md](DESIGN_ARCHITECTURE.md) — SRS / requirements (REQ-0..REQ-11)
> - [SOPIFY_ARCH.md](SOPIFY_ARCH.md) — สรุป architecture สั้น 1 หน้า
> - [MANUAL.md](MANUAL.md) — user manual (วิธีใช้)
> - [ARCHITECTURE.md](ARCHITECTURE.md) — Hermes core (runtime ที่ Sopify ซ้อนทับ)

---

## §1. ภาพรวมระบบ (One-paragraph mental model)

**Sopify = Hermes runtime + Docker sandbox + 3 modes + org governance**
ทุก feature ของ Sopify อยู่ใน `plugins/sopify_*` (snake_case) — *ห้ามแก้* Hermes core
(ไฟล์อื่นทั้งหมด) เพื่อรักษา upgrade path กับ upstream Hermes

```
host (Mac/Linux/Windows)
   │
   ▼
sopify (bash wrapper, /usr/local/bin/sopify หรือ ~/.local/bin/sopify)
   │
   ▼ resolve via realpath → ~/.sopify-app/sopify (symlink → harness dir)
   │
   ├── sopify install / doctor / --version       → รันบน host
   ├── sopify dashboard / chat / /vibe / ...     → spawn microVM (sbx) แล้วรันใน sandbox
   ▼
sbx microVM (VT-x) — image: sopify-sandbox:latest
   │
   ├── /opt/sopify         (source baked-in จาก docker build, read-write owned by sopify user)
   ├── /workspace          (mount cwd ของ host, rw)
   ├── /Users/.../.hermes  (mount ~/.hermes, ro)
   └── /usr/local/bin/sopify  (wrapper → /opt/sopify/.venv/bin/python /opt/sopify/sopify)
        │
        ▼
   /opt/sopify/sopify (same Python shim)
        │
        ├── sopify dashboard → spawn FastAPI (hermes_cli web_server) บน :9119
        │     │
        │     ├── web_dist/ static → React dashboard (sidebar + pages)
        │     └── /api/* → backend operations (sessions/models/config/...)
        │           └── /chat tab → spawn node PTY → ui-tui/dist/entry.js (ink TUI)
        │                 └── WebSocket back to browser → xterm.js
        │
        └── sopify chat → run hermes_cli TUI ตรงๆ (no FastAPI)
```

---

## §2. โครงสร้าง Top-level (Directory map)

| Path | บทบาท |
|---|---|
| [`sopify`](sopify) | Python launcher shim (entry point) |
| [`cli.py`](cli.py) | Hermes-era CLI entry (4700+ lines) — Sopify ยังใช้บางส่วน |
| [`sopify-runtime.py`](sopify-runtime.py) | Linux runtime entry (เรียกจาก entrypoint.sh) |
| [`pyproject.toml`](pyproject.toml) | Python deps (exact-pinned) |
| [`docker/sopify-sandbox/`](docker/sopify-sandbox/) | Dockerfile + entrypoint สำหรับ sandbox image |
| [`infra/sbx/sopify-kit/`](infra/sbx/sopify-kit/) | sbx kit spec (network allowedDomains) |
| [`plugins/sopify_*/`](plugins/) | Sopify-specific plugins (9 ตัว — ดู §9) |
| [`plugins/<หลายตัว>/`](plugins/) | Hermes core plugins (browser, kanban, memory, ...) — *ห้ามแก้* |
| [`hermes_cli/`](hermes_cli/) | Hermes CLI + FastAPI web_server + บรรจุ web_dist/ |
| [`hermes_cli/web_dist/`](hermes_cli/web_dist/) | ผลลัพธ์ web build (committed) — served เป็น static |
| [`web/`](web/) | React dashboard source (Vite + Tailwind 4) |
| [`ui-tui/`](ui-tui/) | TUI source (React + ink, custom @hermes/ink fork) |
| [`ui-tui/dist/entry.js`](ui-tui/dist/entry.js) | Bundle output (esbuild) — รัน ใน node ใน sandbox |
| [`agent/`](agent/) | Hermes agent core (rate limit, model routing) |
| [`tools/`](tools/) | Tool definitions (skills, web search, ฯลฯ) |
| [`skills/`](skills/) | Hermes skills (โหลด lazily) |
| [`tests/`](tests/) | pytest suites |
| [`scripts/`](scripts/) | install scripts (install.sh / install.ps1) |
| [`assets/`](assets/) | Brand assets (rhino-icon.png, banner.png) |

---

## §3. Entry point — `sopify` shim ([`sopify`](sopify))

> **อ่านไฟล์นี้ก่อนเป็นอันดับแรก** — ทุก command เข้าทางนี้

### 3.1 Resolve install path ([sopify:21-24](sopify#L21-L24))
```python
ROOT = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, ROOT)
```
ใช้ `realpath` เพื่อ resolve symlink — `~/.local/bin/sopify` → `~/.sopify-app/sopify` (symlink) → repo จริง

### 3.2 Banner ([sopify:27-34](sopify#L27-L34))
`_show_banner()` import `plugins.sopify_core.banner` แล้วเรียก `banner.render()` — ดู §8

### 3.3 Command dispatch ([sopify:266-298](sopify#L266-L298))
| Subcommand | Function | รันที่ไหน |
|---|---|---|
| `--version` | [`_cmd_version`](sopify#L67) | host |
| `install` | [`_cmd_install`](sopify#L76) | host |
| `doctor` | [`_cmd_doctor`](sopify#L85) | host |
| `dashboard` | [`_cmd_dashboard`](sopify#L167) | **sandbox** (publish 9119) |
| `chat` | [`_cmd_chat`](sopify#L199) | sandbox |
| `login`/`logout` | [`_cmd_login`](sopify#L205)/[`_cmd_logout`](sopify#L214) | host |
| `env` | [`_cmd_env`](sopify#L225) | host |
| `onboard` | [`_cmd_onboard`](sopify#L237) | host |
| `/vibe`/`/living`/`/code-with-you` | [`_cmd_mode`](sopify#L245) | sandbox |
| อื่นๆ | [`_delegate_to_hermes`](sopify#L120) | sandbox ถ้ามี sbx ไม่งั้น host |

### 3.4 Sandbox routing decision ([sopify:120-149](sopify#L120-L149))
- ถ้า `_sbx_available()` (sbx installed + logged in) → ไปทาง [`plugins.sopify_sandbox.sbx_launcher.spawn()`](plugins/sopify_sandbox/sbx_launcher.py#L251)
- ไม่งั้น fallback → preload plugins แล้วเรียก [`hermes_cli.main.main()`](hermes_cli/main.py) บน host ตรงๆ
- `SOPIFY_NO_SBX=1` บังคับ host fallback

### 3.5 ตัว wrapper สองชั้น
- **บน host:** `~/.local/bin/sopify` (bash script จาก `scripts/install.sh`) → exec venv python + `sopify` script
- **ใน sandbox:** `/usr/local/bin/sopify` (bash script จาก Dockerfile [docker/sopify-sandbox/Dockerfile:87-91](docker/sopify-sandbox/Dockerfile#L87-L91)) → exec `/opt/sopify/.venv/bin/python /opt/sopify/sopify`

---

## §4. Sandbox layer — `plugins/sopify_sandbox/`

> **flow ลำดับยาวสุดในระบบ — อ่านที่นี่ทั้งหมดถ้าจะ debug deployment**

### 4.1 sbx (Docker Sandboxes microVM) vs docker
- `sbx` = microVM (VT-x) จาก Docker Sandboxes — secure isolation
- ถ้า host มี `sbx` + login แล้ว → ใช้ทาง `sbx_launcher.py` (default path)
- ถ้าไม่มี → ใช้ทาง `launcher.py` (docker run ปกติ) เป็น fallback
- ตรวจที่ [sbx_launcher.is_available()](plugins/sopify_sandbox/sbx_launcher.py#L53) + [is_logged_in()](plugins/sopify_sandbox/sbx_launcher.py#L76)

### 4.2 `spawn()` flow ([sbx_launcher.py:251-359](plugins/sopify_sandbox/sbx_launcher.py#L251-L359))
1. ตรวจ sbx availability + login
2. คำนวณ `cwd` + `app_root` (=[_sopify_app_root()](plugins/sopify_sandbox/sbx_launcher.py#L58) → repo root)
3. กำหนด workspaces list: `cwd:rw`, `app_root:ro`, `~/.hermes:ro`
4. [`_ensure_sandbox()`](plugins/sopify_sandbox/sbx_launcher.py#L189) — สร้าง sandbox ถ้ายังไม่มี
5. [`_link_hermes_into_sandbox()`](plugins/sopify_sandbox/sbx_launcher.py#L216) — symlink `~/.hermes` เข้า home ของ sopify user
6. [`_publish_port()`](plugins/sopify_sandbox/sbx_launcher.py#L208) — ผูก port (เช่น 9119 สำหรับ dashboard)
7. [`_open_browser_when_ready()`](plugins/sopify_sandbox/sbx_launcher.py#L146) — รอ port เปิดแล้วเปิด browser
8. ประกอบ `inner_cmd` — export env vars + invoke `/usr/local/bin/sopify`
9. `sbx exec -it <sandbox> bash -lc <inner_cmd>` → รันใน microVM

### 4.3 Sandbox naming ([sbx_launcher.py:104-108](plugins/sopify_sandbox/sbx_launcher.py#L104-L108))
```python
def _sandbox_name_for_cwd() -> str:
    h = hashlib.sha1(str(Path.cwd()).encode()).hexdigest()[:10]
    return f"sopify-{h}"
```
→ sandbox 1 ตัวต่อ cwd → `sopify chat` ซ้ำใน dir เดิม reuse sandbox เดิม

### 4.4 Critical env exports ใน `inner_cmd` ([sbx_launcher.py:341-352](plugins/sopify_sandbox/sbx_launcher.py#L341-L352))
```python
"export COLORTERM=truecolor; "       # rich 24-bit color (ไม่งั้นแรดซีดเทา)
"export TERM=xterm-256color; "       # ไม่งั้น TERM=dumb → rich strip color
"export no_proxy=...; "              # ข้าม Docker MCP gateway
'if [ "$ANTHROPIC_API_KEY" = "proxy-managed" ]; then unset ...; fi; '
"/usr/local/bin/sopify <argv>"
```

### 4.5 ทำไม mount harness แต่ยังใช้โค้ดเก่า
- `app_root:ro` mount เข้า microVM แต่ไม่มีใครอ่าน — wrapper hardcode `/opt/sopify`
- โค้ดที่ runtime ใช้ทั้งหมดมาจาก **baked image** (Dockerfile copy ตอน build)
- → แก้โค้ดที่รันใน sandbox ต้อง rebuild image เสมอ (ดู §11)

---

## §5. Docker image — `docker/sopify-sandbox/`

### 5.1 Dockerfile flow ([docker/sopify-sandbox/Dockerfile](docker/sopify-sandbox/Dockerfile))
| Stage | บรรทัด | ทำอะไร |
|---|---|---|
| Base | [`L11-L13`](docker/sopify-sandbox/Dockerfile#L11) | debian:13.4-slim + uv 0.11.6 |
| OS deps | [`L25-L31`](docker/sopify-sandbox/Dockerfile#L25) | tini, git, node, python, ripgrep, ffmpeg |
| User | [`L38`](docker/sopify-sandbox/Dockerfile#L38) | สร้าง `sopify` uid=10001 (non-root, REQ-11.4) |
| Source | [`L49`](docker/sopify-sandbox/Dockerfile#L49) | `COPY . /opt/sopify` (build context = harness root) |
| Python venv | [`L60-L64`](docker/sopify-sandbox/Dockerfile#L60) | `uv sync --extra web --extra cli --extra anthropic --extra pty` |
| TUI deps | [`L72-L75`](docker/sopify-sandbox/Dockerfile#L72) | `npm install` ใน `ui-tui/` + `ui-tui/packages/hermes-ink/` |
| TUI bundle | [`L79`](docker/sopify-sandbox/Dockerfile#L79) | `node scripts/build.mjs` → `ui-tui/dist/entry.js` |
| Wrapper | [`L87-L91`](docker/sopify-sandbox/Dockerfile#L87) | สร้าง `/usr/local/bin/sopify` (bash + venv python) |
| Mountpoints | [`L94-L95`](docker/sopify-sandbox/Dockerfile#L94) | mkdir + chown `/workspace /sopify-auth /sopify-config /sopify-sessions` |
| Smoke test | [`L101-L107`](docker/sopify-sandbox/Dockerfile#L101) | import yaml/fastapi/anthropic/ptyprocess + version smoke |
| Entry | [`L114-L115`](docker/sopify-sandbox/Dockerfile#L114) | `tini -- bash` |

### 5.2 entrypoint.sh ([docker/sopify-sandbox/entrypoint.sh](docker/sopify-sandbox/entrypoint.sh))
ไม่ใช้ใน sbx path (sbx เรียก `/usr/local/bin/sopify` ตรงๆ ผ่าน `sbx exec`) — ใช้ตอน `docker run` แบบ standalone เท่านั้น

### 5.3 sbx kit ([infra/sbx/sopify-kit/spec.yaml](infra/sbx/sopify-kit/spec.yaml))
- `network.allowedDomains` — egress whitelist (api.anthropic.com, otel-collector.gsbattery.local, *.gsbattery.local, ฯลฯ)
- `env:` block — **silently ignored** โดย sbx schema v1 — เลยต้อง export env vars ใน `inner_cmd` แทน (ดู §4.4)

---

## §6. Install + Doctor — `plugins/sopify_core/`

### 6.1 `install.run()` ([install.py:185-200](plugins/sopify_core/install.py#L185-L200))
ลำดับ steps:
1. [`_require_docker()`](plugins/sopify_core/install.py#L45) — ตรวจ Docker daemon
2. [`_ensure_image()`](plugins/sopify_core/install.py#L62) — pull/build `sopify-sandbox:latest`
   - **ถ้า image มีอยู่แล้วจะข้าม build** — ใช้ `--rebuild` flag หรือลบ image ก่อนถึงจะ rebuild ใหม่
   - Build command: `docker build -t sopify-sandbox:latest -f docker/sopify-sandbox/Dockerfile <repo_root> --quiet`
3. [`_sync_image_to_sbx()`](plugins/sopify_core/install.py#L97) — `docker save | sbx template load` — sbx มี image store แยกจาก host docker
4. [`_ensure_network()`](plugins/sopify_core/install.py#L135) — สร้าง bridge `sopify-net` ถ้ายังไม่มี
5. [`_write_default_policy()`](plugins/sopify_core/install.py#L152) — เขียน `~/.sopify/network-policy.json`
6. [`_activate_plugins()`](plugins/sopify_core/install.py#L201) + [`_validate_sbx_kit()`](plugins/sopify_core/install.py#L213)
7. [`_emit_install_event()`](plugins/sopify_core/install.py#L168) — OTel event `install_complete`

### 6.2 `doctor` ([plugins/sopify_core/doctor.py](plugins/sopify_core/doctor.py))
5-row health report: docker / sandbox-image / sandbox-net / auth / otel — ต้องเสร็จ < 3s (Gate P2)

### 6.3 Version ([plugins/sopify_core/version.py](plugins/sopify_core/version.py))
`full_version_string()` → `"sopify {SOPIFY_VERSION} (runtime {HERMES_VERSION})"`

---

## §7. Web Dashboard — `web/` → `hermes_cli/web_dist/`

### 7.1 Build pipeline
```
web/src/**/*.tsx (React 18)
       │
       ▼ vite build (outDir = ../hermes_cli/web_dist)
hermes_cli/web_dist/
       ├── index.html  (favicon: /rhino-icon.png)
       ├── rhino-icon.png  (copy จาก web/public/)
       ├── sopify-logo.png
       ├── favicon.ico
       ├── fonts/, fonts-terminal/
       └── assets/
            ├── index-<hash>.js     ← React bundle (1.6 MB)
            ├── index-<hash>.css    ← Tailwind 4
            └── ฯลฯ
```

### 7.2 Serving
[`hermes_cli/web_server.py`](hermes_cli/web_server.py) — FastAPI mount `web_dist/` เป็น StaticFiles + `/api/*` routes

### 7.3 Pages ([web/src/pages/](web/src/pages/))
| Path | บทบาท |
|---|---|
| [`ChatPage.tsx`](web/src/pages/ChatPage.tsx) | tab `/chat` — embed TUI ผ่าน xterm.js + WebSocket |
| [`SessionsPage.tsx`](web/src/pages/SessionsPage.tsx) | tab `/sessions` — list + search + expand session messages |
| [`ModelsPage.tsx`](web/src/pages/ModelsPage.tsx) | `/models` — provider chain config |
| [`SkillsPage.tsx`](web/src/pages/SkillsPage.tsx) | skill registry browser |
| [`PluginsPage.tsx`](web/src/pages/PluginsPage.tsx) | enabled plugins toggle |
| [`ConfigPage.tsx`](web/src/pages/ConfigPage.tsx) | settings.json editor |
| [`LogsPage.tsx`](web/src/pages/LogsPage.tsx) | tail recent logs |
| [`CronPage.tsx`](web/src/pages/CronPage.tsx) | scheduled jobs (Hermes routines) |
| [`ProfilesPage.tsx`](web/src/pages/ProfilesPage.tsx) | role profile (user/dev) |
| [`EnvPage.tsx`](web/src/pages/EnvPage.tsx) | API keys management |
| [`DocsPage.tsx`](web/src/pages/DocsPage.tsx) | embedded markdown docs |
| [`AnalyticsPage.tsx`](web/src/pages/AnalyticsPage.tsx) | usage charts |

### 7.4 Empty-state mascot (recent)
`SessionsPage` ตอนยังไม่มี session → แสดง `<img src="/rhino-icon.png" class="animate-float">` ([SessionsPage.tsx:783-801](web/src/pages/SessionsPage.tsx#L783-L801))
- keyframe `sopify-float` ใน [index.css](web/src/index.css#L357-L364) — translateY ±8px ทุก 3s
- `image-rendering: pixelated` เพื่อให้ pixel art ไม่เบลอ

### 7.5 Theme tokens ([web/src/index.css](web/src/index.css))
ดู [CSS_STYLE.md](../CSS_STYLE.md) — CSS variables ใน `:root` mirror เข้า Tailwind config

---

## §8. Banner pipeline (4 จุดที่เรนเดอร์)

> ดูประวัติของ "ทำไมต้อง render หลายที่" — banner ปรากฏใน 4 contexts แยกกัน

### 8.1 Host CLI banner (Python + rich)
- **เรนเดอร์ที่:** ตอน `sopify install` / `doctor` / `dashboard` / `chat` / ฯลฯ บน host
- **โค้ด:** [`plugins/sopify_core/banner.py`](plugins/sopify_core/banner.py)
  - `SOPIFY_WORDMARK` [L31-L50](plugins/sopify_core/banner.py#L31-L50) — ASCII "SOPIFY AI" 20 บรรทัด (6 cyan shades)
  - `SOPIFY_CADUCEUS` [L15-L25](plugins/sopify_core/banner.py#L15-L25) — pixel rhino 7 บรรทัด × 14 cols (half-block compressed)
  - [`render()`](plugins/sopify_core/banner.py#L134) — wordmark + Rich Panel + grid (mascot ซ้าย / info ขวา)
- **Fallback ตอนไม่มี rich:** [`_render_rich_ansi()`](plugins/sopify_core/banner.py#L78) — regex parse `[#fg on #bg]` → emit `\x1b[38;2;…m` + `\x1b[48;2;…m`

### 8.2 Sandbox CLI banner (เหมือน 8.1 แต่ใน sandbox)
- ตอน `sopify dashboard` mountup, `/usr/local/bin/sopify` ใน sandbox เรียก `_show_banner()` อีกครั้ง
- ใช้ **baked-in** `plugins/sopify_core/banner.py` (จาก image) — ไม่ใช่ host code
- หลัก ๆ ที่เคยซีดเทา: [`COLORTERM=truecolor`](plugins/sopify_sandbox/sbx_launcher.py#L341) ใน inner_cmd ต้องตั้ง

### 8.3 hermes_cli banner (Python + rich)
- [`hermes_cli/banner.py`](hermes_cli/banner.py) — มี `HERMES_CADUCEUS` + `HERMES_TEXT_LOGO`
- เรนเดอร์ตอน `sopify chat` (terminal TUI fallback)

### 8.4 ink TUI banner (TypeScript)
- รัน ใน node ใน sandbox, เรนเดอร์ผ่าน xterm.js ใน browser tab `/chat`
- **โค้ด:**
  - [`ui-tui/src/banner.ts`](ui-tui/src/banner.ts) — `PIXEL_RHINO`, `HERMES_TEXT_LOGO`, `parseRichMarkup()`
  - `Segment = [fg, text, bg?]` — bg อยู่ตำแหน่ง 3 (optional)
  - [`logo()`](ui-tui/src/banner.ts#L131-L132) + [`caduceus()`](ui-tui/src/banner.ts#L134-L135) — return DEFAULT_*_ROWS ตรงๆ (ไม่ผ่าน `themed()` เพื่อไม่ collapse 5 colors → 3 theme tokens)
- **Components:** [`ui-tui/src/components/branding.tsx`](ui-tui/src/components/branding.tsx)
  - [`ArtLines`](ui-tui/src/components/branding.tsx#L31) — ตัวเรนเดอร์ rows ของ rich markup → `<Text color bg>`
  - [`Banner`](ui-tui/src/components/branding.tsx#L46) — wordmark + tagline
  - [`SopifyInfoPanel`](ui-tui/src/components/branding.tsx#L72) — panel `☤ Sopify ☤` + mascot ซ้าย + version/tagline/subtitle/REQ list ขวา
  - [`SessionPanel`](ui-tui/src/components/branding.tsx#L131) — collapsible tools/skills/MCP (ซ่อน default, เปิดด้วย `SOPIFY_SHOW_SESSION_PANEL=1`)

### 8.5 Web BrandHero (React) [legacy, ตอนนี้แทนด้วย img แล้ว]
- [`web/src/components/BrandHero.tsx`](web/src/components/BrandHero.tsx) — pixel rhino + wordmark เป็น inline-styled `<pre>` (เคยใช้ใน SessionsPage empty state)
- ปัจจุบัน SessionsPage เปลี่ยนไปใช้ `<img src="/rhino-icon.png">` แทน

### 8.6 Mascot color encoding (5 colors via half-blocks)
- 14×14 logical pixel grid → 7×14 chars ผ่าน Unicode `▀`/`▄`/`█`
- แต่ละ `▀` cell: foreground = สีบน, background = สีล่าง
- Palette:
  - `#164E63` — dark navy outline
  - `#22D3EE` — teal (ear inside, body accent)
  - `#67E8F9` — cyan light (body main)
  - `#0891B2` — dark cyan (shadow/eye)
  - `#F9A8D4` — pink (cheeks)

---

## §9. Plugin system — `plugins/sopify_*/`

ทุก plugin มี `plugin.yaml` + `__init__.py` (entry) + `README.md` + `tests/`

| Plugin | REQ | บทบาท |
|---|---|---|
| [`sopify_core`](plugins/sopify_core/) | REQ-0 | bootstrap, version, doctor, install, banner |
| [`sopify_sandbox`](plugins/sopify_sandbox/) | REQ-1 | sbx_launcher + docker launcher + network policy v1 |
| [`sopify_encm`](plugins/sopify_encm/) | REQ-ENCM-M1 | External Network Control Module — layer-7 forward proxy, schema v2, audit log |
| [`sopify_providers`](plugins/sopify_providers/) | REQ-2 | ProviderRouter cascade (Anthropic → OpenRouter → ...) + auth |
| [`sopify_modes`](plugins/sopify_modes/) | REQ-3/4/5 | /vibe, /living, /code-with-you mode profiles |
| [`sopify_guardrails`](plugins/sopify_guardrails/) | REQ-6 | HARD_DENY / SOFT_DENY patterns + role enforcement |
| [`sopify_otel`](plugins/sopify_otel/) | REQ-7 | 5-event audit pipeline (api_request, tool_decision, ...) |
| [`sopify_skills`](plugins/sopify_skills/) | REQ-8 | company-sop / mode-specific skill injection |
| [`sopify_management`](plugins/sopify_management/) | REQ-9 | IT-managed settings, onboard flow |
| [`sopify_tui`](plugins/sopify_tui/) | REQ-10 | TUI overlay (mode/quota chip) |

### §9.1 sopify_encm internals (M1)

ENCM เป็น layer-7 forward proxy แยกออกมาเป็น container ของตัวเอง ดู [docs/sopify/REQ-ENCM-M1.md](docs/sopify/REQ-ENCM-M1.md) สำหรับ spec เต็ม

```
plugins/sopify_encm/
├── __init__.py
├── plugin.yaml
├── schema.py               ← Pydantic v2 — NetworkPolicy + Rule discriminated union
├── migration.py            ← v1 → v2 upgrader (idempotent)
├── ca.py                   ← self-signed CA generator (5y, RSA 4096)
├── proxy/
│   ├── __init__.py
│   └── http_proxy.py       ← mitmproxy addon (request + response hooks)
├── rules/
│   ├── __init__.py
│   ├── matcher.py          ← rule lookup (domain/port/method/path)
│   ├── rate_limiter.py     ← sliding window 60s per (rule_id, src)
│   └── store.py            ← file-watched PolicyStore for hot-reload
├── audit/
│   ├── __init__.py
│   ├── writer.py           ← JSONL append + UTC date rotation
│   └── rotator.py          ← purge files older than retention_days
└── tests/                  ← 74 tests covering schema/migration/matcher/audit/CA
```

**Key flows:**
- **HTTPS request** ใน sandbox → `HTTPS_PROXY` env → ENCM container :3128 → mitmproxy `request` hook → `RuleMatcher.evaluate_http()` → allow + forward / 403 deny → response hook → audit log
- **CA cert chain:** [`ca.generate_ca()`](plugins/sopify_encm/ca.py) สร้างใน `~/.sopify/encm-ca/` → mount เข้า sandbox `/sopify-encm-ca:ro` → [`install-sopify-ca.sh`](docker/sopify-sandbox/install-sopify-ca.sh) คัดลอกเข้า system trust store → sandbox trust ENCM cert
- **Policy hot-reload:** [`PolicyStore`](plugins/sopify_encm/rules/store.py) poll mtime ทุก 1s — edit `~/.sopify/network-policy.json` → matcher reload ใหม่ทันทีไม่ต้อง restart ENCM

Plugin loading: [`sopify` shim _preload_sopify_plugins()](sopify#L152) iterate `plugins/sopify_*/` แล้ว `importlib.import_module()`

---

## §10. Configuration files

| File | Owner | Mode | Purpose |
|---|---|---|---|
| `~/.sopify/auth.json` | user | 0600 | API keys |
| `~/.sopify/settings.json` | IT (MDM) | 0444 | provider chain, OTel endpoint, daily budgets |
| `~/.sopify/profile.json` | IT | 0444 | role (`user`/`dev`) |
| `~/.sopify/network-policy.json` | merged | 0644 | egress rules (schema v2 — protocol/domain/port/method/path/rate limit per rule) |
| `~/.sopify/encm-ca/ca.key` | user | 0600 | ENCM CA private key (RSA 4096, valid 5 yrs) |
| `~/.sopify/encm-ca/ca.crt` | user | 0644 | ENCM CA public cert — mounted ro into sandbox + Docker container |
| `~/.sopify/audit-log/YYYY-MM-DD.jsonl` | user | 0644 | ENCM audit log, daily rotation, 30-day retention |
| `~/.sopify/sessions/` | user | 0700 | /living session DB (SQLite WAL) |
| `~/.hermes/.env` | user | 0600 | Hermes-era env vars (ANTHROPIC_TOKEN, ...) — mounted ro ใน sandbox |

Mount mapping ใน sandbox:
- `~/.sopify/auth.json` → `/sopify-auth` (ro)
- `~/.sopify/settings.json` → `/sopify-config` (ro)
- `~/.sopify/sessions/` → `/sopify-sessions` (rw)
- `~/.hermes` → host abs path (ro) — linked เข้า `$HOME/.hermes` ของ sopify user โดย [`_link_hermes_into_sandbox()`](plugins/sopify_sandbox/sbx_launcher.py#L216)

---

## §11. Rebuild workflow — แก้อะไรต้อง rebuild อะไร

> ดูประวัติเก่า ปัญหา "แก้โค้ดแล้วใน sandbox ไม่เห็น" เกิดเพราะ baked image

| แก้ที่ | ต้องทำ |
|---|---|
| `plugins/sopify_core/banner.py` (host banner) | ไม่ต้อง rebuild — host เรียก `plugins.sopify_core.banner` ผ่าน symlink `~/.sopify-app` |
| `plugins/sopify_core/banner.py` (sandbox banner) | **rebuild image + sync sbx + ลบ sandbox เก่า** |
| `plugins/sopify_sandbox/sbx_launcher.py` | ไม่ต้อง rebuild — รันบน host เสมอ |
| `web/src/**/*.tsx` | `cd web && npm run build` → `hermes_cli/web_dist/` → **rebuild image** |
| `ui-tui/src/**/*.tsx` | `cd ui-tui && npm run build` → `dist/entry.js` → **rebuild image** |
| `docker/sopify-sandbox/Dockerfile` | **rebuild image** |
| `hermes_cli/*.py` | **rebuild image** |
| `pyproject.toml` deps | **rebuild image** (uv sync layer cache miss → ช้า ~60-90s) |

### Full rebuild commands
```bash
# 1. Rebuild web (~2s)
cd web && npm run build

# 2. Rebuild TUI bundle (~100ms)
cd ../ui-tui && npm run build

# 3. Rebuild docker image (~30s with cache, ~3-5min cold)
cd .. && docker build -t sopify-sandbox:latest -f docker/sopify-sandbox/Dockerfile .

# 4. Sync to sbx template store
docker save -o /tmp/sopify-sandbox.tar sopify-sandbox:latest
sbx template load /tmp/sopify-sandbox.tar
rm /tmp/sopify-sandbox.tar

# 5. Remove stale sandboxes (sandbox สร้างจาก image เก่ายังคงอยู่)
sbx ls
sbx rm <name> --force
```

ใช้ `sopify install --rebuild` ทำขั้นตอน 3+4 อัตโนมัติ (แต่ไม่ลบ sandbox เก่าให้ — ต้องทำเอง)

---

## §12. Reading order recommendation

1. **เริ่มที่ §1-2** เพื่อรู้ภาพรวม + map directory
2. **อ่าน [`sopify`](sopify) ตรงๆ** (300 บรรทัด) — entry shim — เข้าใจ command dispatch
3. **อ่าน §3-5** เพื่อตามรอย flow `sopify dashboard` ตั้งแต่ launch จนถึงรันใน sandbox
4. **อ่าน §6** สำหรับ install/doctor (host-side commands)
5. **อ่าน §7** สำหรับ web dashboard (frontend)
6. **อ่าน §8** ถ้าจะแตะ banner หรือ branding (ระวัง 4 จุดเรนเดอร์)
7. **อ่าน §9** สำหรับ plugin internals — ดู `plugin.yaml` ของแต่ละตัว
8. **อ่าน §10-11** ก่อนแก้โค้ดจริงเพื่อรู้ว่าต้อง rebuild อะไรบ้าง

ถ้าจะ debug bug เฉพาะจุด — ดู `path:line` ที่ตารางแต่ละ section จะกระโดดได้เร็ว

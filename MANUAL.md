# Sopify — User Manual

> **คู่มือใช้งานสำหรับ end user + developer**
>
> สำหรับเอกสารสายโครงสร้างโค้ด ดู [DOCUMENTATION_ARCHITECTURE.md](DOCUMENTATION_ARCHITECTURE.md)
> สำหรับ requirements ดู [DESIGN_ARCHITECTURE.md](DESIGN_ARCHITECTURE.md)

---

## สารบัญ

1. [Sopify คืออะไร](#1-sopify-คืออะไร)
2. [Prerequisites](#2-prerequisites)
3. [ติดตั้ง (First-time install)](#3-ติดตั้ง-first-time-install)
4. [คำสั่งที่ใช้บ่อย](#4-คำสั่งที่ใช้บ่อย)
5. [Dashboard (Web UI) — แนะนำสำหรับผู้ใช้ทั่วไป](#5-dashboard-web-ui)
6. [Terminal modes — สำหรับ power user](#6-terminal-modes)
7. [การจัดการ session](#7-การจัดการ-session)
8. [API keys + credentials](#8-api-keys--credentials)
9. [Troubleshooting](#9-troubleshooting)
10. [สำหรับ developer — แก้โค้ดแล้ว rebuild](#10-สำหรับ-developer)

---

## 1. Sopify คืออะไร

**Sopify** = AI agent + Docker sandbox + 3 working modes + org governance สำหรับ GS Battery

จุดต่างจาก Hermes (runtime ใต้ก้น):
- **Sandbox ฝังตัว** — ทุก command รันใน Docker microVM อัตโนมัติ
- **3 โหมดการทำงาน:**
  - `/vibe` — guided app builder (สำหรับ non-engineer วาง prototype)
  - `/living` — persistent AI พนักงาน 24/7 ของแผนก
  - `/code-with-you` — pair programming step-by-step
- **Org governance** — IT จัดการ provider chain, deny-list, OTel telemetry, network egress
- **Dashboard ใน browser** — chat + sessions + config โดยไม่ต้องเปิด terminal

---

## 2. Prerequisites

ก่อนติดตั้ง ตรวจของให้ครบ:

| Tool | เช็คคำสั่ง | ติดตั้ง |
|---|---|---|
| Docker Desktop | `docker --version` | https://www.docker.com/products/docker-desktop |
| sbx (Docker Sandboxes) | `sbx --version` | macOS: `brew install docker/tap/sbx` · Linux: `sudo apt-get install docker-sbx` · Windows: `winget install Docker.sbx` |
| Python 3.10+ | `python3 --version` | https://www.python.org/downloads/ (หรือ `brew install python@3.13`) |
| API key | — | Anthropic console: https://console.anthropic.com/settings/keys |

**สำคัญ:**
- Docker Desktop ต้องรันก่อน เปิดให้ daemon ทำงานก่อนรัน `sopify install`
- `sbx` ต้อง `sbx login` ก่อน (จะเปิด browser ให้ login ด้วยบัญชี Docker)

---

## 3. ติดตั้ง (First-time install)

### 3.1 Clone + ลิงก์

```bash
# clone
git clone <repo-url> ~/ai_engineer/gs/project-based/sopify
cd ~/ai_engineer/gs/project-based/sopify/sopify-harness

# venv + dependencies
uv sync --extra web --extra cli --extra anthropic --extra pty

# install เป็น command
./scripts/install.sh
# → สร้าง ~/.local/bin/sopify (bash wrapper)
# → สร้าง ~/.sopify-app symlink → ./sopify-harness

# verify
sopify --version
```

ควรเห็น banner แรด + บรรทัด `sopify 0.1.0 (runtime 0.14.0)`

### 3.2 One-shot setup

```bash
sopify install
```

ทำให้:
1. ตรวจ Docker daemon
2. Build image `sopify-sandbox:latest` (ครั้งแรก ~3-5 นาที — `uv sync` + npm install + node bundle)
3. Sync image เข้า sbx template store
4. สร้าง bridge network `sopify-net`
5. เขียน default `~/.sopify/network-policy.json` (whitelist เริ่มต้น)
6. Emit OTel event `install_complete`

ถ้าเสร็จเรียบร้อยจะเห็น:
```
OK — run `sopify doctor` to verify.
```

### 3.3 Login (API key)

```bash
sopify login
```

จะถามว่าจะตั้ง provider ตัวไหน — ใส่ key ของ Anthropic หรือ OpenRouter
Key ถูกเก็บใน `~/.sopify/auth.json` (mode 0600 — เฉพาะคุณอ่านได้)

### 3.4 Doctor (health check)

```bash
sopify doctor
```

ตรวจ 5 row ภายใน 3 วินาที:

| Row | OK เมื่อ | FAIL บอกอะไร |
|---|---|---|
| docker | Docker daemon ตอบ | เปิด Docker Desktop ก่อน |
| sandbox-image | มี image | รัน `sopify install` |
| sandbox-net | bridge `sopify-net` มี | install สร้างให้ |
| auth | `~/.sopify/auth.json` มี + 0600 | `sopify login` |
| otel | otel endpoint ตอบ | "unreachable" = collector ไม่อยู่ — ไม่กระทบใช้งาน |

---

## 4. คำสั่งที่ใช้บ่อย

| Command | ใช้ตอน | รันที่ไหน |
|---|---|---|
| `sopify dashboard` | เปิด web UI ใน browser (แนะนำสำหรับ user) | sandbox |
| `sopify chat` | terminal chat (สำหรับ power user) | sandbox |
| `sopify /vibe` | guided app builder mode | sandbox |
| `sopify /living` | persistent AI mode | sandbox |
| `sopify /code-with-you` | pair programming mode | sandbox |
| `sopify install` | one-shot setup ครั้งแรก | host |
| `sopify install --rebuild` | rebuild image (หลังแก้โค้ด) | host |
| `sopify doctor` | health check | host |
| `sopify login` | ตั้ง API key | host |
| `sopify logout [provider]` | ลบ credentials | host |
| `sopify env list` | ดู keys ใน `~/.hermes/.env` | host |
| `sopify env set <provider>` | เพิ่ม API key | host |
| `sopify env unset <provider>` | ลบ API key | host |
| `sopify onboard` | welcome flow + audit consent | host |
| `sopify --version` | ดู version | host |

---

## 5. Dashboard (Web UI)

```bash
sopify dashboard
```

จะเปิด browser ที่ http://localhost:9119 อัตโนมัติ

**Tab หลัก:**

| Tab | ใช้ทำอะไร |
|---|---|
| `CHAT` | คุยกับ AI agent (TUI ฝังใน browser ผ่าน WebSocket) |
| `SESSIONS` | ดู / search / resume / ลบ session เก่า |
| `MODELS` | สลับ provider + model ตัว default |
| `LOGS` | ดู log จาก gateway / agent |
| `CRON` | scheduled jobs (Hermes routines) |
| `SKILLS` | ดู skill registry + เปิด/ปิด skill |
| `PLUGINS` | toggle plugin |
| `PROFILES` | สลับ role (user/dev) |
| `CONFIG` | edit settings.json |
| `KEYS` | จัดการ API keys |
| `DOCUMENTATION` | ดู docs ฝังใน app |

**ปิด dashboard:** ปิด terminal ที่รัน `sopify dashboard` (Ctrl+C) — sandbox จะหยุดอัตโนมัติ

### 5.1 เริ่ม chat ครั้งแรก
- เข้า tab `CHAT`
- ระบบจะแสดง wordmark + panel `☤ Sopify ☤` พร้อม version/tagline/REQ-list
- พิมพ์ message ใน prompt (เช่น `"refactor the auth module"` หรือ `"explain this codebase"`)
- กด Enter → AI ตอบ

### 5.2 ตอนยังไม่มี session
- เข้า tab `SESSIONS` ตอนเริ่มต้น จะเห็นแรดลอย + ข้อความ `Start a conversation to see it here`
- คลิก tab `CHAT` เพื่อเริ่มคุย → session แรกจะปรากฏใน SESSIONS หลังจากนั้น

---

## 6. Terminal modes

สำหรับ power user — รันใน terminal ตรงๆ ไม่ผ่าน browser

### 6.1 `/vibe` — Guided app builder

```bash
sopify /vibe
```

AI จะถามเป็น structured flow ก่อนเขียนโค้ด:
1. อยากได้อะไร? (goal)
2. ใช้ข้อมูลอะไร? (data source)
3. ใครจะใช้? (target user)
4. ต้องการ output แบบไหน? (format)

หลังจาก intake → AI เสนอ approach 2-3 แบบ → รอเลือก → เริ่ม implement

เหมาะกับ: non-engineer ที่อยากได้ prototype, รายงาน, automation script

### 6.2 `/living` — Persistent AI employee

```bash
sopify /living
```

- Session ไม่ตายเมื่อปิด terminal — รัน background ต่อ
- Auto-resume เมื่อ PC reboot (ลงทะเบียนเป็น system service)
- Memory persist ข้ามวัน — AI จำบริบทของแผนกได้

คำสั่งช่วย:
- `sopify /living status` — ดู uptime + last activity + memory
- `sopify /living stop` — graceful shutdown

เหมาะกับ: AI agent ประจำแผนก, monitor task, สรุปข้อมูลรายวัน

### 6.3 `/code-with-you` — Pair programming

```bash
sopify /code-with-you
```

- ทุก tool call ต้องผ่าน confirmation ก่อน execute (ไม่มี auto-approve)
- AI อธิบายว่าทำอะไร + ทำไม + ผลที่คาดหวัง ก่อนทำงาน
- เหมาะกับ: engineer ที่ต้องการเข้าใจทุก line code ก่อน execute

---

## 7. การจัดการ session

### 7.1 Resume session เก่า

ใน Dashboard → tab `SESSIONS` → คลิก ▶ Play icon ของ session ที่อยากเปิด → เปิดใน `CHAT` ต่อ

หรือใน terminal:
```bash
sopify chat --resume <session-id>
```

### 7.2 ค้นหา session

ใน Dashboard → tab `SESSIONS` → กล่อง search ด้านบนขวา → ใช้ FTS5 (full-text search) ของ SQLite

### 7.3 ลบ session

- ใน Dashboard → คลิก trash icon ของ session
- หรือ delete ผ่าน API: `DELETE /api/sessions/<id>`

---

## 8. API keys + credentials

### 8.1 ตำแหน่งไฟล์

| ไฟล์ | ใช้กับ |
|---|---|
| `~/.sopify/auth.json` | Sopify-native (Anthropic primary) |
| `~/.hermes/.env` | Hermes-era providers (OpenRouter, OpenAI, ฯลฯ) |

ทั้งสองถูก mount เข้า sandbox แบบ read-only

### 8.2 เพิ่ม API key

```bash
# วิธีแนะนำ: interactive
sopify login

# หรือ env-style:
sopify env set anthropic
# (จะ prompt ขอ key)

sopify env set openrouter
sopify env list
```

### 8.3 ลบ API key

```bash
sopify logout              # ลบทุก provider
sopify logout anthropic    # ลบเฉพาะ
sopify env unset openrouter
```

การลบใช้ zero-fill ก่อน unlink (ป้องกัน recovery จาก disk)

### 8.4 Environment variable override

ทุก `ANTHROPIC_API_KEY` (และ provider อื่น) ที่ตั้งใน shell จะ override ค่าใน auth.json
แต่ถ้าค่าเป็น `"proxy-managed"` (sentinel ของ sbx) → ระบบจะ ignore + fallback เข้า auth.json อัตโนมัติ ([sbx_launcher.py:344](plugins/sopify_sandbox/sbx_launcher.py#L344))

---

## 8.5 External Network Control (ENCM)

ตั้งแต่ M1 — ทุก outbound traffic จาก sandbox ผ่าน **ENCM proxy** (forward proxy + protocol enforcement)

### 8.5.1 Architecture

```
sandbox (HTTPS_PROXY=host.docker.internal:3128)
     │
     ▼
ENCM container :3128 (mitmproxy + addon)
     │
     ├─ match rule → audit log "allow" → forward to upstream
     └─ no match  → 403 deny + audit log "deny"
```

### 8.5.2 จัดการ rules

ตอนนี้ยังไม่มี UI (dashboard `/network` page อยู่ใน Milestone 3) — แก้ผ่านไฟล์ตรงๆ:

```bash
# ดู rules ปัจจุบัน
cat ~/.sopify/network-policy.json | jq .

# เพิ่ม rule (ตัวอย่าง: อนุญาต SharePoint)
# แก้ rules array ใน JSON ตรงๆ ตาม schema v2 — ENCM hot-reload ภายใน 1 วินาที
```

ดู [docs/sopify/REQ-ENCM-M1.md §3](docs/sopify/REQ-ENCM-M1.md#3-schema-v2) สำหรับ schema เต็ม

### 8.5.3 ดู audit log

```bash
# วันนี้
tail -f ~/.sopify/audit-log/$(date +%F).jsonl | jq

# กรองเฉพาะ deny
grep '"decision":"deny"' ~/.sopify/audit-log/*.jsonl | jq

# 30 วันย้อนหลัง (เกินนั้น auto-purge)
ls ~/.sopify/audit-log/
```

### 8.5.4 Bypass ENCM (dev mode เท่านั้น)

```bash
export SOPIFY_NO_ENCM=1
sopify dashboard
```

→ Sandbox จะไม่ผ่าน ENCM, ใช้ default sbx allowedDomains แทน (security weaker)

### 8.5.5 Restart ENCM container

```bash
docker restart sopify-encm
# หรือ rebuild image:
docker rm -f sopify-encm
sopify install     # จะ build + start ENCM ใหม่
```

---

## 9. Troubleshooting

### 9.1 Banner / mascot ไม่อัปเดตหลังแก้โค้ด

**สาเหตุ:** โค้ดที่รันใน sandbox มาจาก image baked-in ไม่ใช่ host code ที่ mount เข้ามา

**แก้:**
```bash
# 1. Rebuild image
sopify install --rebuild

# 2. ลบ sandbox เก่า (สร้างจาก image เวอร์ชันก่อน)
sbx ls
sbx rm <sandbox-name> --force

# 3. รัน sopify dashboard ใหม่ → สร้าง sandbox ใหม่จาก image อัปเดต
sopify dashboard
```

### 9.2 ตัวแรกใน sandbox สีซีดเทา (monochrome)

**สาเหตุ:** ก่อนหน้านี้ `TERM=dumb COLORTERM=` ไม่มี truecolor ใน `sbx exec`

**แก้:** ตอนนี้ [sbx_launcher.py:341-347](plugins/sopify_sandbox/sbx_launcher.py#L341-L347) export `COLORTERM=truecolor` + `TERM=xterm-256color` ใน inner_cmd แล้ว — ไม่ต้องทำอะไรเพิ่ม

### 9.3 Dashboard ไม่เปิด browser อัตโนมัติ

**สาเหตุ:** Port 9119 ยังไม่ binding ใน sandbox (FastAPI ยังไม่ start)

**แก้:** [`_open_browser_when_ready()`](plugins/sopify_sandbox/sbx_launcher.py#L146) รอ port เปิด 30 วินาที ถ้าไม่เปิดให้เปิด URL `http://localhost:9119` เองใน browser

### 9.4 `sbx login` failed

**สาเหตุ:** บัญชี Docker ยังไม่มีสิทธิ์ Sandboxes (beta access)

**แก้:** ขอ access ที่ https://docker.com/sandboxes — หรือ fallback ใช้ docker run:
```bash
SOPIFY_NO_SBX=1 sopify dashboard
```
จะข้าม sbx + รัน docker run ตรงๆ (ไม่มี microVM isolation)

### 9.5 `WARN: failed to start SSH agent relay`

ไม่มีผลกับการใช้งาน — sbx พยายาม forward SSH agent socket แต่ไม่จำเป็น

### 9.5b ENCM container ไม่ start / sandbox 403 ทุก request

**สาเหตุ:** ENCM container ตาย หรือ CA cert ไม่ trust

**แก้:**
```bash
# 1. เช็ค ENCM ยังรันไหม
docker ps | grep sopify-encm

# 2. ถ้าตาย → restart
docker start sopify-encm
# หรือ rebuild
docker rm -f sopify-encm
sopify install   # จะสร้างใหม่

# 3. เช็ค CA cert ในจริง ๆ ใน sandbox
docker run --rm -v ~/.sopify/encm-ca:/ca:ro debian:13.4-slim ls -la /ca/

# 4. ถ้าไม่ trust → ทำใหม่ทั้งกระบวน
rm -rf ~/.sopify/encm-ca
sbx ls && sbx rm <each-name> --force   # ลบ sandbox เก่าที่ trust CA เก่า
sopify install                          # สร้าง CA ใหม่ + ENCM image ใหม่
```

### 9.5c rules ไม่ apply หลังแก้ network-policy.json

**สาเหตุ:** ENCM policy file watcher ตาย / file location ไม่ถูก

**แก้:**
```bash
# ตรวจ syntax JSON ก่อน
cat ~/.sopify/network-policy.json | jq . || echo "JSON broken"

# Restart ENCM ให้แน่ใจ reload ใหม่
docker restart sopify-encm
docker logs sopify-encm --tail 30
```

### 9.6 Sandbox ไม่ติดตามที่ทำงานปัจจุบัน

Sandbox name = hash 10 ตัวของ `cwd` — ทำให้ 1 cwd ใช้ 1 sandbox

ถ้า `cd` ไปอีก dir แล้วรัน `sopify chat` → ได้ sandbox ใหม่
- ดู: `sbx ls` จะเห็น sopify-XXX หลายตัว
- ลบเฉพาะที่ไม่ใช้: `sbx rm <name> --force`

### 9.7 ผมพิมพ์อะไรไป sandbox ก็ไม่ตอบ

**Check:**
```bash
sopify doctor               # ตรวจ auth + OTel + sandbox image
sbx ls                      # ตรวจ sandbox running ไหม
docker ps                   # หรือถ้าใช้ docker fallback
```

ถ้า sandbox stopped:
```bash
sbx rm <name> --force
sopify chat                 # สร้างใหม่
```

### 9.8 Hide banner

```bash
export SOPIFY_NO_BANNER=1
```

ใส่ใน `~/.zshrc` หรือ `~/.bashrc` ถ้าอยากซ่อน banner ทุกครั้ง

---

## 10. สำหรับ developer

### 10.1 Map: แก้อะไรต้อง rebuild อะไร

ดูตารางเต็มที่ [DOCUMENTATION_ARCHITECTURE.md §11](DOCUMENTATION_ARCHITECTURE.md#11-rebuild-workflow--แก้อะไรต้อง-rebuild-อะไร)

สรุป:
| แก้ที่ | Rebuild |
|---|---|
| `plugins/sopify_*/` (host commands) | ❌ ไม่ต้อง |
| `plugins/sopify_*/` (ใน sandbox) | ✅ image |
| `web/src/` | ✅ web → image |
| `ui-tui/src/` | ✅ tui → image |
| `hermes_cli/`, `agent/`, `tools/` | ✅ image |
| `Dockerfile` | ✅ image |

### 10.2 Full rebuild

```bash
cd ~/ai_engineer/gs/project-based/sopify/sopify-harness

# build web
cd web && npm run build && cd ..

# build TUI
cd ui-tui && npm run build && cd ..

# build image (~30s cached, ~3-5min cold)
docker build -t sopify-sandbox:latest -f docker/sopify-sandbox/Dockerfile .

# sync to sbx
docker save -o /tmp/sopify-sandbox.tar sopify-sandbox:latest
sbx template load /tmp/sopify-sandbox.tar
rm /tmp/sopify-sandbox.tar

# remove stale sandboxes
sbx ls
sbx rm <each-name> --force
```

หรือ shortcut:
```bash
sopify install --rebuild
# ทำขั้นตอน docker build + sbx template load อัตโนมัติ
# (ต้องลบ sandbox เอง)
```

### 10.3 Dev-mode (host runtime, ไม่ใช้ sandbox)

```bash
SOPIFY_NO_SBX=1 sopify chat
```

จะ preload `plugins/sopify_*/` แล้วรัน Hermes บน host venv โดยตรง — แก้โค้ดเห็นผลทันที (ไม่ต้อง rebuild image)

ข้อจำกัด: ไม่มี sandbox isolation, network policy ไม่ enforced

### 10.4 Run tests

```bash
# Python tests
pytest tests/

# Test เฉพาะ Sopify plugins
pytest tests/sopify_*

# TUI tests
cd ui-tui && npm test
```

### 10.5 Type check

```bash
# Python
mypy plugins/sopify_*/

# Web
cd web && npm run type-check

# TUI
cd ui-tui && npm run type-check
```

### 10.6 Lint

```bash
ruff check plugins/sopify_*/
cd web && npm run lint
cd ui-tui && npm run lint
```

### 10.7 Live mount โค้ดเข้า sandbox (advanced)

ปกติ `app_root` mount เข้า sandbox แบบ `:ro` แต่ wrapper ไม่ใช้ — ใช้ `/opt/sopify` ใน image แทน

ถ้าอยาก live-mount จริง ๆ ให้แก้ wrapper ใน Dockerfile:
```bash
#!/usr/bin/env bash
# ตรวจว่า host harness mounted อยู่ไหม
if [ -d "/Users/<you>/ai_engineer/gs/project-based/sopify/sopify-harness" ]; then
    SRC="/Users/<you>/ai_engineer/gs/project-based/sopify/sopify-harness"
else
    SRC="/opt/sopify"
fi
exec /opt/sopify/.venv/bin/python "$SRC/sopify" "$@"
```

แล้ว rebuild image — ต่อไปนี้จะ pick up host code ที่แก้โดยไม่ต้อง rebuild

⚠️ ไม่แนะนำเป็น default — `/opt/sopify` มี venv + node_modules ที่ host อาจไม่มี

---

## Quick reference

```bash
# Daily usage
sopify dashboard            # main entry, web UI
sopify chat                 # terminal chat
sopify /vibe                # guided builder mode

# Manage credentials
sopify login                # interactive setup
sopify env list             # show keys (lengths only)
sopify logout               # clear all

# Maintenance
sopify doctor               # health check
sopify install --rebuild    # rebuild image after code changes
sbx ls                      # list sandboxes
sbx rm <name> --force       # remove sandbox

# Suppress banner
SOPIFY_NO_BANNER=1 sopify chat

# Host fallback (skip sandbox)
SOPIFY_NO_SBX=1 sopify chat
```

ดูเอกสารเพิ่มเติม:
- [DOCUMENTATION_ARCHITECTURE.md](DOCUMENTATION_ARCHITECTURE.md) — โครงสร้างโค้ด (developer)
- [docs/sopify/TUTORIAL.md](docs/sopify/TUTORIAL.md) — tutorial เก่า (Phase 1 scaffold)
- [docs/sopify/INSTALL.md](docs/sopify/INSTALL.md) — install steps แบบละเอียด
- [docs/sopify/REQ-*-*.md](docs/sopify/) — รายละเอียดต่อ REQ block (REQ-0 .. REQ-11)
- [SECURITY.md](SECURITY.md) — security disclosure policy

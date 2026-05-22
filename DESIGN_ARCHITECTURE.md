# Sopify — Software Requirements Specification
> Version: 0.1  
> Status: Draft  
> Author: GS Battery IT Team  
> Concept: **Hermes Upgrade** — ไม่ลบอะไรออก เพิ่ม org layer ทับของที่มีอยู่

---

## Core Concept

```
Sopify ≠ ระบบใหม่
Sopify = Hermes + Docker Sandbox (embedded) + 3 Modes + Org Governance
```

ทุก feature ของ Hermes ยังอยู่ครบ — Sopify เพิ่ม layer ทับโดยไม่แตะ core

---

## REQ-0 — Foundation (Hermes Base)

> Hermes ทำงานได้ปกติ ไม่มีอะไรถูกลบ

- [ ] **REQ-0.1** Fork Hermes repository และ maintain เป็น upstream reference
- [ ] **REQ-0.2** สร้าง `SOPIFY_ARCH.md` ใน repo ก่อน commit ใดๆ (SPOF protection)
- [ ] **REQ-0.3** Architecture rule: Sopify code ทั้งหมดอยู่ใน `plugins/sopify-*` เท่านั้น — ห้ามแก้ Hermes core
- [ ] **REQ-0.4** CI pipeline: lint (ruff) + type check (mypy) + unit tests pass ก่อน merge
- [ ] **REQ-0.5** `sopify --version` แสดง version และ Hermes base version
- [ ] **REQ-0.6** รองรับ Windows (install.ps1) และ Linux (install.sh)
- [ ] **REQ-0.7** `sopify install` command — setup ทุกอย่าง one-shot (Docker + auth + config)
- [ ] **REQ-0.8** `sopify doctor` — health check auth, sandbox, OTel connectivity

---

## REQ-1 — Docker Sandbox (Embedded, First-class)

> Docker Sandbox คือ **environment ที่ Sopify อาศัยอยู่** — ไม่ใช่ feature ที่เรียกใช้
> ตั้งแต่ `sopify install` เสร็จ → Sopify ทุก command รันอยู่ใน sandbox เสมอ
> ไม่ต้องสั่งอะไรพิเศษ ไม่ขึ้นกับ mode

```
sopify install
    ↓ pull sopify-sandbox image
    ↓ build sandbox environment
    ↓ register network policy
    ↓ sandbox READY — ทุกอย่างหลังจากนี้รันในนั้น

sopify /vibe     → runs inside sandbox (already)
sopify /living   → runs inside sandbox (already)
sopify /code-with-you → runs inside sandbox (already)
sopify chat      → runs inside sandbox (already)
```

### REQ-1.1 Sandbox ตอน Install

- [ ] **REQ-1.1.1** `sopify install` pull + build `sopify-sandbox:latest` image อัตโนมัติ
- [ ] **REQ-1.1.2** Install ตรวจสอบว่า Docker daemon รันอยู่ — ถ้าไม่มี → แสดง error + installation guide
- [ ] **REQ-1.1.3** Install สร้าง `sopify-net` bridge network ถ้ายังไม่มี
- [ ] **REQ-1.1.4** Install เขียน default `~/.sopify/network-policy.json` (whitelist เริ่มต้น)
- [ ] **REQ-1.1.5** `sopify doctor` ตรวจสอบ sandbox health และรายงาน: image exists, network ready, permissions OK

### REQ-1.2 Sandbox Runtime (ทุก session ทุก mode)

- [ ] **REQ-1.2.1** Sopify runtime **ทั้งหมด** ทำงานอยู่ภายใน container — ไม่มี Sopify process บน host นอกจาก launcher
- [ ] **REQ-1.2.2** Launcher บน host ทำแค่: spawn container, mount directories, forward stdin/stdout/stderr
- [ ] **REQ-1.2.3** Container ใช้ image `sopify-sandbox:latest` ที่ bundle มากับ installation
- [ ] **REQ-1.2.4** Container หยุดและลบอัตโนมัติเมื่อ session ปิด (cleanup ไม่เหลือ orphan)
- [ ] **REQ-1.2.5** Project directory ของ user mount เข้า container เป็น `/workspace` (read-write)
- [ ] **REQ-1.2.6** Auth config mount เป็น read-only: `~/.sopify/auth.json` → `/sopify-auth` (ro)
- [ ] **REQ-1.2.7** Settings mount เป็น read-only: `~/.sopify/settings.json` → `/sopify-config` (ro)
- [ ] **REQ-1.2.8** Session state DB mount: `~/.sopify/sessions/` → `/sopify-sessions` (read-write) — สำหรับ /living persistence

### REQ-1.2 Network Egress Control

- [ ] **REQ-1.2.1** Container ใช้ custom bridge network `sopify-net` แยกจาก host network
- [ ] **REQ-1.2.2** Default whitelist (always allowed, ไม่ต้องถาม):
  - `api.anthropic.com` — LLM API
  - `otel-collector.gsbattery.local` — Internal telemetry
- [ ] **REQ-1.2.3** เมื่อ AI พยายาม access domain ใหม่ → แสดง dialog ถาม user ก่อน
- [ ] **REQ-1.2.4** Dialog options: "Allow once" / "Allow always" / "Deny"
- [ ] **REQ-1.2.5** "Allow always" persist ลง `~/.sopify/network-policy.json`
- [ ] **REQ-1.2.6** IT สามารถ pre-approve domains ผ่าน managed settings (MDM push)
- [ ] **REQ-1.2.7** Access ที่ถูก deny → log เป็น OTel event `tool_decision` (blocked)

### REQ-1.3 Dev Mode (Optional override)

- [ ] **REQ-1.3.1** `role: "dev"` สามารถ enable `--no-sandbox` flag ได้ (สำหรับ debugging)
- [ ] **REQ-1.3.2** การใช้ `--no-sandbox` ต้องบันทึก OTel event ว่า sandbox disabled + reason
- [ ] **REQ-1.3.3** `role: "user"` ไม่มีสิทธิ์ใช้ `--no-sandbox` ไม่ว่ากรณีใด

---

## REQ-2 — Provider & Auth

> ใช้ Anthropic API key โดยตรง — ไม่มี subscription OAuth trick

### REQ-2.1 Provider Router

- [ ] **REQ-2.1.1** สร้าง `ProviderRouter` class ที่ handle provider priority cascade
- [ ] **REQ-2.1.2** Priority chain (default): Anthropic API → OpenRouter → any Hermes provider
- [ ] **REQ-2.1.3** ถ้า provider return 401/403 → blacklist 1 ชั่วโมง → ลองตัวถัดไปอัตโนมัติ
- [ ] **REQ-2.1.4** ถ้า quota exceeded / rate limit → blacklist 1 ชั่วโมง → failover อัตโนมัติ
- [ ] **REQ-2.1.5** TUI แสดง active provider + quota remaining ที่ footer ตลอดเวลา
- [ ] **REQ-2.1.6** IT สามารถ override provider chain ผ่าน `~/.sopify/settings.json` (MDM push)

### REQ-2.2 Auth Storage

- [ ] **REQ-2.2.1** เก็บ API keys ใน `~/.sopify/auth.json` file permission 0600
- [ ] **REQ-2.2.2** รองรับ `ANTHROPIC_API_KEY` environment variable (override auth.json)
- [ ] **REQ-2.2.3** `sopify login` — interactive setup สำหรับ API key
- [ ] **REQ-2.2.4** `sopify logout` — ลบ credentials อย่างปลอดภัย (zero-fill ก่อนลบ)

---

## REQ-3 — /living Mode

> AI พนักงาน 24/7 ที่อาศัยอยู่บนเครื่อง PC ของแผนก

### REQ-3.1 Persistent Session

- [ ] **REQ-3.1.1** Session ไม่ตายเมื่อปิด terminal — ยังรันใน background
- [ ] **REQ-3.1.2** Auto-resume เมื่อ PC reboot — ลงทะเบียนเป็น system service (systemd / launchd / Windows Service)
- [ ] **REQ-3.1.3** Session state persist ใน SQLite WAL (Hermes hermes_state.py) — crash-safe
- [ ] **REQ-3.1.4** Daily automatic backup ของ session state ไปยัง path ที่ config ได้
- [ ] **REQ-3.1.5** `sopify /living status` — แสดง uptime, last activity, memory usage
- [ ] **REQ-3.1.6** `sopify /living stop` — graceful shutdown บันทึก state ก่อนหยุด

### REQ-3.2 Department Context

- [ ] **REQ-3.2.1** inject `living-employee/SKILL.md` และ `company-sop/SKILL.md` เข้า system prompt อัตโนมัติ
- [ ] **REQ-3.2.2** รองรับ department-specific skill file: `.sopify/dept-context.md` ในโฟลเดอร์ของแผนก
- [ ] **REQ-3.2.3** Memory persistent ข้ามวัน — AI จำบริบทของแผนกได้โดยไม่ต้อง re-explain
- [ ] **REQ-3.2.4** Cron job support — แผนกสามารถตั้ง scheduled tasks ผ่าน `/living` ได้

### REQ-3.3 Security (Strict level)

- [ ] **REQ-3.3.1** ใช้ `deny_list_level: "strict"` — ทุก destructive command ต้องผ่าน hard deny ก่อน
- [ ] **REQ-3.3.2** `require_approval_for_destructive: true` — dialog confirm ทุก soft deny action
- [ ] **REQ-3.3.3** ไม่อนุญาต `parallel_tool_execution` สำหรับ destructive operations
- [ ] **REQ-3.3.4** OTel emit ทุก tool call ตลอด 24 ชั่วโมง

---

## REQ-4 — /vibe Mode

> Guided app builder — ตั้งแต่ brainstorm ไปจนถึง code ที่ IT อ่านแล้วเข้าใจ

### REQ-4.1 Guided Flow

- [ ] **REQ-4.1.1** เมื่อเริ่ม session ใหม่ — AI ถาม user เป็น structured flow ก่อน code
  1. อยากได้อะไร? (goal)
  2. ใช้ข้อมูลอะไร? (data source)
  3. ใครจะใช้? (target user)
  4. ต้องการ output แบบไหน? (format)
- [ ] **REQ-4.1.2** หลัง intake → AI สรุป understanding + เสนอ approach 2-3 แบบ → รอ user เลือก
- [ ] **REQ-4.1.3** Implementation เริ่มหลัง user approve approach เท่านั้น

### REQ-4.2 Session Branching

- [ ] **REQ-4.2.1** ทุก brainstorm topic ใหม่ → auto-create session branch (Hermes session tree)
- [ ] **REQ-4.2.2** User สามารถกลับไป branch เก่าผ่าน `/tree` command
- [ ] **REQ-4.2.3** Session history export เป็น HTML สำหรับส่ง IT ได้

### REQ-4.3 IT Handoff

- [ ] **REQ-4.3.1** เมื่อ session เสร็จ → AI generate IT handoff template อัตโนมัติ:
  - สิ่งที่สร้าง + เหตุผลที่เลือก approach
  - Files ที่แก้ไข
  - Dependencies ที่เพิ่ม
  - วิธี run + ข้อควรระวัง
- [ ] **REQ-4.3.2** inject `vibe-app-builder/SKILL.md` และ `company-sop/SKILL.md`
- [ ] **REQ-4.3.3** Code ที่ generate ต้อง follow GS Battery coding standards (inject ผ่าน skill)

### REQ-4.4 Promotion Gate

- [ ] **REQ-4.4.1** OTel track `app_fingerprint` (hash ของ project structure) ต่อ session
- [ ] **REQ-4.4.2** ถ้า same app type ใช้ >3 ครั้งใน 7 วัน → trigger IT notification
- [ ] **REQ-4.4.3** IT notification รวม: user, app fingerprint, session count, cost, Grafana link
- [ ] **REQ-4.4.4** Nightly cron job query Loki → ส่ง notification ถ้ามี candidates

---

## REQ-5 — /code-with-you Mode

> Pair programming — engineer เข้าใจทุก line ก่อน execute ใดๆ

### REQ-5.1 Confirm-Every-Step

- [ ] **REQ-5.1.1** ทุก tool call ต้องผ่าน confirmation dialog ก่อน execute — ไม่มี auto-approve
- [ ] **REQ-5.1.2** Dialog แสดง: tool name, arguments, และ plain-language explanation ว่าจะทำอะไร
- [ ] **REQ-5.1.3** User options: "Execute" / "Skip" / "Modify before execute" / "Stop session"
- [ ] **REQ-5.1.4** `parallel_tool_execution: false` — sequential เท่านั้น (ง่ายต่อ follow)

### REQ-5.2 Explanation First

- [ ] **REQ-5.2.1** ก่อน execute ทุก step → AI อธิบายว่าทำอะไร + ทำไม + ผลที่คาดหวัง
- [ ] **REQ-5.2.2** ถ้า step เกี่ยวกับ algorithm หรือ logic ที่ซับซ้อน → AI explain แบบ inline comment
- [ ] **REQ-5.2.3** inject `code-with-you/SKILL.md` — ระบุ AI ต้อง optimize for understanding ไม่ใช่ speed

### REQ-5.3 Token Efficiency

- [ ] **REQ-5.3.1** `daily_token_budget: 50000` — ต่ำกว่า /vibe เพราะ interactive ทีละ step
- [ ] **REQ-5.3.2** Context compaction เมื่อ context > 70% (Hermes context_compressor.py)
- [ ] **REQ-5.3.3** OTel track token usage ต่อ session — alert ถ้า near budget

---

## REQ-6 — Deny-list & Role Gating

> Governance ที่อยู่ใน execution layer — bypass ไม่ได้

### REQ-6.1 Hard Deny (ทุก role ห้ามเด็ดขาด)

- [ ] **REQ-6.1.1** Implement `HARD_DENY` pattern list ใน `tool_guardrails.py` plugin
- [ ] **REQ-6.1.2** Patterns ขั้นต่ำที่ต้อง block:

  | Pattern | เหตุผล |
  |---|---|
  | `rm -rf /` หรือ `rm -rf ~` | Recursive delete root/home |
  | `DROP DATABASE` | ลบ database ทั้งหมด |
  | `DROP TABLE <name>;` | ลบ table ไม่มี WHERE |
  | `:(){ :|:& };:` | Fork bomb |
  | `mkfs.*` | Format filesystem |
  | `dd if=* of=/dev/sd*` | Overwrite block device |
  | `chmod -R 777 /` | World-write root |
  | `shutdown\|reboot\|halt\|poweroff` | System shutdown |

- [ ] **REQ-6.1.3** เมื่อ block → แสดงข้อความชัดเจน + emit OTel `tool_decision` (hard_deny)
- [ ] **REQ-6.1.4** Hard deny ไม่มีวิธี override — แม้แต่ dev role ก็ไม่ผ่าน

### REQ-6.2 Soft Deny (user ห้าม, dev ต้อง confirm)

- [ ] **REQ-6.2.1** Implement `SOFT_DENY` pattern list:

  | Pattern | เหตุผล |
  |---|---|
  | `DELETE FROM <table>;` (ไม่มี WHERE) | ลบข้อมูลทั้ง table |
  | `TRUNCATE TABLE` | ลบข้อมูลทั้ง table |
  | `rm -rf <any-path>` | Recursive delete |
  | `git push --force` | Force push |
  | `curl * \| bash` | Pipe to shell |
  | `wget * \| bash` | Pipe to shell |

- [ ] **REQ-6.2.2** ถ้า `role: "user"` → block + แสดง "ต้องการ Dev role สำหรับคำสั่งนี้ ติดต่อ IT"
- [ ] **REQ-6.2.3** ถ้า `role: "dev"` → แสดง confirmation modal พร้อม command + reason → รอ yes/no
- [ ] **REQ-6.2.4** Dev confirm → emit OTel `tool_decision` (dev_confirmed + role_escalation_used)
- [ ] **REQ-6.2.5** Dev reject → emit OTel `tool_decision` (dev_rejected)

### REQ-6.3 Role Management

- [ ] **REQ-6.3.1** Role เก็บใน `~/.sopify/profile.json` — set โดย IT ตอน install
- [ ] **REQ-6.3.2** User ไม่มีสิทธิ์แก้ role ของตัวเอง (file permission + validation)
- [ ] **REQ-6.3.3** `sopify admin set-role <user> <user|dev>` — IT-only command
- [ ] **REQ-6.3.4** Values: `"user"` (default, non-dev) / `"dev"` (engineering team)

---

## REQ-7 — OTel Telemetry Pipeline

> Audit trail สำหรับ IT — ทุก AI action มีหลักฐาน

### REQ-7.1 5 Event Types (Claude Code compatible schema)

- [ ] **REQ-7.1.1** `user_prompt` — prompt text (truncate 2000 chars), session_id, user_email, mode
- [ ] **REQ-7.1.2** `api_request` — model, input_tokens, output_tokens, cost_usd, latency_ms, provider
- [ ] **REQ-7.1.3** `tool_result` — tool_name, success, duration_ms, args_summary (500 chars)
- [ ] **REQ-7.1.4** `tool_decision` — decision (auto_approved/user_approved/blocked), tool_name, reason
- [ ] **REQ-7.1.5** `api_error` — error_type, status_code, message
- [ ] **REQ-7.1.6** ทุก event มี base fields: timestamp, session_id, user_email, org_id, sopify_mode

### REQ-7.2 Collector & Storage

- [ ] **REQ-7.2.1** Grafana Alloy collector deploy บน server กลาง (Docker container)
- [ ] **REQ-7.2.2** รับ OTel ผ่าน gRPC (port 4317) และ HTTP (port 4318)
- [ ] **REQ-7.2.3** Forward ไป Loki (logs) + Prometheus (metrics)
- [ ] **REQ-7.2.4** ถ้า collector unreachable → Sopify ยังทำงานได้ (fire-and-forget, ไม่ block)
- [ ] **REQ-7.2.5** `OTEL_EXPORTER_OTLP_ENDPOINT` ต้องเป็น managed setting (user ไม่แก้ได้)

### REQ-7.3 Grafana Dashboards (3 ชุด)

- [ ] **REQ-7.3.1** **IT Overview Dashboard** — cost/day, active sessions, top 10 users by cost, error rate
- [ ] **REQ-7.3.2** **User Audit Dashboard** — search by `user_email`, full session trace พร้อม tool decisions
- [ ] **REQ-7.3.3** **Promotion Candidates Dashboard** — sessions ที่ใช้ app เดิม >3 ครั้ง → deploy queue

### REQ-7.4 Privacy

- [ ] **REQ-7.4.1** `user_prompt` event เก็บเฉพาะเมื่อ `OTEL_LOG_USER_PROMPTS=1` (opt-in, managed by IT)
- [ ] **REQ-7.4.2** Data retention policy configurable (default: purge >90 วัน)
- [ ] **REQ-7.4.3** Grafana RBAC — IT admin เท่านั้นดู User Audit dashboard
- [ ] **REQ-7.4.4** แจ้ง user ตอน install ว่า session ถูก audit (consent flow)
- [ ] **REQ-7.4.5** ต้องมี HR + GM IT sign-off ก่อน enable `OTEL_LOG_USER_PROMPTS` ใน production

---

## REQ-8 — Skills & Org Context

> Org knowledge ที่ AI รู้ตลอดเวลา ไม่ต้อง explain ซ้ำ

### REQ-8.1 Skill Bundles (SKILL.md format — Hermes compatible)

- [ ] **REQ-8.1.1** `sopify_skills/company-sop/SKILL.md` — IT SOP, coding standards, ข้อห้ามของบริษัท
- [ ] **REQ-8.1.2** `sopify_skills/living-employee/SKILL.md` — persona สำหรับ /living mode
- [ ] **REQ-8.1.3** `sopify_skills/vibe-app-builder/SKILL.md` — guided flow + IT handoff template
- [ ] **REQ-8.1.4** `sopify_skills/code-with-you/SKILL.md` — pair programming behavior
- [ ] **REQ-8.1.5** `sopify_skills/gs-mad/SKILL.md` — GS-MAD methodology **(Phase 7+ only)**
- [ ] **REQ-8.1.6** Mode ที่เปิดอยู่ inject skill bundle ของตัวเองอัตโนมัติตอน session start
- [ ] **REQ-8.1.7** User สามารถเพิ่ม skill เสริมได้จาก `.sopify/skills/` ใน project folder

### REQ-8.2 Claude Code Ecosystem Compatibility

- [ ] **REQ-8.2.1** Sopify อ่าน `~/.claude/skills/` และ merge เข้า skill list (Claude Code skills ใช้ได้เลย)
- [ ] **REQ-8.2.2** Sopify อ่าน `~/.claude/mcp.json` และ spawn MCP servers เดียวกัน (Hermes mcp_tool.py)
- [ ] **REQ-8.2.3** Sopify skill override Claude Code skill ที่ชื่อเดียวกัน (last-writer-wins)

---

## REQ-9 — IT Management & Deployment

> IT สามารถ govern ทุกอย่างจากส่วนกลาง โดยไม่ต้องนั่งที่เครื่อง user

### REQ-9.1 Managed Settings

- [ ] **REQ-9.1.1** `~/.sopify/settings.json` — IT push ผ่าน MDM, user อ่านได้แต่แก้ไม่ได้ (0444)
- [ ] **REQ-9.1.2** Settings ที่ IT ควบคุมได้:
  - `provider_chain` — ลำดับ provider fallback
  - `otel_endpoint` — collector URL
  - `allowed_domains` — network whitelist เพิ่มเติม
  - `daily_token_budgets` — budget ต่อ mode
  - `log_user_prompts` — เปิด/ปิด prompt logging
  - `sandbox_enabled` — เปิด/ปิด sandbox (default: true, IT-only)
- [ ] **REQ-9.1.3** เมื่อ settings เปลี่ยน → session ถัดไปใช้ค่าใหม่อัตโนมัติ (ไม่ต้อง restart)

### REQ-9.2 Install & Onboard

- [ ] **REQ-9.2.1** `sopify install` — one-command setup: Docker pull + auth setup + config + systemd/service register
- [ ] **REQ-9.2.2** IT สามารถ pre-package installation script พร้อม org settings สำหรับ mass deploy
- [ ] **REQ-9.2.3** `sopify onboard` — welcome flow สำหรับ user ใหม่: อธิบาย 3 modes, consent audit, auth setup
- [ ] **REQ-9.2.4** Installation บันทึก OTel event `install_complete` พร้อม machine_id + user + role

### REQ-9.3 Quota Monitor

- [ ] **REQ-9.3.1** Track token usage ต่อ provider ต่อ session แบบ real-time
- [ ] **REQ-9.3.2** Warning เมื่อ daily budget ใกล้หมด (80%) — แสดงใน TUI footer
- [ ] **REQ-9.3.3** Auto-switch provider เมื่อ quota หมด (Provider Router)
- [ ] **REQ-9.3.4** IT alert เมื่อ total org spend > threshold ที่ config ไว้

---

## REQ-10 — TUI (Terminal User Interface)

> User experience ที่ non-dev ใช้ได้ — ไม่ใช่ raw CLI

- [ ] **REQ-10.1** TUI (Ink/React) แสดง: active mode, provider, quota remaining, session info
- [ ] **REQ-10.2** Mode switcher ผ่าน slash command: `/living`, `/vibe`, `/code-with-you`
- [ ] **REQ-10.3** Dangerous command confirmation dialog มี visual warning ชัดเจน (color, icon)
- [ ] **REQ-10.4** Network permission dialog แสดง domain + reason ก่อน allow/deny
- [ ] **REQ-10.5** `/help` แสดง quick reference: available modes, slash commands, keyboard shortcuts
- [ ] **REQ-10.6** รองรับ Thai ภาษาในการ display (UTF-8, ไม่ garble)
- [ ] **REQ-10.7** Streaming response render แบบ real-time (ไม่รอ full response)
- [ ] **REQ-10.8** `/status` แสดง: mode, sandbox status, provider, quota, session stats

---

## REQ-11 — Security & Compliance

- [ ] **REQ-11.1** ทุก API key เก็บใน file ที่ permission 0600 (user-only read/write)
- [ ] **REQ-11.2** ไม่เขียน API key ลง log หรือ OTel events (redact ก่อน emit)
- [ ] **REQ-11.3** `sopify_core/agent/redact.py` (Hermes) — PII redact ก่อน log ทุกครั้ง
- [ ] **REQ-11.4** Docker container รันเป็น non-root user
- [ ] **REQ-11.5** Container image scan สำหรับ CVE ก่อน release (GitHub Actions)
- [ ] **REQ-11.6** Watch Hermes upstream สำหรับ security patches — cherry-pick เข้า Sopify ภายใน 7 วัน
- [ ] **REQ-11.7** Watch Claude Code releases สำหรับ OTel schema changes

---

## REQ-12 — Non-Functional Requirements

| Requirement | Target |
|---|---|
| Container start time | < 5 วินาที ตั้งแต่ `sopify /vibe` ถึง ready |
| TUI response latency | < 200ms สำหรับ UI interactions |
| OTel event drop rate | < 0.1% (fire-and-forget, ไม่ block session) |
| Session recovery time | < 30 วินาที หลัง PC reboot (/living mode) |
| RAM overhead (sandbox) | < 512MB per container (ไม่นับ project) |
| Disk usage (base image) | < 2GB สำหรับ sopify-sandbox image |
| Windows compatibility | Windows 10 + WSL2 + Docker Desktop |
| Linux compatibility | Ubuntu 22.04+ / Debian 11+ |

---

## Implementation Priority

```
PHASE 1 (Weeks 1–10) — Foundation
  REQ-0  Foundation        ████████████ must-have
  REQ-2  Provider & Auth   ████████████ must-have
  REQ-1  Docker Sandbox    ████████████ must-have (core differentiator)

PHASE 2 (Weeks 11–22) — Org Layer + Pilot
  REQ-4  /vibe Mode        ████████████ must-have (primary use case)
  REQ-7  OTel Pipeline     ████████████ must-have (governance evidence)
  REQ-6  Deny-list         ████████████ must-have (security)
  REQ-8  Skills            ████░░░░░░░░ important
  REQ-9  IT Management     ████░░░░░░░░ important
  REQ-10 TUI               ████░░░░░░░░ important

PHASE 3 (Weeks 23–32) — Full Modes + Scale
  REQ-5  /code-with-you    ████░░░░░░░░ important
  REQ-3  /living Mode      ████░░░░░░░░ important (high risk, test last)
  REQ-11 Security          ████████████ continuous
  REQ-12 Non-functional    ████░░░░░░░░ validate at each phase
```

---

## Acceptance Criteria (Phase Gates)

### Gate P2 (After Sandbox)
- [ ] `sopify install` เสร็จ → `sopify doctor` รายงาน sandbox: READY (image exists, network ok)
- [ ] `sopify` ทุก command (ไม่ว่า mode ไหน) → รันอยู่ใน container แล้วเสมอ ไม่ต้องสั่งอะไรพิเศษ
- [ ] `sopify doctor` แสดง sandbox status ภายใน < 3 วินาที
- [ ] AI พยายาม access URL ที่ไม่ได้ whitelist → prompt-to-allow dialog ปรากฏทันที
- [ ] ปิด session → container ลบตัวเองอัตโนมัติ (ไม่เหลือ orphan)
- [ ] รัน `sopify` บนเครื่องที่ไม่มี Docker → error message ชัดเจน พร้อม installation guide

### Gate P5 (After Deny-list)
- [ ] `rm -rf /` ใน bash tool → blocked + logged ทุกกรณี ไม่มีข้อยกเว้น
- [ ] `role: "user"` พยายามรัน `rm -rf ./folder` → blocked (soft deny)
- [ ] `role: "dev"` พยายามรัน `rm -rf ./folder` → confirmation dialog, ถ้า yes = execute + log

### Gate P6 (After Pilot)
- [ ] QA non-dev user สร้าง app ได้ end-to-end โดยไม่ต้องการความช่วยเหลือ
- [ ] IT เห็น session ทั้งหมดใน Grafana User Audit dashboard
- [ ] Promotion gate trigger ถ้า user ใช้ /vibe > 3 ครั้งใน 7 วัน
- [ ] 0 critical incidents (sandbox breach, data loss, unauthorized access)

---

*เอกสารนี้คือ source of truth สำหรับ Sopify features*  
*อ้างอิง: SOPIFY_ARCH.md (architecture), GS_CONTEXT.md (full context)*  
*Rule: ถ้า implementation ไม่ตรง checklist → update เอกสาร ไม่ใช่ code*
# Claude Code Integration — Implementation Plan

> Plan สำหรับเอกสาร [spec](2026-06-01-claude-code-integration-spec.md)
> สถานะ: Draft v2 (architecture locked) · วันที่: 2026-06-01 · เจ้าของ: Burased
> Base: ใช้ code ปัจจุบันใน repo (`sopify-harness/`) เป็น canonical
> Cadence: PR เล็ก atomic ทีละชิ้น, feature branch แตกจาก `development` แล้ว PR เข้า `development` (dev ค่อย merge → `main` ทีหลัง)

---

## 1. เป้าหมาย (Goal)

นำ **Claude Code (CLI)** เข้ามาเป็นกำลังหลักด้าน coding ภายใน Sopify เพื่อแก้ปัญหาเดิมที่ Hermes เขียน code คุณภาพไม่พอและติด loop บ่อย แม้ใช้ skills แล้ว — โดยรันใน Docker Sandbox เดิม

**หลักการแบ่งบทบาท (locked):**
- **Vibe Code section** = งานเขียน code แบบ interactive → **User คุยกับ Claude Code โดยตรง** (ไม่ผ่าน Hermes เพื่อไม่ให้ section ทับซ้อนและไม่เปลือง token 2 ต่อ)
- **Panel** = คุยกับ **Hermes** → เน้นงาน orchestration: ตอบคำถาม, research, brainstorm, และ**เขียน Scheduling / Cron Job**
- **จุดเชื่อม:** User ตั้ง Cron Job ผ่าน Hermes บน Panel ที่ "สั่งให้ Claude Code ทำงาน" ได้ → อนุญาต (Hermes เรียก Claude Code แบบ headless)

---

## 2. การตัดสินใจที่ล็อกแล้ว (Locked Decisions)

| # | คำถาม | คำตอบ |
|---|---|---|
| 1 | Claude Code ใช้ key แยกหรือ share กับ Hermes? | **Share** provider/credential เดียวกับ Hermes |
| 2 | `ANTHROPIC_BASE_URL` ชี้ไปไหน? | **เลือกได้** (Anthropic จริง หรือ relay ไป model ราคาถูก ผ่าน Anthropic-compatible endpoint) — ตั้งผ่าน Dashboard |
| 3 | Claude Code binary มาอย่างไร? | **Bake ลง Docker image** (pin version) — เหตุผล: sandbox spin บ่อยต้องเริ่มเร็ว, network ถูกจำกัดด้วย ENCM `no_proxy` (runtime install อาจโดน block), และตรง pattern เดิมที่ image bake `.venv`+TUI bundle ไว้แล้ว |
| 4 | ต้องมี UI monitoring ไหม? | **มี** — การ์ด token + bar chart เลือก model |

---

## 3. สถาปัตยกรรมเป้าหมาย (Target Architecture)

**2 surface แยกกัน + 1 จุดเชื่อมผ่าน cron**

```
┌──────────────────────────────── Docker Sandbox (sbx microVM) ────────────────────────────────┐
│                                                                                                │
│   ┌─ Surface A: VIBE CODE ─────────────┐        ┌─ Surface B: PANEL ──────────────────────┐    │
│   │  User  ◄──────────►  Claude Code    │        │  User  ◄──────────►  Hermes             │    │
│   │        (interactive, ตรง)           │        │        (chat / research / scheduling)   │    │
│   │  - ไม่มี Hermes relay ตอน iterate    │        │  - เขียน Cron Job / Routines             │    │
│   │  - แก้ไฟล์ใน shared workspace        │        │              │                          │    │
│   └─────────────────────┬───────────────┘        └──────────────┼──────────────────────────┘    │
│                         │                                        │ (cron ถึงเวลา / trigger)     │
│   context bridge (boundary เท่านั้น):                            ▼                              │
│   Hermes ─ enter: ส่ง persistent memory/context ─►        claude_code_task (headless)          │
│           ─ exit:  เก็บสรุป + usage กลับเข้า memory ◄──    รัน Claude Code แบบ non-interactive    │
│                                                                                                │
│   shared workspace (cwd, rw) · ~/.hermes (rw → /home/sopify/.hermes) · MCP: hermes mcp serve   │
└────────────────────────────────────────────────────────────────────┬───────────────────────────┘
                                                                       ▼
                                              provider endpoint (base_url เลือกได้ — share credential)
```

**สอง path ของการรัน Claude Code:**
- **(A) Interactive** — Vibe Code section wire chat ไปยัง Claude Code session โดยตรง; persistent ด้วย `--resume` ผูกกับ project id
- **(B) Headless** — `claude_code_task` ที่ Hermes cron/routine เรียกได้ (non-interactive, มี budget guard)

**Connection / context:** Claude Code ดึง context ข้าม section ผ่าน Hermes MCP server ([mcp_serve.py](../../mcp_serve.py)) เฉพาะตอน boundary; ส่วน edit code ทำผ่าน shared filesystem ไม่ผ่าน token

---

## 4. ตรวจกับ code จริง (Reality Check)

| ประเด็น | สถานะจริง | ผลต่อแผน |
|---|---|---|
| Sandbox mount `~/.hermes` | rw แล้ว + symlink เข้า home ของ user `sopify` ([sbx_launcher.py:588,617](../../plugins/sopify_sandbox/sbx_launcher.py#L588)) | ยืนยัน path = `/home/sopify/.hermes` (PR 1.2) |
| Env inject | ทำตอน exec-time ([sbx_launcher.py:684-736](../../plugins/sopify_sandbox/sbx_launcher.py#L684)); มี `no_proxy` allowlist | เพิ่ม `ANTHROPIC_BASE_URL` ผ่าน path เดิม |
| Dashboard env config | หน้า `/env` แก้ `OPTIONAL_ENV_VARS` → `~/.hermes/.env` ([web_server.py:1216-1259](../../hermes_cli/web_server.py#L1216)) | เพิ่ม 1 entry ก็ใช้ UI เดิม |
| Cron / Routines | **มีครบแล้ว** — `hermes cron create` พร้อม `--script`/`--skills`/`--deliver` (ดู [hermes-already-has-routines.md](../../hermes-already-has-routines.md)) | path B ต่อยอด: cron prompt เรียก `claude_code_task` |
| MCP server | Hermes รัน `hermes mcp serve` อยู่แล้ว (client ต่อเข้า) ([mcp_serve.py](../../mcp_serve.py)) | Claude Code ต่อเข้ามาดึง context ได้ |
| Token tracking | `sessions` table มี `input/output_tokens`, `billing_provider` แต่**ไม่มี field แยกที่มา** ([hermes_state.py:190-222](../../hermes_state.py#L190)) | เพิ่มมิติ `agent_kind` (PR 4.1) |
| Vibe Code page | [VibeCodePage.tsx](../../web/src/pages/VibeCodePage.tsx) + ProjectView; chat ปัจจุบันผูก Hermes session | ต้อง re-wire ไป Claude Code session (PR 2.x) |
| Analytics chart | chart token รายวัน React ล้วน + `/api/analytics/usage` คืน `by_model[]` ([AnalyticsPage.tsx:131](../../web/src/pages/AnalyticsPage.tsx#L131)) | ต่อยอด multi-select + filter ≥1 req |

> งานที่ "ยังไม่มี": (1) wire Vibe Code chat → Claude Code session ตรง, (2) headless `claude_code_task` สำหรับ cron, (3) token attribution แยก, (4) UI การ์ด/chart. ส่วน mount, env, cron, MCP, analytics base มีของเดิมรองรับ

---

## 5. ข้อกังวล 3 ข้อ — ถูกแก้ด้วย architecture ใหม่

- **Q1 ติด loop กิน token** → path interactive: user คุมเอง + Claude Code มี `--max-turns`; path headless: `claude_code_task` บังคับ budget/timeout, เกินแล้ว kill
- **Q2 token 2 ต่อ** → **หายไปใน Vibe Code** เพราะ user คุย Claude Code ตรง ไม่มี Hermes relay; เหลือเฉพาะ path cron ซึ่งเป็น automation ที่ตั้งใจ
- **Q3 จำ state ไม่ได้** → ใช้ Claude Code session/`--resume` ผูกกับ project id (มีในตัว) + progress file ใน workspace

---

## 5.1 Skills — flow เดิมอยู่ครบไหม? (ครบ + reuse ได้)

ข่าวดี: **Hermes กับ Claude Code ใช้ฐาน format เดียวกัน** — `SKILL.md` + YAML frontmatter (`name`/`description`, มาตรฐาน agentskills.io) ต่างกันแค่วิธีเรียก + metadata namespace

| | Panel (Hermes) | Vibe Code (Claude Code) |
|---|---|---|
| Skill flow เดิม | **ไม่แตะ ทำงาน 100%** — `hermes cron --skills`, `skills_list`/`skill_view`, slash `/skill-name`, preload | ใช้ skill system ของ Claude Code (`Skill` tool / `.claude/skills`) |
| Discovery | `skills_list` → metadata, `skill_view` → full ([skills_tool.py:550](../../tools/skills_tool.py#L550)) | Skill tool เรียกตรง |
| Invocation | slash command / preload `--skills` ([cli.py:14333](../../cli.py#L14333)) | agent เรียก Skill tool |
| metadata | `metadata.hermes.*` | namespace ของ Claude Code |

**Reuse:** skills เดิมใน `~/.hermes/skills/` (`sopify-sdlc-backend`, `sopify-sdlc-database`, `yuanbao`) เอามาใช้กับ Claude Code ได้ โดย expose dir เดียวกันเข้า `.claude/skills` (PR 2.4) — body ของ skill ใช้ร่วม, ต่างแค่ invocation + metadata namespace

**ตรง problem statement:** เดิม "ติด loop ทั้งที่ใช้ skills แล้ว" = skill ดีอยู่แล้วแต่ Hermes รันไม่ไหว → ให้ Claude Code (engine coding เก่งกว่า) ใช้ skills ชุดเดิม = skill ไม่เสียเปล่า แค่เปลี่ยนคนรัน

---

## 6. แผนทำงานแบบ PR เล็ก ๆ (Atomic PRs)

> PR เล็ก atomic ทีละชิ้น (feature branch → `development`), merge ทีละอัน · ทุก PR ต้อง run/boot จริง ไม่ใช่แค่ syntax check

### Phase 0 — Spike (ไม่ merge)
ยืนยันใน sandbox: เรียก `claude` ได้, ตั้ง `ANTHROPIC_BASE_URL` แล้วต่อ provider (share credential) สำเร็จ, Claude Code ต่อ `hermes mcp serve` เห็น context, token ถูกนับ
- *Output:* ตอบ open questions §8 ด้วยข้อมูลจริง

### Phase 1 — Foundation
- **PR 1.1** — Bake Claude Code (pin version) ลง [Dockerfile](../../docker/sopify-sandbox/Dockerfile); rebuild `sopify-sandbox:latest`
  - *Test:* `sbx exec -- claude --version`
- **PR 1.2** — Inject + verify `ANTHROPIC_BASE_URL` (+ share credential ของ Hermes) ใน [sbx_launcher.py:684](../../plugins/sopify_sandbox/sbx_launcher.py#L684); ยืนยัน `/home/sopify/.hermes` resolves
  - *Test:* `sbx exec -- printenv ANTHROPIC_BASE_URL` + `ls /home/sopify/.hermes`
- **PR 1.3** — เพิ่ม `ANTHROPIC_BASE_URL` เข้า `OPTIONAL_ENV_VARS` (กลุ่ม provider) → ใช้หน้า `/env` เดิม; รองรับสลับค่าได้ (decision #2)
  - *Test:* boot dashboard → แก้ค่า `/env` → ยืนยันเขียนลง `.env`

### Phase 2 — Surface A: Vibe Code คุย Claude Code ตรง
- **PR 2.1** — Backend session bridge: API เปิด/ต่อ Claude Code session ผูกกับ Vibe Code project id (interactive, `--resume`)
  - *Test:* สร้าง project → เปิด session → ส่ง 1 prompt แก้ไฟล์ → ไฟล์เปลี่ยนจริง
- **PR 2.2** — Frontend re-wire: chat ใน [VibeCodePage.tsx](../../web/src/pages/VibeCodePage.tsx)/ProjectView route ไป Claude Code session แทน Hermes
  - *Test:* boot SPA → คุยใน Vibe Code → คำตอบมาจาก Claude Code, ไม่มี Hermes ในวง
- **PR 2.3** — Persistent state: เก็บ session mapping + progress file ใน `.hermes`; เปิด project ซ้ำจำ context ได้
  - *Test:* คุย 2 รอบคนละครั้งเปิด → รอบ 2 จำของรอบ 1
- **PR 2.4** — Skills bridge: expose `~/.hermes/skills/` ให้ Claude Code เห็น (mount/symlink → `.claude/skills`) เพื่อ reuse skills เดิม (ดู §5.1)
  - *Test:* skill เดิม (เช่น `sopify-sdlc-backend`) เรียกได้จาก Claude Code ใน Vibe Code

### Phase 3 — Surface B: Hermes cron เรียก Claude Code (headless)
- **PR 3.1** — Headless tool `claude_code_task` (non-interactive, params: `task`/`working_dir`/`max_turns`/`budget_tokens`/`timeout`; loop guard + kill เมื่อเกิน)
  - *Test:* เรียก tool ตรง ๆ ให้แก้ไฟล์ → ได้สรุป diff/test กลับ; ตั้ง cap ต่ำ → ถูกตัด
- **PR 3.2** — เชื่อมกับ cron: prompt/`--script` ของ `hermes cron create` เรียก `claude_code_task` ได้ (ดู [hermes-already-has-routines.md](../../hermes-already-has-routines.md))
  - *Test:* ตั้ง cron interval สั้น สั่ง Claude Code task → ทำงานตามเวลา + deliver ผล
- **PR 3.3** — Skills passthrough: `--skills` ของ `hermes cron` ส่งต่อให้ `claude_code_task` โหลดเป็น Claude Code skill (automation ได้ skill เหมือน interactive)
  - *Test:* cron `--skills sopify-sdlc-backend` สั่ง Claude Code task → ยืนยัน skill ถูกโหลด

### Phase 4 — Token Attribution
- **PR 4.1** — schema: เพิ่มมิติ `agent_kind` (`hermes` | `claude_code`) ใน [hermes_state.py:190](../../hermes_state.py#L190) + migration
  - *Test:* รัน 1 Claude Code task → query เห็น tag `claude_code`
- **PR 4.2** — `/api/analytics/usage` แตก breakdown ตาม `agent_kind` + flag model ที่มี ≥1 req
  - *Test:* curl → เห็น 2 ฝั่งแยก

### Phase 5 — UI Monitoring (decision #4)
- **PR 5.1** — Vibe Code: การ์ด 2 ใบ (Token Usage Claude Code / Token Usage Hermes) ตามเอกสารเดิม
  - *Test:* boot SPA → การ์ดแสดงเลขจริง
- **PR 5.2** — Bar chart multi-select model (Token In/Out), แสดงเฉพาะ model ที่เคยมี ≥1 req ([AnalyticsPage.tsx:131](../../web/src/pages/AnalyticsPage.tsx#L131))
  - *Test:* เลือกหลาย model พร้อมกัน → chart อัปเดต; model ไม่เคยใช้ไม่โผล่

### Phase 6 — Polish & Docs
- **PR 6.1** — trace ด้วย raw fd write (ไม่ใช่ stdio ที่ถูก patch — patchStderr/patchConsole กลืน trace เงียบ ๆ); error handling ครบ
- **PR 6.2** — อัปเดต [SYSTEM_ARCHITECTURE.md](../../SYSTEM_ARCHITECTURE.md) เพิ่มส่วน Claude Code (2 surface + cron path)

---

## 7. ความเสี่ยง (Risks)

| ความเสี่ยง | การลด |
|---|---|
| Loop กิน token (path headless) | budget cap + max-turns + timeout + kill (PR 3.1) |
| Context bridge ตอน boundary ส่งข้อมูลมาก/เปลือง | ส่งเฉพาะ context ที่เกี่ยว, ครั้งเดียวตอน enter |
| Re-wire chat ใน Vibe Code กระทบ session เดิม | feature flag / แยก route ก่อน cutover |
| Provider routing (base_url สลับได้) ผิดพลาด | validate ใน Phase 0; default = Anthropic |
| Image ใหญ่/build นาน | pin version, layer cache |
| node_modules hoisting เพี้ยน (declared ^4 อาจ resolve เป็น v3) | ตรวจเวอร์ชันที่ install จริง ไม่เชื่อ declared |

---

## 8. Open Questions (ค้างให้เคลียร์ระหว่าง Phase 0)
1. Context bridge ตอน enter Vibe Code — ส่ง context อะไรบ้างให้ Claude Code (persistent memory ทั้งหมด? เฉพาะ project-related?)
2. `claude_code_task` headless — default budget/timeout เท่าไรถึงพอดี (กันทั้ง loop และไม่ตัดงานจริงทิ้ง)
3. relay endpoint สำหรับ model ราคาถูก — ใช้ตัวไหน (OpenRouter / Nous / self-host shim) ที่ Anthropic-compatible

---

## 9. นอกขอบเขต (Future)
- Cloud Gateway เชื่อม User + Cloud (phase อื่น)
- Multi Claude Code ขนานหลาย task
- ย้ายทุก coding flow มา Claude Code (ค่อยเปลี่ยนหลัง demo)

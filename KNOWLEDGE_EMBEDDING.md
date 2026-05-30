# Hermes — กลไกการ Embed ความรู้

**Status:** Reference doc (rev 0.1, 2026-05-30). อธิบายว่า Hermes (agent runtime ที่ Sopify fork มา) ฉีดความรู้เข้าไปยัง agent อย่างไร และจุดเชื่อมต่อใดบ้างที่ใช้ปรับ/เพิ่มความรู้ได้

> **TL;DR** — Hermes **ไม่ใช้ vector search / RAG** ไม่มี embeddings ของ Pinecone/Chroma/Faiss ทั้งหมดทำผ่าน **explicit context loading** (โหลดไฟล์ markdown ทั้งก้อนเข้า system prompt) แล้วใช้ **Anthropic prompt caching** ลดต้นทุนลง ~75% ปรัชญาคือ "เห็นทั้งไฟล์ดีกว่าเห็นเศษเสี้ยวที่ retrieve มาผิด"

---

## สารบัญ

1. [ภาพรวม](#1-ภาพรวม)
2. [System Prompt Composition](#2-system-prompt-composition)
3. [Skills System](#3-skills-system)
4. [Memory — Session + Persistent](#4-memory--session--persistent)
5. [Tools & MCP](#5-tools--mcp)
6. [Plugins — Runtime augmentation](#6-plugins--runtime-augmentation)
7. [Prompt Caching](#7-prompt-caching)
8. [Project-local Context (Vibe-specific)](#8-project-local-context-vibe-specific)
9. [วิธีเพิ่มความรู้ใหม่](#9-วิธีเพิ่มความรู้ใหม่)
10. [Trade-offs ของการไม่ใช้ RAG](#10-trade-offs-ของการไม่ใช้-rag)

---

## 1. ภาพรวม

ความรู้ที่ agent ใช้ในแต่ละ turn มาจาก **4 ช่องทางหลัก** ที่ประกอบกันเป็น input ของ model:

```
┌─────────────────────────────────────────────────────────┐
│  System Prompt (text ก้อนเดียว ที่ฉีดทุก turn)             │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ Stable tier   — identity, tool guidance              │ │ ← cache hit สูง
│  │ Context tier  — AGENTS.md / CLAUDE.md / phase prompt │ │
│  │ Volatile tier — memory snippets, recent turns        │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  Skills Index (one-line bullets ของ skill ที่ load ได้)   │
│  Tool Schemas (tools=[...] ใน API request)               │
└─────────────────────────────────────────────────────────┘
                          ↓
              Anthropic Messages API
                          ↓
             Cache-marked breakpoints
              (~75% input cost cut)
```

ไม่มี vector retrieval, ไม่มี embedding lookup, ไม่มี chunking — มี **explicit composition** ของ markdown ไฟล์ที่อยู่ใน repo

---

## 2. System Prompt Composition

ทุก turn agent ได้ system prompt ที่ประกอบจากหลายชั้น เรียงจาก stable (เสถียร, cache hit สูง) → context (ตาม project) → volatile (เปลี่ยนทุก turn)

| Function | ตำแหน่ง | บทบาท |
|---|---|---|
| `build_system_prompt_parts()` | [agent/system_prompt.py:60](agent/system_prompt.py#L60) | Orchestrator หลัก แบ่ง prompt เป็น 3 tier |
| `build_system_prompt()` | [agent/system_prompt.py:287](agent/system_prompt.py#L287) | รวม tier ทั้งหมดเป็น string ก่อนยิงไป model |
| `MemoryManager.build_system_prompt()` | [agent/memory_manager.py:318](agent/memory_manager.py#L318) | ห่อ memory ด้วย `<memory-context>` fence แล้ว inject เข้า prompt |

### Vibe-specific composition

สำหรับ Vibe Code project, system prompt ถูกประกอบโดย `_vibe_compose_system_prompt()` ที่ [hermes_cli/web_server.py:5426](hermes_cli/web_server.py#L5426) — stack ไฟล์ markdown ตามลำดับ:

```
prompts/vibe/base.md
  ↓
prompts/vibe/modes/<mode>.md           (web-app | dashboard | landing-page | form-registration)
  ↓
prompts/vibe/add-ons/<addon>.md        (auth-jwt, database-supabase, dark-mode, file-upload, ...)
  ↓
prompts/vibe/phases/<phase>.md         (brainstorm | design | backend | improvement | security | approve)
```

ดังนั้น "ความรู้ที่ embed" ของ Vibe Code agent = ไฟล์ทั้งหมดใน [prompts/vibe/](prompts/vibe/) ที่ slice ตาม mode + add-ons + phase ของ project

---

## 3. Skills System

Skill เป็น **markdown ไฟล์ที่ agent โหลดเองตามต้องการ** ไม่ได้ inject เต็มไฟล์ตั้งแต่แรก เพื่อไม่ให้ system prompt บวม

### กลไก

`build_skills_system_prompt()` ที่ [agent/prompt_builder.py:997](agent/prompt_builder.py#L997) สแกน:
- `~/.hermes/skills/` (user-installed)
- Bundled skills ใน [skills/](skills/) (90+ skills)

แล้วสร้าง **index แบบ compact** (1-2 บรรทัดต่อ skill) ฉีดเข้า system prompt — มีลักษณะ "ถ้าเจองาน X ให้ load skill Y"

### โครงสร้าง skill

แต่ละ skill ที่ [skills/<name>/SKILL.md](skills/) มี:

```markdown
---
name: claude-code-security-review
description: Review code for security vulnerabilities
version: 1.0.0
platforms: [linux, macos]
---

# (เนื้อหา markdown — โหลดเฉพาะตอน agent decide ว่าจะใช้)
```

**Frontmatter** เป็นสิ่งที่ index เห็น; **เนื้อหาเต็ม** โหลดเฉพาะตอน agent เรียกใช้

นี่คือเหตุผลที่ Sopify มี 90+ skills แต่ system prompt ไม่บวม

### Lifecycle

- เพิ่ม/ลบ/แก้ skill → [hermes_cli/skills_hub.py](hermes_cli/skills_hub.py) จัดการ enable/disable
- Cache invalidation: `clear_skills_system_prompt_cache()` ที่ [agent/prompt_builder.py:852](agent/prompt_builder.py#L852) — clear in-process LRU + disk snapshot

---

## 4. Memory — Session + Persistent

### Session memory (per-conversation)

Message history ของ turn ปัจจุบัน + **trajectory compression** เมื่อ token เกิน:

- Drop early turns
- Compress tool details (เก็บแค่ tool name + result summary)
- Keep recent + important

`MemoryManager` ที่ [agent/memory_manager.py](agent/memory_manager.py) เป็น orchestrator

### Persistent memory (cross-session)

โหลดผ่าน **memory provider plugin** — default ของ Sopify ใช้ SQLite local; provider abstract อยู่ที่ [agent/memory_provider.py](agent/memory_provider.py)

Plugin จริงๆ ที่ใช้งานอยู่ใน [plugins/sopify_providers/](plugins/sopify_providers/)

### Project guidance (auto-injected)

Agent หา **CLAUDE.md** หรือ **AGENTS.md** ใน cwd อัตโนมัติแล้วโหลดทั้งไฟล์เข้า context tier ของ system prompt — เป็น session-specific guidance ที่ user เขียนกำกับ project

---

## 5. Tools & MCP

Tools ไม่ใช่ "ความรู้แบบ knowledge base" แต่เป็น **schema ที่ฉีดเข้า model API request** ผ่าน parameter `tools=[...]` ทำให้ model "รู้ว่าทำอะไรได้"

| Layer | ตำแหน่ง | หน้าที่ |
|---|---|---|
| Built-in tool registry | [tools/registry.py](tools/registry.py) | `discover_builtin_tools()` import tool modules ที่ self-register |
| Schema sanitizer | [tools/schema_sanitizer.py](tools/schema_sanitizer.py) | Strip sensitive params ก่อนส่งไปให้ model |
| MCP bridge | [mcp_serve.py](mcp_serve.py) | `create_mcp_server()` expose FastMCP server (stdio) สำหรับ Claude Code / Cursor / Codex |

Tool schemas ส่งเข้า model พร้อม system prompt ในทุก request — model ตัดสินใจเองว่าจะเรียกตัวไหนเมื่อใด

---

## 6. Plugins — Runtime augmentation

Plugin ของ Hermes ทำงานผ่าน **lifecycle hooks 14+ ตัว** ที่ [hermes_cli/plugins.py:128](hermes_cli/plugins.py#L128):

```
pre_tool_call      → ก่อนเรียก tool
post_tool_call     → หลัง tool return
pre_gateway_dispatch → ก่อนส่งไป model
transform_llm_output → หลัง model response กลับ
pre_session_save   → ก่อนเซฟ session
... (ฯลฯ)
```

### Plugins ของ Sopify

| Plugin | บทบาท |
|---|---|
| [plugins/sopify_providers/](plugins/sopify_providers/) | Credential routing, model provider chain (Anthropic → OpenRouter → fallback) |
| [plugins/sopify_modes/](plugins/sopify_modes/) | เปลี่ยน agent persona ตาม mode (code-with-you, company-sop, living-employee) |
| [plugins/sopify_daemon/](plugins/sopify_daemon/) | ENCM background tasks (network egress control) |

**ข้อสังเกต:** ไม่มี hook ชื่อ `system_prompt` ตรงๆ — plugin ปรับ knowledge ได้ผ่าน:
- `transform_llm_output` (หลัง response กลับ)
- Inject ผ่าน **tools** (เพิ่ม tool ใหม่ที่ wrap knowledge เป็น callable)
- Memory provider plugin (เพิ่มแหล่ง persistent memory)

---

## 7. Prompt Caching

`apply_anthropic_cache_control()` ที่ [agent/prompt_caching.py:49](agent/prompt_caching.py#L49) ใส่ marker:

```json
{"type": "ephemeral", "ttl": "5m"}
{"type": "ephemeral", "ttl": "1h"}
```

ที่จุดต่อไปนี้:
- ส่วน **stable + context** ของ system prompt
- **3 messages ล่าสุด** ที่ไม่ใช่ system

ผลลัพธ์:
- **~75% input token cost reduction** บน multi-turn conversation
- Cached prefix อยู่ในระบบ Anthropic ตลอด TTL — ส่ง request ใหม่ในกรอบเวลา → ดึง cache ทันที

นี่คือเหตุผลทาง economics ที่ Hermes เลือก **"ฉีดทั้งไฟล์เข้า prompt"** แทน RAG:
- Cache 200K tokens ราคา 10% ของไม่ cache
- ไม่ต้อง maintain vector DB / re-index / chunk
- Agent เห็น context ทั้งหมด → ตัดสินใจดีกว่า partial retrieval

---

## 8. Project-local Context (Vibe-specific)

Vibe Code project มี context มาจาก 2 ที่:

### 8.1 Agent-curated (เขียนโดย agent เอง)

| ไฟล์ | Phase ที่ใช้งาน |
|---|---|
| `REQUIREMENTS.md` | brainstorm → design |
| `DESIGN.md` | design → backend |
| `DATABASE.md`, `API.md` | backend → improvement |
| `SECURITY_REVIEW.md` | security → approve |

อ่านผ่าน `/api/vibe/projects/{name}` ที่ [hermes_cli/web_server.py:5406](hermes_cli/web_server.py#L5406) ส่งกลับให้ frontend แสดง

### 8.2 User-uploaded (เพิ่งเพิ่มในรอบ commit 2026-05-30)

`<project>/uploads/*.csv|*.xlsx|*.md|*.png|*.jpg|*.webp` — user upload ตอน create project ผ่านหน้า Vibe Code:

- **POST endpoint:** `/api/vibe/projects/{name}/uploads` ที่ [hermes_cli/web_server.py](hermes_cli/web_server.py) (commit `201ae35a0`)
- **Storage:** `/home/sopify/.hermes/vibe-projects/<name>/uploads/` แบน, ไม่มี subfolder ตามประเภท
- **Brainstorm prompt ที่สอน agent อ่าน:** [prompts/vibe/phases/brainstorm.md](prompts/vibe/phases/brainstorm.md) section "User-supplied context in `uploads/`" (commit `1095b58a8`)

Agent อ่านผ่าน file tools ปกติ (`ls`, `Read`, `Grep`, Python pandas) — ไม่ต้องผ่าน vector retrieval

---

## 9. วิธีเพิ่มความรู้ใหม่

3 ทางเลือก เลือกตามความถี่ในการใช้:

| ต้องการ | ช่องทาง | ตัวอย่าง |
|---|---|---|
| Agent **รู้ตลอดเวลา** ทุก turn ทุก session | แก้ไฟล์ใน [prompts/vibe/](prompts/vibe/) (Vibe) หรือ [agent/system_prompt.py](agent/system_prompt.py) (Hermes core) | เพิ่ม company-wide coding standard, brand voice |
| Agent **โหลดเฉพาะเมื่อต้องการ** | สร้าง skill ใน [skills/\<name\>/SKILL.md](skills/) | "วิธี deploy GS Battery ERP", "Standard PLC config" |
| ความรู้ **เฉพาะ project นั้น** | วางไฟล์ใน project folder (`AGENTS.md`, `uploads/<file>`) | Spec ของลูกค้ารายนี้, ภาพ wireframe |

### Cost vs awareness

```
แก้ system prompt    →  high awareness  +  prompt บวม  +  cost เพิ่ม (ลบล้างด้วย cache)
สร้าง skill          →  on-demand      +  index 1 บรรทัด  +  cost ต่ำกว่า
project file        →  scoped         +  ไม่กระทบ project อื่น  +  cost ต่ำสุด
```

---

## 10. Trade-offs ของการไม่ใช้ RAG

### ข้อดี

- **เรียบง่ายกว่า** — ไม่มี chunking, embedding, similarity threshold tuning, vector DB infra
- **Debug ง่ายกว่า** — system prompt เป็น text ก้อนเดียว ดูได้ที่ [hermes_cli/web_server.py system-prompt endpoint](hermes_cli/web_server.py)
- **Cost ต่ำกว่าที่คิด** — Anthropic cache absorb ~75% ของ input cost; effective rate ใกล้เคียง RAG ที่ต้องจ่ายค่า embedding + vector store
- **Quality สูงกว่า** — agent เห็น context ทั้งหมด ตัดสินใจดีกว่า partial retrieval ที่อาจ miss สิ่งสำคัญ
- **Reproducible** — knowledge state = git state ไม่มี out-of-band index ที่ต้อง re-sync

### ข้อจำกัด

- **Scale จำกัดที่ context window** — 200K (Sonnet) / 1M (Opus) tokens; เกินกว่านี้ต้อง compression หรือ skill split
- **Cold-cache penalty** — request แรกใน session ไม่มี cache; ถ้า prompt 100K tokens จะแพง ครั้งที่ 2 ขึ้นไปถูก
- **No semantic search** — ค้น "knowledge เกี่ยวกับ X" ทำไม่ได้อัตโนมัติ; ต้องโครงสร้าง folder + naming ให้ดี
- **Token efficiency** — ถ้าฉีด knowledge 500K tokens ที่ใช้จริง 5K, RAG จะคุ้มกว่าทาง bandwidth (แต่ Anthropic cache เกือบ neutralize ตรงนี้)

### เมื่อไรควรพิจารณาเพิ่ม RAG

- Knowledge base ใหญ่กว่า context window มากๆ (เช่น 10M+ tokens) ที่ใช้จริงแค่บางส่วน
- Knowledge มี high turnover (เปลี่ยนรายวัน) ทำให้ git commit จัดการลำบาก
- ต้อง semantic search แบบ end-user (เช่น customer support search) ไม่ใช่ agent-internal

ปัจจุบัน Sopify ยังไม่เข้าเงื่อนไขเหล่านี้ — โครงสร้างปัจจุบันเพียงพอสำหรับ Vibe Code + company SOP + employee Q&A workloads

---

## อ้างอิงไฟล์สำคัญ

| ส่วน | ไฟล์ |
|---|---|
| Prompt orchestration | [agent/system_prompt.py](agent/system_prompt.py), [agent/prompt_builder.py](agent/prompt_builder.py) |
| Memory | [agent/memory_manager.py](agent/memory_manager.py), [agent/memory_provider.py](agent/memory_provider.py) |
| Caching | [agent/prompt_caching.py](agent/prompt_caching.py) |
| Skills | [agent/prompt_builder.py:997](agent/prompt_builder.py#L997), [hermes_cli/skills_hub.py](hermes_cli/skills_hub.py), [skills/](skills/) |
| Tools / MCP | [tools/registry.py](tools/registry.py), [mcp_serve.py](mcp_serve.py) |
| Plugins | [hermes_cli/plugins.py](hermes_cli/plugins.py), [plugins/sopify_providers/](plugins/sopify_providers/), [plugins/sopify_modes/](plugins/sopify_modes/), [plugins/sopify_daemon/](plugins/sopify_daemon/) |
| Vibe composition | [hermes_cli/web_server.py:5426](hermes_cli/web_server.py#L5426), [prompts/vibe/](prompts/vibe/) |

---

**Companion docs:** [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) (end-to-end runtime picture) · [MODEL_SELECTION.md](MODEL_SELECTION.md) (model-per-phase policy) · [AGENTS.md](AGENTS.md) (agent config reference)

# Hermes Agent — Architecture Map (เอกสารทำความเข้าใจภายใน)

> เอกสารฉบับนี้สรุปสถาปัตยกรรมของ **Hermes Agent** (โดย Nous Research) ทุก layer
> ตั้งแต่ entry points จนถึง provider transports, tool/skill/plugin systems,
> messaging gateway, ACP adapter, TUI/Web UI, MCP server และ infrastructure
> เป้าหมายคือให้ทีม "เข้าใจ-เปลี่ยนแปลง-ขยาย" ได้โดยไม่ต้องไล่อ่านโค้ดเป็นแสนบรรทัด
>
> *อ้างอิงโค้ด*: ทุก section ใส่ `path:line` เพื่อให้เปิดได้ทันที
> *เวอร์ชัน*: snapshot ของ repo ณ commit ปัจจุบัน (ขนาดรวม ~3M LOC, Python + TS + Nix)

---

## 0. Mental Model สั้น ๆ ก่อนเริ่ม

Hermes เป็น **AI agent runtime** ที่ "เปิดให้ต่อ" ในทุกชั้น:

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Front-ends (ผู้ใช้คุยจากไหนก็ได้)                  │
│  ┌─────────┐  ┌──────────────┐  ┌────────────────┐  ┌─────────────┐│
│  │ CLI/TUI │  │ Web Dashboard│  │ Messaging       │  │ ACP (Zed/   ││
│  │ (Ink)   │  │ (React/Vite) │  │ (TG/Discord/…)  │  │  editors)   ││
│  └────┬────┘  └──────┬───────┘  └────────┬────────┘  └──────┬──────┘│
│       │              │                    │                  │       │
│       │ JSON-RPC     │ HTTP/WS            │ Platform-specific│ ACP   │
│       │ (tui_gateway)│ (web_server)       │ (gateway/)       │ stdio │
└───────┼──────────────┼────────────────────┼──────────────────┼──────┘
        ▼              ▼                    ▼                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│         AIAgent Core Runtime (run_agent.py + agent/)                  │
│   ┌──────────────────────────────────────────────────────────────┐  │
│   │  conversation_loop → context_engine → prompt_builder         │  │
│   │       │                                                       │  │
│   │       ▼                                                       │  │
│   │  ProviderTransport (chat_completions / anthropic / bedrock…)  │  │
│   │       │                                                       │  │
│   │       ▼                                                       │  │
│   │  tool_executor ── dispatch ──► tools/registry                 │  │
│   │       │                              ▲                        │  │
│   │       │                              │ register()             │  │
│   │       ▼                       ┌──────┴────────┐               │  │
│   │  state.db / trajectory        │ plugins/ , skills/ , MCP tools│  │
│   │  curator / memory_manager     └───────────────┘               │  │
│   └──────────────────────────────────────────────────────────────┘  │
│   Pluggable: providers/, plugins/, tools/, skills/                   │
└──────────────────────────────────────────────────────────────────────┘
```

**ห้าหลักการที่ทำให้สถาปัตยกรรมนี้ขยายได้:**

1. **Self-registration**: ทุก tool / plugin / provider ลงทะเบียนตัวเองตอน import (`registry.register(...)`) — ไม่มี master list ให้ต้องแก้
2. **Lazy discovery**: AST scan + entry points + filesystem walk ที่เวลา startup เท่านั้น
3. **ContextVar-based async**: gateway/server หลายตัวรัน async โดยใช้ ContextVar กัน race condition
4. **Three fronts, one core**: messaging gateway + ACP + TUI gateway เป็น "หน้าด่าน" คนละชุด แต่ใช้ `AIAgent` ตัวเดียวกัน
5. **User overrides built-in**: ค้นหา bundled → `~/.hermes/` → project `./.hermes/` → pip entry points — last-writer-wins

---

## 1. โครงสร้างไฟล์ระดับสูง (Repo Layout)

```
hermes-agent/
├── run_agent.py              4,149 lines  ← AIAgent class + main loop forwarder
├── cli.py                   14,512 lines  ← Interactive REPL (legacy entry; main.py ใหม่)
├── hermes_state.py           3,273 lines  ← SQLite session DB + FTS5
├── hermes_bootstrap.py         129 lines  ← Windows UTF-8 stdio fix
├── hermes_constants.py         418 lines  ← HERMES_HOME, paths, defaults
├── hermes_logging.py           389 lines  ← Logging w/ session_id ContextVar
├── hermes_time.py              104 lines  ← TZ-aware datetime helpers
├── model_tools.py              923 lines  ← Tool discovery + dispatch glue
├── toolsets.py                 866 lines  ← Toolset categories
├── toolset_distributions.py    364 lines  ← Toolset presets (image_gen, etc.)
├── trajectory_compressor.py  1,508 lines  ← Compress trajectories for training
├── batch_runner.py           1,321 lines  ← Parallel trajectory generation
├── mini_swe_runner.py          735 lines  ← SWE-bench runner
├── mcp_serve.py                897 lines  ← Expose Hermes as MCP server
│
├── agent/                    ← Core runtime (82 modules)
├── tools/                    ← 76 built-in tools + registry
├── skills/                   ← 27 skill categories (bundled)
├── optional-skills/          ← 18 niche/heavy skill categories
├── plugins/                  ← 19 bundled plugins
├── providers/                ← Provider base + legacy profiles
├── gateway/                  ← 20+ messaging platforms
├── gateway/platforms/        ← per-platform adapters
├── acp_adapter/              ← Agent Client Protocol (Zed integration)
├── acp_registry/             ← ACP metadata
├── tui_gateway/              ← WS bridge for Ink TUI
├── ui-tui/                   ← Ink/React/TS terminal UI
├── web/                      ← React/Vite/TS dashboard
├── hermes_cli/               ← 80+ CLI modules (the "hermes" command)
├── tests/                    ← ~1,000 test files
├── docs/, plans/, .plans/    ← Docs + planning notes
├── cron/, locales/           ← Cron schedules + i18n
├── scripts/, packaging/      ← Installers, release tooling
├── docker/, nix/             ← Container + Nix flake
└── website/                  ← Marketing site (separate)
```

---

## 2. RING 1 — Entry Points

มี **5 entry points หลัก** ที่ pyproject.toml lines 209–212 ประกาศ:

| Entry Point | Module | Purpose |
|---|---|---|
| `hermes` | `hermes_cli.main:main` | Interactive CLI / setup / gateway / kanban / config |
| `hermes-agent` | `run_agent:main` | Direct agent loop (รัน trajectory headless) |
| `hermes-acp` | `acp_adapter.entry:main` | ACP server สำหรับ Zed editor |
| MCP serve | `python mcp_serve.py` | MCP server เปิด Hermes session ให้ Claude Code/Cursor |
| TUI gateway | `python -m tui_gateway` | WS subprocess สำหรับ Ink TUI |

ทั้งหมดเรียกเข้า `AIAgent(...)` class ใน `run_agent.py:350+`

**ลำดับ bootstrap (`hermes` command):**

1. Shell wrapper `hermes` (262 bytes) → `python -m hermes_cli.main`
2. `hermes_cli/main.py:110-150` parse `--profile` ก่อน argparse → set `HERMES_HOME`
3. `_parser.py:build_top_level_parser()` สร้าง argparse hierarchy
4. Dispatch ไปยัง `cmd_*` callback (e.g. `cmd_chat`, `cmd_setup`, `cmd_gateway`)
5. `cmd_chat()` instantiate `AIAgent`, spawn Ink TUI subprocess
6. TUI ← JSON-RPC over stdio → `tui_gateway.server` → `AIAgent.run_conversation()`

**Gotchas:**
- `hermes_bootstrap` ต้อง import ก่อนสุดบน Windows (utf-8 stdio); `run_agent.py:24-32` จัดให้
- OpenAI SDK เป็น **lazy proxy** (`run_agent.py:56-83`) — ยังไม่ import จริงจนกว่าจะใช้ครั้งแรก (~240ms cold import saved)

---

## 3. RING 2 — Core Conversation Loop (`agent/`)

หัวใจของ Hermes อยู่ที่ `agent/conversation_loop.py:run_conversation()` (~3,900 บรรทัด ถูกถอดออกมาจาก `run_agent.py`)

### 3.1 Flow ของ 1 turn

```
user_message
    ↓
[1] restore_or_build_system_prompt()     ← เช็ค session DB ก่อน rebuild (prefix-cache)
[2] build messages list                   ← system + history + memory + user
[3] context_compressor.should_compress()  ← gate ที่ 75% ของ context limit
    ├─ True  → compress() (auxiliary model summarize middle turns)
    └─ False → ส่งตรง
[4] transport.convert_messages() / convert_tools() / build_kwargs()
[5] client.create(**kwargs)               ← LLM call
    ├─ Success → normalize_response()
    └─ Error   → classify_api_error() → retry / failover / compress / abort
[6] iteration_budget.decrement()
[7] if response.tool_calls:
        execute_tool_calls_concurrent() / _sequential()
        append tool results to messages
        loop to [4]
    else:
        exit
[8] save_trajectory() + persist system_prompt to session DB
[9] queue background curator + memory prefetch (non-blocking)
[10] return {final_response, usage, cost, messages, tool_calls}
```

### 3.2 ไฟล์ที่สำคัญใน `agent/`

| โซน | Modules | บทบาท |
|---|---|---|
| **Loop** | `conversation_loop.py`, `agent_runtime_helpers.py`, `agent_init.py`, `process_bootstrap.py`, `iteration_budget.py` | initialize/run agent, manage budget |
| **Tool execution** | `tool_executor.py`, `tool_dispatch_helpers.py`, `tool_guardrails.py`, `tool_result_classification.py` | concurrent vs sequential dispatch, pre-flight guardrails, classify mutation/error |
| **Transports** | `transports/base.py`, `transports/anthropic.py`, `transports/chat_completions.py`, `transports/bedrock.py`, `transports/codex.py`, `transports/codex_app_server.py`, `transports/hermes_tools_mcp_server.py` | abstract LLM API differences |
| **Provider adapters** | `anthropic_adapter.py`, `bedrock_adapter.py`, `codex_responses_adapter.py`, `gemini_native_adapter.py`, `gemini_cloudcode_adapter.py`, `gemini_schema.py`, `google_oauth.py`, `google_code_assist.py`, `azure_identity_adapter.py`, `lmstudio_reasoning.py`, `moonshot_schema.py`, `nous_rate_guard.py` | จัดการ quirks ระดับลึก เช่น OAuth refresh, cache-control, schema massage |
| **Context engineering** | `context_engine.py` (ABC), `context_compressor.py`, `context_references.py`, `conversation_compression.py`, `prompt_builder.py`, `prompt_caching.py`, `system_prompt.py`, `subdirectory_hints.py`, `trajectory.py` | สร้าง prompt + บีบประวัติ |
| **Memory + Learning** | `curator.py`, `curator_backup.py`, `memory_manager.py`, `memory_provider.py` (ABC), `insights.py`, `onboarding.py` | self-improvement loop (skill curation + memory sync) |
| **Skills** | `skill_bundles.py`, `skill_commands.py`, `skill_preprocessing.py`, `skill_utils.py` | load skills เข้าเป็น context |
| **Models** | `model_metadata.py`, `models_dev.py`, `usage_pricing.py`, `rate_limit_tracker.py` | catalog + pricing + RL tracking |
| **Safety** | `redact.py`, `message_sanitization.py`, `think_scrubber.py`, `file_safety.py`, `error_classifier.py`, `retry_utils.py` | PII redact, scrub `<think>` blocks, classify errors |
| **Plugins glue** | `plugin_llm.py`, `image_gen_provider.py`, `image_gen_registry.py`, `image_routing.py`, `video_gen_provider.py`, `video_gen_registry.py`, `web_search_provider.py`, `web_search_registry.py`, `browser_provider.py`, `browser_registry.py` | provider registries สำหรับ plugin |
| **LSP** | `lsp/manager.py`, `lsp/client.py`, `lsp/protocol.py`, `lsp/eventlog.py`, `lsp/servers.py`, `lsp/workspace.py`, `lsp/range_shift.py` | language server protocol สำหรับ tool ที่อ่าน symbol |
| **Display/i18n** | `display.py`, `i18n.py`, `title_generator.py`, `background_review.py`, `stream_diag.py`, `markdown_tables.py`, `manual_compression_feedback.py`, `account_usage.py`, `async_utils.py`, `auxiliary_client.py`, `chat_completion_helpers.py`, `codex_runtime.py`, `copilot_acp_client.py`, `credential_pool.py`, `credential_sources.py`, `portal_tags.py`, `shell_hooks.py` | UX + helpers |

### 3.3 Context Compression (สำคัญ)

`agent/context_compressor.py` (~1,800 lines) เป็น context engine ตั้งต้น:

- `threshold_percent = 0.75` — บีบเมื่อใช้ 75% ของ context window
- `protect_first_n = 3`, `protect_last_n = 6` — head/tail ห้ามแตะ
- `_MIN_SUMMARY_TOKENS = 2000`, `_SUMMARY_RATIO = 0.20` — summary ต้องคุ้ม
- เรียก **auxiliary model** (cheaper, ใช้ `default_aux_model` ของ provider) เพื่อสรุป middle turns
- มี gates 2 จุด: **pre-flight** (estimate ก่อนยิง API) และ **post-response** (ใช้ token count จริง)

### 3.4 Failover (resilience)

`agent/error_classifier.py:classify_api_error()` map HTTP/message → `FailoverReason` enum:

| Reason | Action |
|---|---|
| `rate_limit` | jittered backoff → rotate credential → retry |
| `context_overflow` | trigger compression → retry |
| `auth` | refresh OAuth (Anthropic) → retry → abort if fails |
| `model_not_found` | tier-down (Sonnet → Haiku) → retry |
| `provider_outage` | switch provider → retry |

ลำดับ failover ไม่ใช่ round-robin — **credential rotation → tier-down → provider switch** (เพราะ credential rotation ถูกที่สุด)

---

## 4. RING 3 — Tools Layer (`tools/`)

### 4.1 Registry & Discovery (`tools/registry.py`, 590 lines)

- `ToolRegistry` singleton — thread-safe, **30-second TTL cache** บน availability check
- Tools register ตัวเองตอน import: `registry.register(name, toolset, schema, handler, check_fn, ...)`
- **AST scan**: `discover_builtin_tools()` walk `tools/*.py` หาไฟล์ที่มี `registry.register(...)` ที่ top-level — ไม่ต้องมี master list
- `RLock` + generation counter ป้องกัน race เวลา MCP เพิ่ม tool runtime
- Async handlers bridge สู่ sync context อัตโนมัติด้วย `_run_async()` ใน `model_tools.py:84-100`

### 4.2 หมวด tools (~76 ตัว, 55+ ไฟล์)

| หมวด | ไฟล์ |
|---|---|
| **Security / Approval** | `approval.py`, `path_security.py`, `url_safety.py`, `skills_guard.py`, `tirith_security.py`, `website_policy.py` |
| **Filesystem** | `file_operations.py`, `file_state.py`, `file_tools.py`, `patch_parser.py`, `binary_extensions.py`, `fuzzy_match.py` |
| **Terminal / Process** | `terminal_tool.py`, `process_registry.py`, `checkpoint_manager.py`, `environments/`, `env_passthrough.py` |
| **Browser / Computer Use** | `browser_camofox.py`, `browser_camofox_state.py`, `browser_cdp_tool.py`, `browser_dialog_tool.py`, `browser_supervisor.py`, `browser_tool.py`, `computer_use/`, `computer_use_tool.py` |
| **MCP** | `mcp_tool.py`, `mcp_oauth.py`, `mcp_oauth_manager.py`, `managed_tool_gateway.py` |
| **Self-management** | `skill_manager_tool.py`, `skill_provenance.py`, `skill_usage.py`, `skills_hub.py`, `skills_sync.py`, `skills_tool.py`, `memory_tool.py`, `session_search_tool.py`, `todo_tool.py`, `kanban_tools.py`, `cronjob_tools.py` |
| **Coordination** | `delegate_tool.py`, `mixture_of_agents_tool.py`, `clarify_tool.py`, `clarify_gateway.py`, `send_message_tool.py` |
| **External** | `web_tools.py`, `x_search_tool.py`, `yuanbao_tools.py`, `feishu_doc_tool.py`, `feishu_drive_tool.py`, `microsoft_graph_auth.py`, `microsoft_graph_client.py`, `discord_tool.py`, `homeassistant_tool.py` |
| **Media / Code Exec** | `code_execution_tool.py`, `image_generation_tool.py`, `video_generation_tool.py`, `vision_tools.py`, `tts_tool.py`, `transcription_tools.py`, `voice_mode.py`, `neutts_synth.py` |
| **Utils** | `openrouter_client.py`, `xai_http.py`, `osv_check.py`, `credential_files.py`, `schema_sanitizer.py`, `slash_confirm.py`, `interrupt.py`, `budget_config.py`, `tool_output_limits.py`, `tool_result_storage.py`, `tool_backend_helpers.py`, `lazy_deps.py`, `debug_helpers.py`, `ansi_strip.py` |

### 4.3 Tool dispatch

```python
# model_tools.py
1. handle_function_call(tool_name, args, task_id)
2. → registry.dispatch(tool_name, args)
3.   ├─ lookup handler + async flag
4.   ├─ try: handler(**args)
5.   ├─ except: wrap error → JSON string
6. → return JSON string เป็น tool_result message
```

### 4.4 เพิ่ม tool ใหม่

**Built-in (repo)**: สร้าง `tools/your_tool.py` พร้อม `registry.register(...)` ระดับ module — auto-discovery หาเจอเอง

**Plugin (user)**: สร้าง `~/.hermes/plugins/<name>/__init__.py` + เรียก `ctx.register_tool(...)` ใน `register(ctx)` — Override built-in ได้ด้วย `override=True`

ดู `AGENTS.md:276-294` สำหรับ checklist เต็ม

---

## 5. RING 4 — Skills Layer (`skills/` + `optional-skills/`)

### 5.1 ความแตกต่าง

| | `skills/` | `optional-skills/` |
|---|---|---|
| Load default? | ✅ | ❌ ต้องสั่ง `hermes skills install official/...` |
| Use case | core productivity, lightweight | niche, heavy deps (blockchain, finance, health) |
| Count | 27 categories | 18 categories |

### 5.2 รูปแบบ SKILL.md

YAML frontmatter + prose:

```
---
name: my-skill
description: ≤60 chars หนัก ๆ
version: 0.1.0
author: ...
platforms: [linux, macos]
metadata:
  hermes:
    tags: [...]
    category: ...
    config: { ... }
---

# Title
## When to Use
## Prerequisites
## How to Run
## Quick Reference
## Procedure
## Pitfalls
## Verification
```

โครงสร้าง directory:
```
skills/<category>/<name>/
├── SKILL.md
├── scripts/        ← helper scripts ที่ skill เรียก
├── references/     ← เอกสารอ้างอิง
├── templates/      ← templates ที่ skill copy
└── tests/skills/test_<name>_skill.py
```

### 5.3 SkillSource (`tools/skills_hub.py`)

discovery มี 6 sources (`SkillSource` ABC ที่ line 294):

1. Bundled (`skills/`)
2. Optional (`optional-skills/`)
3. GitHub (ClaudeSkills standard format)
4. Marketplace (LobeHub, ClaudeBrowse, HermesIndex)
5. URL/tarball download
6. User/project disk (`~/.hermes/skills/`, `./.hermes/skills/`)

### 5.4 ทำงานยังไง

1. Init: `load_active_skills()` enumerate sources
2. SKILL.md content ถูก inject เป็น **user message** (ไม่ใช่ system) เพื่อรักษา prompt cache (`AGENTS.md:150`)
3. Model อ่าน description แล้วเรียก tools ที่ skill ระบุ
4. **Skills ไม่ใช่โค้ด** — เป็น context document

### 5.5 Curator (background self-improvement)

`agent/curator.py:maybe_run_curator()` (line 55+):
- รันเมื่อ idle > 2 ชั่วโมง และ last curator run > 7 วัน
- Fork สร้าง subagent ใหม่ (ไม่ block main turn)
- รีวิว skills: pin หากใช้บ่อย, archive หากไม่ใช้ 30/90 วัน, consolidate ที่ซ้ำ

### 5.6 27 หมวด skills (bundled)

`apple`, `autonomous-ai-agents`, `creative` (23 skills), `data-science`, `devops`, `diagramming`, `dogfood`, `domain`, `email`, `gaming`, `gifs`, `github` (9 skills), `index-cache`, `inference-sh`, `mcp`, `media`, `mlops` (10), `note-taking`, `productivity` (12), `red-teaming`, `research` (8), `smart-home`, `social-media`, `software-development` (13), `yuanbao`

---

## 6. RING 5 — Plugins Layer (`plugins/`)

### 6.1 Discovery (`hermes_cli/plugins.py:34-400`)

4 sources, last-writer-wins:

1. Bundled — `<repo>/plugins/<name>/`
2. User — `~/.hermes/plugins/<name>/`
3. Project — `./.hermes/plugins/<name>/` (opt-in via `HERMES_ENABLE_PROJECT_PLUGINS`)
4. Pip — packages with entry point group `hermes_agent.plugins`

ทุก plugin ต้องมี:
- `plugin.yaml` — manifest (name, kind, version, description, entry_point)
- `__init__.py` — มี `register(ctx: PluginContext)` function

### 6.2 19 bundled plugins

| Plugin | Subdir | บทบาท |
|---|---|---|
| browser | `browser/` | alternative browser backends |
| context_engine | `context_engine/` | สถาปัตยกรรม pluggable context (browser/code/conversation/email/file/memory/semantic/slack/ticket/web context) |
| disk-cleanup | `disk-cleanup/` | utility |
| example-dashboard | `example-dashboard/` | starter template |
| google_meet | `google_meet/` | meeting integration |
| hermes-achievements | `hermes-achievements/` | gamification |
| image_gen | `image_gen/` | DALL-E, Flux, Ideogram, MJ-API, OpenRouter, StabilityAI |
| kanban | `kanban/` | SQLite Kanban + multi-agent dispatcher |
| memory | `memory/` | honcho, mem0, supermemory, byterover, hindsight, holographic, openviking, retaindb |
| model-providers | `model-providers/` | 30+ providers (ดู section 7) |
| observability | `observability/` | metrics/traces |
| platforms | `platforms/` | gateway adapter plugins (ดู section 9) |
| spotify | `spotify/` | music |
| teams_pipeline | `teams_pipeline/` | MS Teams pipeline |
| video_gen | `video_gen/` | video generation |
| web | `web/` | web dashboard plugin |

### 6.3 PluginContext APIs

ใน `register(ctx)`:
- `ctx.register_tool(...)` — เพิ่ม tool (ผ่าน `tools.registry.register`)
- `ctx.register_memory_provider(...)` — เพิ่ม memory backend
- `ctx.register_platform(...)` — เพิ่ม messaging platform
- `ctx.register_cli_command(...)` — เพิ่ม sub-command
- Hooks: `register_pre_tool_call_hook`, `register_post_tool_call_hook`, lifecycle hooks

### 6.4 Memory provider plugin

ตัวอย่าง `plugins/memory/honcho/`:
- subclass `MemoryProvider` ABC (`agent/memory_provider.py`)
- Lifecycle hooks: `sync_turn()`, `prefetch()`, `shutdown()`, `post_setup()`
- ลงทะเบียนผ่าน `discover_plugin_memory_providers()`
- Orchestrated โดย `agent/memory_manager.py`

---

## 7. RING 6 — Providers Layer (`providers/`)

แยก discovery จาก plugin หลัก เพราะ provider โหลด lazy

### 7.1 ProviderProfile (`providers/base.py:38-184`)

```python
@dataclass
class ProviderProfile:
    name: str
    aliases: tuple[str, ...]
    api_mode: str       # "chat_completions" / "anthropic_messages" / "codex_responses"
    env_vars: tuple[str, ...]
    base_url: str
    auth_type: str      # "api_key" / "oauth_device_code" / "oauth_external" / "copilot" / "aws_sdk"
    fallback_models: tuple[str, ...]
    hostname: str | None
    default_aux_model: str | None
    fixed_temperature: float | None
    default_max_tokens: int | None

    # Overridable hooks
    def prepare_messages(msgs): ...      # provider-specific massage
    def build_extra_body(**ctx): ...     # extra_body fields
    def build_api_kwargs_extras(**ctx): ...
    def fetch_models(*, api_key): ...    # live catalog
```

### 7.2 Registry (`providers/__init__.py:53-191`)

- Lazy `_discover_providers()` ตอนถามครั้งแรก
- Scan order: `<repo>/plugins/model-providers/` → `$HERMES_HOME/plugins/model-providers/` → legacy `<repo>/providers/*.py`
- Last-writer-wins บน name; aliases รวมเป็น dict ที่สอง

### 7.3 30+ bundled providers

`anthropic`, `openrouter`, `gmi`, `deepseek`, `nvidia`, `kimi-coding`, `azure-foundry`, `bedrock`, `copilot`, `nous-portal`, `novita`, `xiaomi-mimo`, `z.ai/glm`, `kimi/moonshot`, `minimax`, `huggingface`, `openai`, ... ดูได้ใน `plugins/model-providers/`

### 7.4 ตัวอย่าง

```python
# plugins/model-providers/anthropic/__init__.py
anthropic = AnthropicProfile(
    name="anthropic",
    aliases=("claude", "claude-oauth", "claude-code"),
    api_mode="anthropic_messages",
    env_vars=("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"),
    base_url="https://api.anthropic.com",
    auth_type="api_key",
    default_aux_model="claude-haiku-4-5-20251001",
)
register_provider(anthropic)
```

### 7.5 ที่ profile ถูกใช้

- `hermes_cli/auth.py` — generate auth setup จากทุก env_var
- `hermes_cli/models.py` — `profile.fetch_models()` build live catalog
- `hermes_cli/doctor.py` — health check `/models` endpoint
- `agent/auxiliary_client.py` — อ่าน `default_aux_model` สำหรับ side tasks
- `agent/transports/chat_completions.py` — เรียก `prepare_messages`, `build_extra_body`, `build_api_kwargs_extras` ทุก call

---

## 8. Three Fronts — Messaging / ACP / TUI Gateway

Hermes มี **3 หน้าด่าน** ที่เชื่อมเข้า AIAgent ตัวเดียวกัน

### 8.1 Messaging Gateway (`gateway/`) — 20+ platforms

`gateway/run.py` (~18,200 lines) เป็น main event loop

**Core modules:**

| Module | บทบาท |
|---|---|
| `run.py` | lifecycle (start/stop adapter), agent LRU cache, route inbound → AIAgent |
| `config.py` | YAML/JSON/env config + Platform enum + StreamingConfig |
| `session.py` | `SessionSource(platform, chat_id, user_id, thread_id, ...)` + reset policy |
| `session_context.py` | ContextVar storage สำหรับ async concurrent |
| `delivery.py` | parse `"telegram:123"` / `"origin"` / `"local"` → route reply |
| `mirror.py`, `pairing.py`, `restart.py`, `status.py` | side concerns |
| `platform_registry.py` | plugin registration สำหรับ third-party adapters |
| `stream_consumer.py` | async ingestion จาก SDK |
| `slash_access.py`, `hooks.py`, `memory_monitor.py` | hooks + introspection |

**Platforms (`gateway/platforms/`)**

ทุก adapter inherit `BasePlatformAdapter` ใน `base.py` (~2,500 lines) — define methods: `send()`, `send_image()`, `send_document()`, `send_voice()`, `send_video()`, `send_animation()`, `send_typing()`, `connect()`, `disconnect()`, `cache_image_from_bytes()` etc.

| Adapter | ไฟล์ | Quirk |
|---|---|---|
| Telegram | `telegram.py` + `telegram_network.py` | topic threading, draft streaming (Bot API 9.5+), UTF-16 length |
| Discord | `discord.py` | guild-scoped, thread auto-create, history backfill |
| WhatsApp | `whatsapp.py` | webhook bridge, 24h session window |
| Slack | `slack.py` | channel vs DM, reaction polling |
| Signal | `signal.py` + `signal_rate_limit.py` | UUID identifiers, signal-cli subprocess |
| Email | `email.py` | SMTP/IMAP, thread reconstruction |
| SMS | `sms.py` | Twilio, 160-char concat |
| Matrix | `matrix.py` | room-scoped, sync token, E2E compat |
| Mattermost | `mattermost.py` | self-hosted Slack clone |
| Feishu (字节) | `feishu.py`, `feishu_comment.py`, `feishu_comment_rules.py` | card messages, app install scope |
| DingTalk | `dingtalk.py` | markdown + cards, robot mention |
| WeCom | `wecom.py`, `wecom_callback.py`, `wecom_crypto.py` | callbacks + crypto |
| QQ Bot | `qqbot/` | intents-based subscription |
| HomeAssistant | `homeassistant.py` | local-only HTTP |
| Weixin | `weixin.py` | access token refresh |
| Yuanbao (Alibaba) | `yuanbao.py`, `yuanbao_media.py`, `yuanbao_proto.py`, `yuanbao_sticker.py` | sticker caching |
| BlueBubbles | `bluebubbles.py` | Mac iMessage relay |
| API server | `api_server.py` | REST `/chat/{session_key}` |
| Webhook | `webhook.py`, `msgraph_webhook.py` | inbound HTTP / MS Graph subscriptions |

**Message flow ขาเข้า:**

```
Telegram user → /chat hello
    ↓ TelegramAdapter.connect() listener
    ↓ Parse: chat_id, user_id, message_id, thread_id
    ↓ self.build_source() → SessionSource(...)
    ↓ self.handle_message(MessageEvent) → gateway.run._route_inbound_message()
    ↓ SessionStore.get_or_create(session_source)
    ↓ should_reset(session, reset_policy)
    ↓ AIAgent.run_turn(session_id, context, message)
    ↓ Stream? → StreamConsumer (edit mode: progressive edit preview)
    ↓ adapter.send(chat_id, text, thread_id=…)
    ↓ Telegram sendMessage / editMessageText
```

**Streaming config (`gateway/config.py:StreamingConfig`):**
- `transport="edit"` — progressive `editMessageText` (default)
- `transport="draft"` — native draft updates (TG Bot API 9.5+)
- `edit_interval=0.8s` — < TG flood limit
- `buffer_threshold=24` — สะสม 24 tokens ก่อน edit
- `fresh_final_after_seconds=60` — > 60s → ส่ง final เป็น message ใหม่

**เพิ่ม platform ใหม่:**

แนะนำ **plugin path**: สร้าง `~/.hermes/plugins/platforms/<name>/`:
```
plugin.yaml
adapter.py            # subclass BasePlatformAdapter
__init__.py           # มี register(ctx) ที่เรียก ctx.register_platform(PlatformEntry(...))
```

Optional hooks: `env_enablement_fn`, `apply_yaml_config_fn`, `cron_deliver_env_var`, `standalone_sender_fn`

(ดูเต็ม ๆ ที่ `gateway/platforms/ADDING_A_PLATFORM.md:1-375`)

### 8.2 ACP Adapter (`acp_adapter/`) — สำหรับ Zed editor

**Agent Client Protocol** = JSON-RPC 2.0 บน stdio ที่ Zed / editor พูดกับ agent

**Modules:**

| Module | บทบาท |
|---|---|
| `entry.py` | CLI entry, logging stderr (stdout เป็น JSON-RPC), probe-method filter |
| `__main__.py` | `python -m acp_adapter` |
| `server.py` | router: `initialize`, `authenticate`, `new_session`, `list_sessions`, `execute`, `send_message`, `set_session_model`, `fork_session` |
| `session.py` | SessionManager + SessionState (AIAgent instance, history, model) |
| `tools.py` | wrap Hermes tools เป็น ACP tool schema |
| `auth.py` | TERMINAL_SETUP_AUTH_METHOD_ID, OAuth, `build_auth_methods()` |
| `permissions.py` | approval gates สำหรับ file/shell tool |
| `events.py` | callbacks → ACP event schema (UserMessage, AgentThought, AgentMessage, ToolStart/Result) |
| `edit_approval.py` | diff UI + wait for user confirm |

**Flow:**
```
Zed → JSON-RPC stdio → acp_adapter.server.execute()
    → SessionState lookup → AIAgent.run_turn(user_message)
    → tool_call (e.g. edit_approval) → make_approval_callback()
    → wait stdio response from Zed (apply/reject)
    → AIAgent continues → stream AgentMessage chunks → Zed
```

**ACP registry (`acp_registry/agent.json`)** ประกาศ metadata ให้ Zed:
```json
{
  "id": "hermes-agent",
  "version": "0.14.0",
  "distribution": {
    "uvx": {"package": "hermes-agent[acp]==0.14.0", "args": ["hermes-acp"]}
  }
}
```

### 8.3 TUI Gateway (`tui_gateway/`) — สำหรับ Ink TUI

แยก process จาก TUI (Ink/React/TS) เพื่อไม่ให้ rendering block agent runtime

| Module | บทบาท |
|---|---|
| `entry.py` | signal handlers (SIGPIPE, SIGTERM, SIGHUP), shutdown grace, sidecar WS setup |
| `server.py` | dispatcher loop: stdin JSON-RPC → method handler → stdout events |
| `transport.py` | StdioTransport, TeeTransport (dual sink) |
| `ws.py` | sidecar WS publisher (dashboard mirror) |
| `render.py` | terminal rendering helpers |
| `event_publisher.py` | WsPublisherTransport |
| `slash_worker.py` | async handler สำหรับ slow ops (compress, resume) บน thread pool |

**Protocol:**
```
TUI process → stdin → tui_gateway server
{"jsonrpc":"2.0","method":"session.send_message","params":{...},"id":1}

server → stdout → TUI
{"method":"event","params":{"type":"agent_message","payload":{"chunk":"..."}}}
```

**Sidecar:** ถ้า `HERMES_TUI_SIDECAR_URL=wss://localhost:8080/sidecar` → `TeeTransport` ส่ง event ไปทั้ง stdout (TUI) **และ** WS (dashboard) — dashboard sidebar mirror

### 8.4 ความสัมพันธ์

```
Messaging Gateway              ACP Adapter                TUI Gateway
(20+ platforms)                (Zed/editors)              (Ink TUI subprocess)

Telegram ─┐                                                     
Discord ──┤                                                     
Slack ────┼─► [AIAgent instance(s)] ◄── stdio JSON-RPC ◄── stdin pipe
Email ────┤      ↑  (one core)              ↑                  ↑
... ──────┘      └─ session per (platform,  └─ session per     └─ session per
                     chat_id, thread_id)       editor window      --tui process

Persistence:    session DB (state.db)      in-memory           in-memory
```

| Aspect | Gateway | ACP | TUI |
|---|---|---|---|
| Protocol | Platform-specific | JSON-RPC stdio | JSON-RPC stdio |
| Auth | env vars (per platform) | TERMINAL_SETUP_AUTH_METHOD_ID | terminal login |
| Session persistence | disk (sessions.json) | in-memory | in-memory |
| Streaming | platform-native (TG edits/etc) | chunked JSON-RPC | chunked + terminal re-render |
| Approval UI | platform messages (TG buttons) | editor diff UI | terminal prompt |

---

## 9. CLI Subsystem (`hermes_cli/`, 80+ modules)

`hermes_cli/main.py` (13,429 lines) เป็น dispatcher กลาง

### 9.1 หมวด modules

**Setup / Auth / Config:**

| Module | LOC | บทบาท |
|---|---|---|
| `auth.py` | 7,474 | pooled credentials, OAuth (Copilot/GitHub/Google/Vercel/DingTalk), credential cache |
| `setup.py` | ~3,900 | interactive wizard: profile, model, tools, skills, cron |
| `config.py` | ~8,200 | YAML config editor: dotpath access, validation |
| `models.py`, `model_switch.py`, `model_normalize.py`, `model_catalog.py` | | model picker |
| `auth_commands.py` | | `/auth add/list/remove/reset` |
| `copilot_auth.py`, `vercel_auth.py`, `dingtalk_auth.py` | | platform-specific OAuth flows |
| `env_loader.py`, `runtime_provider.py`, `dep_ensure.py`, `default_soul.py` | | environment |
| `nous_subscription.py` | | Nous Research subscription |
| `claw.py`, `codex_runtime_plugin_migration.py`, `codex_runtime_switch.py`, `codex_models.py`, `azure_detect.py` | | migrations |
| `security_advisories.py`, `xai_retirement.py` | | deprecation notices |

**Runtime / UI:**

| Module | LOC | บทบาท |
|---|---|---|
| `gateway.py` | ~6,300 | gateway lifecycle (start/stop/install/status), systemd/launchd/Windows service |
| `gateway_windows.py` | ~1,300 | WinService |
| `web_server.py` | 4,583 | FastAPI backend สำหรับ dashboard, `/api/*`, WS gateway relay, PTY proxy |
| `curses_ui.py`, `banner.py`, `cli_output.py`, `colors.py`, `skin_engine.py`, `clipboard.py`, `completion.py`, `pty_bridge.py`, `pt_input_extras.py`, `tips.py` | | TUI primitives |
| `voice.py` | | edge-tts / faster-whisper |
| `browser_connect.py` | | Puppeteer bridge |
| `send_cmd.py` | | forward commands to running gateway (unix socket/Windows pipe) |
| `oneshot.py`, `fallback_cmd.py` | | `-q` mode + fallback chain |
| `status.py`, `logs.py`, `debug.py`, `doctor.py`, `inventory.py`, `dump.py`, `backup.py` | | observability |
| `webhook.py`, `stdio.py`, `callbacks.py`, `relaunch.py`, `uninstall.py`, `timeouts.py`, `_subprocess_compat.py` | | misc |
| `pairing.py`, `platforms.py`, `slack_cli.py`, `kanban*.py` (6 files) | | platform + kanban |
| `profiles.py`, `profile_describer.py`, `profile_distribution.py` | | profile management |
| `bundles.py`, `hooks.py`, `plugins.py`, `plugins_cmd.py`, `tools_config.py`, `skills_config.py`, `skills_hub.py`, `mcp_config.py`, `memory_setup.py`, `migrate.py` | | tool/skill/plugin config |
| `goals.py`, `session_recap.py`, `checkpoints.py`, `cron.py`, `curator.py` | | session & memory |
| `proxy/` subdir | | HTTP/WS proxies สำหรับ embed agent ใน Claude Code/Cursor/VS Code |

### 9.2 Argparse architecture

`_parser.py` (384 lines) — top-level parser + `chat` sub-parser เท่านั้น; sub-commands อื่น register dynamically

`PRE_ARGPARSE_INHERITED_FLAGS` (line 20) — flags ที่ parse ก่อน argparse (เช่น `--profile`) เพื่อ set `HERMES_HOME` ก่อนทุกอย่าง

---

## 10. Frontend — Web Dashboard + Ink TUI

### 10.1 Web (`web/`, React + Vite + TypeScript)

`package.json`: React 19, TypeScript 5.9, Tailwind CSS 4, Vite 7, xterm.js, Three.js, Framer Motion

| Directory | บทบาท |
|---|---|
| `src/components/` | 22 components (Chat, SessionManager, ToolConfig, TerminalEmulator) |
| `src/pages/` | Dashboard, Settings, Sessions, Tools, Logs, Terminal, Skill Manager |
| `src/contexts/` | 8 contexts (AuthContext, SessionContext, ToolContext, GatewayContext, ThemeContext, ...) |
| `src/hooks/` | useGatewayClient, useSession, useWebSocket, useTTS, useClipboard |
| `src/lib/` | API client, WS manager, TokenCounter |
| `src/i18n/` | English, Chinese, ... |
| `src/plugins/` | third-party dashboard integrations |
| `src/themes/` | Tailwind variants |

**API contract** (consume `hermes_cli/web_server.py`):
- `GET /api/status` — agent + gateway health
- `GET/POST /api/sessions` — list/create/rename
- `GET /api/messages/{session_id}` — history + WS stream
- `GET /api/tools`, `GET/PATCH /api/config`
- WS `/api/pty?channel=...` — PTY stream (TUI sidecar relay)

**Build**: `npm run build` → `web_dist/` ลงทะเบียนเป็น package data ใน `pyproject.toml:218` → FastAPI serve เป็น static files

### 10.2 Ink TUI (`ui-tui/`)

`package.json`: Ink 6.8, React 19, TypeScript, nanostores, Babel + esbuild

| Directory | บทบาท |
|---|---|
| `src/app/` | App.tsx wrapper, orchestration |
| `src/components/` | 24 Ink components (Chat, Header, Footer, Sidebar, StatusBar, TaskMonitor, TerminalOutput, Notification) |
| `src/hooks/` | usePtyStream, useGatewayEvents, useWindowSize, useFocus |
| `src/lib/` | rendering, ANSI parsing, line wrapping |
| `src/domain/` | 10 domain models (Message, Session, Task, Tool, Channel) |
| `src/types/` | TypeScript interfaces (gatewayTypes.ts: 14KB) |
| `src/protocol/` | TUI ↔ gateway protocol handlers |
| `packages/hermes-ink/` | private workspace package — custom Ink components |
| `src/entry.tsx` | TUI entry — launched by `tui_gateway/entry.py` |

### 10.3 Relationship (Web ↔ TUI ↔ Agent)

```
React Dashboard (web/)        ←─ REST/WS ─►  web_server.py (FastAPI)
                                              │
                                              ├─ direct AIAgent calls
                                              └─ optional sidecar WS ◄┐
                                                                       │
Ink TUI (ui-tui/)             ←─ stdin/stdout JSON-RPC ─►  tui_gateway/server.py
                                                                       │
                                                                       └─ TeeTransport
                                                                          (events ไปยัง
                                                                           dashboard ด้วย)
```

---

## 11. MCP Server (`mcp_serve.py`, 897 lines)

เปิด Hermes session ให้ MCP client (Claude Code, Cursor, Codex)

### 11.1 Tools (10 ตัว)

| Tool | บทบาท |
|---|---|
| `conversations_list` | list sessions |
| `conversation_get` | single session metadata |
| `channels_list` | available platforms |
| `messages_read` | paginated history |
| `attachments_fetch` | by ID |
| `events_poll` | long-poll non-blocking |
| `events_wait` | blocking wait |
| `messages_send` | broadcast |
| `permissions_list_open` | pending approvals |
| `permissions_respond` | approve/deny |

### 11.2 รายละเอียด

- `_load_sessions_index()` (line 81) — อ่าน `sessions.json` ตรง ๆ (ไม่ import full SessionStore)
- `_load_channel_directory()` (line 98) — cached platform routing
- `_extract_message_content()` (line 137) — multi-part (text + attachments)
- FastMCP decorator: `@mcp.tool()`
- MCP SDK lazy import (line 50-55) — tools ไม่พร้อมถ้าไม่ได้ติดตั้ง `[mcp]` extra

---

## 12. Research / Training Tooling

### 12.1 `batch_runner.py` (1,321 lines)

Parallel trajectory generation สำหรับ dataset

- `_extract_tool_stats()` (line 125) — parse tool calls
- `_normalize_tool_stats()` (line 71) — ensure all tools present (HuggingFace schema consistency)
- `_work_item()` — worker pool
- `_save_trajectory()` — Hermes format (`from`/`value` pairs)
- Resume via `--resume` flag
- Multiprocessing.Pool + Lock for stdout sync

```bash
python batch_runner.py \
  --dataset_file=data.jsonl \
  --batch_size=10 \
  --run_name=my_run \
  --distribution=image_gen
```

Output JSONL: `{prompt, response, trajectory, tool_stats, tokens_used, duration}`

### 12.2 `trajectory_compressor.py` (1,508 lines)

Post-process — compress middle turns within token budget

1. Protect first system/human/gpt/tool turns
2. Protect last N turns
3. Summarize middle via auxiliary LLM
4. Replace middle ด้วย single human summary
5. Keep tool calls intact

Classes: `CompressionConfig` (line 83), `CompressionMetrics`, `Summarizer` (OpenRouter API, rate-limited)

```bash
python trajectory_compressor.py \
  --input=data/my_run \
  --target_max_tokens=16000 \
  --sample_percent=10
```

Output: `_compressed.jsonl`

### 12.3 `mini_swe_runner.py` (735 lines)

SWE-bench runner ใน Hermes environments (local/Docker/Modal)

- `LocalEnvironment`, `DockerEnvironment`, `ModalEnvironment`
- Tool: `terminal` (bash) ตาม Hermes schema (line 72-114)

```bash
python mini_swe_runner.py --task "..." --env docker --image python:3.11-slim
```

---

## 13. State & Persistence

### 13.1 `hermes_state.py` — SessionDB (3,273 lines)

- SQLite ที่ `~/.hermes/state.db`
- ตาราง: session metadata, message history
- **FTS5** full-text search สำหรับ cross-session recall
- `parent_session_id` chains (compression handoffs)
- **WAL mode with NFS fallback** (`apply_wal_with_fallback()`, line 128-162)
- Per-db_label deduplication ของ NFS warning

### 13.2 Trajectory persistence

- `agent/trajectory.py` — JSONL writer/reader
- Saved after each turn ถ้า `save_trajectories=True`
- Format: messages + tool_stats + usage + cost
- Compatible กับ `trajectory_compressor.py` และ `batch_runner.py`

### 13.3 Filesystem checkpoints

- `tools/checkpoint_manager.py` + `agent._checkpoint_mgr`
- File-mutating tools (write_file, patch) checkpoint **ก่อน** execute
- Destructive terminal commands ก็เช่นกัน
- รอลบ ก็มี rollback path

---

## 14. Infrastructure & Packaging

### 14.1 `pyproject.toml`

**Entry points:**
```toml
hermes = "hermes_cli.main:main"
hermes-agent = "run_agent:main"
hermes-acp = "acp_adapter.entry:main"
```

**Core deps** (exact-pinned): openai 2.24.0, httpx, rich, tenacity, pyyaml, prompt_toolkit 3.0.52, croniter 6.0.0, psutil 7.2.2

**Extras:**

| Extra | สำหรับ |
|---|---|
| `[anthropic]` | Anthropic SDK |
| `[bedrock]`, `[azure-identity]` | AWS / Azure |
| `[slack]`, `[matrix]`, `[dingtalk]`, `[feishu]`, `[messaging]` | platforms |
| `[voice]` | faster-whisper, sounddevice |
| `[mcp]` | MCP 1.26.0 |
| `[web]` | FastAPI, uvicorn |
| `[acp]` | ACP |
| `[all]` | core + dev + cron + cli + pty + mcp + acp + web + skills |
| `[termux]` | Android baseline (subset ของ `[all]`) |

**Lazy-install policy** (`tools/lazy_deps.py`):
Provider-specific packages ไม่อยู่ใน `dependencies` หลัก — โหลดตอนใช้ครั้งแรก ลด install footprint + ลด blast radius จาก supply-chain attack

### 14.2 Docker / Nix

- `Dockerfile` — multi-stage, Python 3.11, uv pip, expose 9119 (dashboard), 8000 (gateway), 8888 (TUI WS)
- `docker-compose.yml` — gateway + dashboard services, mount `HERMES_HOME`
- `flake.nix` + `nix/` (13 files) — dev shell, package, nixOS module

### 14.3 Scripts (`scripts/`)

| Script | บทบาท |
|---|---|
| `install.sh` (~82KB) | POSIX installer, venv, entry points, systemd |
| `install.ps1` | Windows installer (uv, Python 3.11, Node, ripgrep, ffmpeg, MinGit) |
| `hermes-gateway` | wrapper binary |
| `release.py` | versioning, changelog, PyPI upload, Docker push |
| `profile-tui.py` | TUI perf profiler |
| `setup-hermes.sh` | one-shot setup alternative |

### 14.4 GitHub Workflows (`.github/`)

| Workflow | บทบาท |
|---|---|
| `tests.yml` | pytest + `-n auto`, 60s timeout |
| `lint.yml` | Ruff + type check |
| `docker-publish.yml` | Docker Hub / GitHub Packages |
| `upload_to_pypi.yml` | PyPI on version bump |
| `nix-lockfile-fix.yml`, `nix.yml`, `uv-lockfile-check.yml` | lockfile guards |
| `supply-chain-audit.yml` | OSV scanner |
| `contributor-check.yml` | git history hygiene |
| `skills-index.yml` | auto-build skills registry |

### 14.5 Tests (`tests/`)

~1,000 test files, organized โดย subsystem:

| Subdir | Coverage |
|---|---|
| `tests/agent/` | conversation loop, model routing, compression |
| `tests/tools/` | tool execution, schemas, sandboxing |
| `tests/hermes_cli/` | parsing, dispatch, config |
| `tests/gateway/` | platform dispatch, session routing |
| `tests/plugins/` | skill loading, dashboard |
| `tests/tui_gateway/` | TUI protocol, WS |
| `tests/e2e/` | end-to-end (Telegram, Matrix with Docker) |
| `tests/fakes/` | mock providers, stubs |

**Strategy:** parallel (`-n auto`), 60s timeout/test (catches hangs), autouse fixtures stub concurrent detection, `integration` marker for API-key tests (excluded by default)

---

## 15. End-to-End Data Flow Narrative

ดู journey ของข้อความเดียวเต็ม ๆ — ผู้ใช้พิมพ์ `"แก้บั๊กใน test"` ใน CLI:

```
[Entry]
cli.py / hermes_cli/main.py — _repl_loop() จับ input
    │
    ▼
AIAgent.run_conversation(user_message="แก้บั๊กใน test")
    │
[Init & Context Building]   ←─ conversation_loop.py:187-600
    ├─ restore_or_build_system_prompt()
    │   ├─ check session DB cache (prefix-cache reuse, Anthropic)
    │   ├─ ถ้าไม่มี → prompt_builder.DEFAULT_AGENT_IDENTITY (line 134)
    │   │           + PLATFORM_HINTS + memory context
    │   │           + SOUL.md + skills index + guidance blocks
    │   └─ persist กลับเข้า session DB
    ├─ build messages list (system + history + memory + user + context refs)
    └─ estimate_tokens_rough()
    │
[Compression Check]   ←─ conversation_loop.py:660-700
    ├─ context_compressor.should_compress()  (75% threshold)
    │   ├─ True → compress() เรียก auxiliary model สรุป middle turns
    │   └─ False → ไป step ถัดไป
    │
[Transport]   ←─ conversation_loop.py:700-750
    ├─ transport.convert_messages(messages)
    ├─ transport.convert_tools(tools)
    ├─ apply_anthropic_cache_control() ถ้าใช้ Anthropic
    └─ transport.build_kwargs() → API call dict
    │
[LLM Call + Retry]   ←─ conversation_loop.py:800-1200
    ├─ iteration_budget.decrement()
    ├─ client.create(**kwargs)
    ├─ on success: normalize_response() (tool_calls, thinking, usage, finish_reason)
    └─ on error: classify_api_error()
        ├─ rate_limit → backoff + rotate credential → retry
        ├─ context_overflow → compress → retry
        ├─ model_not_found → tier-down → retry
        ├─ auth → refresh OAuth → retry
        └─ exhausted → abort
    │
    └─ context_compressor.update_from_response(usage) ←─ ติดตาม budget
    │
[Tool Execution]   ←─ conversation_loop.py:1300-2500 + tool_executor.py
    └─ ถ้ามี tool_calls:
        ├─ _should_parallelize_tool_batch() ตัดสินใจ concurrent vs sequential
        ├─ execute_tool_calls_*():
        │   ├─ pre-flight: interrupt / guardrails / checkpoint
        │   ├─ registry.dispatch(name, args, task_id)
        │   ├─ handler() (e.g. terminal_tool.run, vision_tools.extract_text)
        │   └─ collect result JSON
        ├─ append tool results เป็น messages
        └─ loop กลับ [LLM Call] จนกว่า finish_reason != "tool_calls"
    │
[Post-Turn Hooks]   ←─ conversation_loop.py:2500-2800
    ├─ trajectory.save_trajectory() (ถ้า enabled)
    ├─ persist system_prompt → session DB (next-turn cache reuse)
    ├─ memory_manager.queue_prefetch_all(user_message)
    ├─ curator.maybe_run_curator() (background, idle>2h)
    └─ build response dict
    │
    ▼
return {final_response, messages, tool_calls, usage, cost_usd}
    │
    ▼
cli.py:_render_response() → markdown / syntax highlight → terminal
    │
    ▼
_repl_loop() กลับมารอ input ต่อไป
```

---

## 16. Extension Cheatsheet — เพิ่มอะไรยังไง

| ต้องการเพิ่ม | สร้างที่ | ต้องมี |
|---|---|---|
| **Tool** | `tools/your_tool.py` (built-in) **หรือ** `~/.hermes/plugins/<name>/__init__.py` | `registry.register(name, toolset, schema, handler)` ระดับ module |
| **Skill** | `skills/<cat>/<name>/SKILL.md` (bundled) **หรือ** `~/.hermes/skills/<cat>/<name>/SKILL.md` | YAML frontmatter + prose sections ตาม template |
| **Plugin** | `plugins/<name>/` (bundled) / `~/.hermes/plugins/<name>/` (user) / pip entry point group `hermes_agent.plugins` | `plugin.yaml` + `__init__.py` with `register(ctx)` |
| **Memory provider** | `plugins/memory/<name>/` | subclass `MemoryProvider`, register ใน `discover_plugin_memory_providers()` |
| **Model provider** | `plugins/model-providers/<name>/__init__.py` | `ProviderProfile(...)` + `register_provider(profile)` |
| **Messaging platform** | `~/.hermes/plugins/platforms/<name>/adapter.py` | subclass `BasePlatformAdapter`, register ผ่าน `ctx.register_platform(PlatformEntry(...))` |
| **Context engine** | `plugins/context_engine/<name>/` | subclass `ContextEngine` (จาก `agent/context_engine.py`), hook `load_context()` |
| **Image-gen backend** | `plugins/image_gen/<name>/` | implement contract ใน `agent/image_gen_provider.py` |
| **CLI sub-command** | inside plugin `register(ctx)` | `ctx.register_cli_command(name, func)` |
| **Dashboard plugin** | `web/src/plugins/<name>/` + plugin manifest | React component + manifest |

---

## 17. ข้อควรระวัง (Non-obvious Gotchas) รวม

จากการสำรวจทั้ง 4 layers:

### Core runtime
- **OpenAI lazy proxy** (`run_agent.py:56-83`) — อย่า import ของจาก openai ก่อน `process_bootstrap`
- **Iteration budget shared** ระหว่าง parent + subagents — `delegate_tool` ใช้ budget เดียวกัน
- **System prompt rebuild แพง** — cached ใน `_cached_system_prompt` + session DB; ถ้า column ว่าง → cache miss ทุก turn
- **Compression mutates messages in-place** — อย่าเก็บ reference ข้าม compress() call
- **Anthropic cache tokens แยกจาก prompt_tokens** — ต้องบวกเอง (`conversation_loop.py:1600-1620`)
- **Thinking blocks ถูก scrub ก่อนแสดงผล** (`think_scrubber.StreamingThinkScrubber`) — log file มี แต่ user ไม่เห็น

### Gateway
- **Thread/topic identity แตกต่างทุก platform** — `SessionSource.thread_id` normalize เป็น string
- **User ID หลายตัว** (Signal phone+UUID, WeChat) — `user_id` + `user_id_alt`
- **Rate limits ต่างกัน** ทุก platform — adapter จัดเอง; streaming respect threshold
- **Media URL หมดอายุ** (WhatsApp 24h) — cache to disk or re-upload
- **Echo filter** — `sender_id == bot_id` ป้องกัน reply loop
- **PII redact** — phone numbers, IDs ผ่าน `agent/redact.py` ก่อน log

### Tools
- **Concurrent vs sequential** — `_should_parallelize_tool_batch()` เช็ค destructive patterns, path scoping; ถ้าไม่ปลอดภัย → sequential
- **Guardrails block ก่อน execute** — return synthetic error JSON แทน
- **Checkpoint ก่อน file-mutating tool** — มี rollback path

### Skills/Plugins/Providers
- **Skills static per session** — ต้อง `/reset` หรือ new instance ถึง hot-reload
- **Curator fork ใน background** — ไม่ block main turn
- **User plugin override bundled** — last-writer-wins บน name
- **Provider hostname-based routing** — ใช้ URL ตรวจหา provider; ระวัง custom base_url ที่ไม่ขึ้นกับ pattern

### TUI Gateway
- **SIGPIPE handler** บันทึก stack trace ไป `~/.hermes/logs/tui_gateway_crash.log`
- **Shutdown grace** default 1s — encrypted disk อาจต้องเพิ่ม `HERMES_TUI_GATEWAY_SHUTDOWN_GRACE_S=5`
- **Long handlers** บน thread pool (4 workers) — เก็บ stdin responsive

### Persistence
- **WAL mode + NFS fallback** — log warning 1 ครั้งต่อ db_label (`apply_wal_with_fallback()`)

---

## 18. แผนที่ไฟล์สำคัญ (Quick Reference)

ถ้าจะเริ่มแก้อะไร อ่านไฟล์นี้ก่อน:

| ต้องการทำ... | อ่าน |
|---|---|
| เพิ่ม tool | `tools/registry.py`, `tools/__init__.py`, ตัวอย่าง `tools/web_tools.py` |
| เพิ่ม skill | `tools/skills_hub.py:69-2360`, ตัวอย่างใน `skills/github/` |
| เพิ่ม plugin | `hermes_cli/plugins.py:34-400`, `plugins/__init__.py`, ตัวอย่าง `plugins/memory/honcho/` |
| เพิ่ม provider | `providers/base.py:38-184`, ตัวอย่าง `plugins/model-providers/anthropic/__init__.py` |
| เพิ่ม platform | `gateway/platforms/ADDING_A_PLATFORM.md`, `gateway/platforms/base.py`, ตัวอย่าง `gateway/platforms/telegram.py` |
| ปรับ conversation loop | `agent/conversation_loop.py` (อย่ายุ่ง forwarder ใน run_agent.py) |
| ปรับ context compression | `agent/context_compressor.py`, `agent/context_engine.py` |
| ปรับ system prompt | `agent/prompt_builder.py:134` (DEFAULT_AGENT_IDENTITY) |
| ปรับ tool dispatch | `agent/tool_executor.py:65`, `agent/tool_dispatch_helpers.py` |
| ปรับ error handling | `agent/error_classifier.py`, `agent/retry_utils.py` |
| ปรับ session storage | `hermes_state.py:128-162` (WAL/NFS), schema ใน same file |
| เพิ่ม CLI command | `hermes_cli/main.py` (dispatch), `hermes_cli/_parser.py` (top parser) |
| ปรับ web dashboard | `hermes_cli/web_server.py` (backend), `web/src/` (frontend) |
| ปรับ TUI | `ui-tui/src/` (UI), `tui_gateway/server.py` (Python bridge) |
| ปรับ MCP exposure | `mcp_serve.py` |
| Trajectory format | `agent/trajectory.py`, `batch_runner.py`, `trajectory_compressor.py` |

---

## 19. สรุปสุดท้าย

Hermes Agent ถูกออกแบบให้ "**plug-and-play ทุกชั้น แต่ core conversation loop เสถียร**":

- **Provider** swap ได้ → เปลี่ยน model ไม่ต้องแก้โค้ด
- **Tool / Skill / Plugin** ลงทะเบียนตัวเอง → ไม่มี master list ให้แก้
- **Three fronts** (gateway/ACP/TUI) → user คุยจากไหนก็ได้ session เดียวกัน
- **Self-improvement loop** (curator + memory) → ทำงาน background ไม่ block user turn
- **Failover + compression** → resilient ต่อ rate limit, context overflow, model deprecation

ลำดับความสำคัญในการอ่านโค้ด:

1. `run_agent.py` (AIAgent class) → `agent/conversation_loop.py` (main loop)
2. `agent/transports/base.py` (provider abstraction)
3. `tools/registry.py` + `model_tools.py` (tool layer)
4. `hermes_cli/main.py` (CLI dispatcher)
5. `gateway/run.py` (เริ่มแก้ messaging)
6. `agent/context_compressor.py` (เริ่มแก้ context engineering)
7. `tools/skills_hub.py` (skill mechanism)
8. `providers/base.py` + `plugins/model-providers/*/` (เริ่มแก้ provider)

---

*เอกสารนี้สร้างจากการ explore repo อัตโนมัติ — มี file:line citations ตลอด ถ้าเจอจุดที่คลาดเคลื่อนกับโค้ดจริง โปรดอัปเดต*

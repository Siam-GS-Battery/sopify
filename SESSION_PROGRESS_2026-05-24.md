# Sopify ENCM — Session Progress + Roadmap (2026-05-24)

> ระยะเวลา: ~1 วัน
> สถานะ: **Week 1 + Week 2 (Foundation + Control Plane core) เสร็จ** ใช้งานจริงได้
> Tests: **133/133 pass** ใน 0.94s
> ดู spec ได้ที่ [SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md](../SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md)

---

## 0. Bootstrap for next session (READ FIRST)

ถ้าเปิด session ใหม่ + เริ่มทำงานต่อ — อ่านไฟล์ตามลำดับนี้:

### 0.1 Required reading (10 นาที)

1. **`../SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md`** v1.0 (parent dir) — **spec ทางการ**
   - §1 Architecture (control plane on top of sbx)
   - §3 Implementation plan (Week 1-4)
   - **§7 Anti-patterns — ห้ามทำอะไร** (สำคัญสุด — เช่น ห้าม MITM proxy, ห้าม regex CLI stdout, ห้าม bind 0.0.0.0, ห้ามเพิ่ม DB)
2. **`./SESSION_PROGRESS_2026-05-24.md`** (ไฟล์นี้) — สิ่งที่เสร็จ + plan ต่อไป
3. **`./archive/2026-05-24-encm-mitm-attempt/README.md`** — บทเรียนจาก attempt แรก (อย่าทำซ้ำ)

### 0.2 Sanity check commands

ก่อนแก้อะไร verify ระบบยังทำงาน:

```bash
cd /Users/burased.b/ai_engineer/gs/project-based/sopify/sopify-harness

# 1. Tests ต้องผ่านทั้งหมด
.venv/bin/python -m pytest plugins/sopify_encm/tests/ sopify_daemon/tests/ -q
# expected: 133 passed in <1s

# 2. CLI ทำงาน
sopify status 2>&1 | head -3
# expected: "daemon not reachable" (ถ้ายังไม่ start) หรือ JSON

# 3. Daemon boot + lifecycle
sopify start  # terminal 1
sopify status # terminal 2 — expected: reachable=True, drift=0
sopify stop   # expected: "stopped cleanly"

# 4. sbx ใช้งานได้
sbx ls
sbx policy ls | head -3
```

ถ้าสามอันแรกเพี้ยน — debug ก่อน อย่าเริ่มงานใหม่

### 0.3 Critical "do not do this" reminders

- ❌ **อย่าสร้าง custom MITM proxy** — ลองแล้ว ตาย (ดู `archive/`)
- ❌ **อย่า bind 0.0.0.0** — 127.0.0.1 only เสมอ
- ❌ **อย่า parse `sbx` CLI stdout via regex** — ใช้ HTTP API หรือ `--json` output เท่านั้น
- ❌ **อย่าเพิ่ม DB dependency** — YAML files + JSONL คือ persistence layer
- ❌ **อย่าให้ CLI อ่าน YAML ตรง ๆ** — CLI = thin HTTP client เสมอ
- ❌ **อย่าให้ daemon รัน UI process แยก** — UI = static assets ใต้ FastAPI เดียวกัน
- ❌ **อย่า bypass `RuleFileWriter`** — atomic write + validate ผ่านมันเสมอ

### 0.4 Open Boss decisions (ค้างจาก session นี้)

ถามก่อนเริ่ม Phase 1:

1. **UI placement**: React หน้า `/network` ใน existing dashboard หรือ standalone?
2. **Priority**: เริ่ม UI ก่อน (end-user value) หรือ Custom Rule Engine ก่อน (differentiator)?
3. **Browser auto-open**: default yes + `--no-browser` flag — โอเค?
4. **Stale sandbox** `sopify-c98a10c5f5` ใน sbx ลบเลยไหม?

---

## 1. สิ่งที่ทำสำเร็จ

### 1.1 สถาปัตยกรรมที่ใช้จริง (หลัง pivot จาก MITM proxy)

```
~/.sopify/encm/rules/*.yaml  (desired state)
        │
        ▼
sopify_daemon (FastAPI 127.0.0.1:7777, token auth)
   ├─ /api/v1/rules (CRUD)
   ├─ /api/v1/audit (query)
   ├─ /api/v1/reconcile (force tick)
   ├─ /api/v1/drift (untracked sbx rules)
   ├─ /api/v1/status (health)
   ├─ Reconciler task — 30s tick: diff YAML vs sbx
   └─ Audit ingester task — poll `sbx policy log --json` + diff
        │
        ▼ (writes via CLI subcommand, reads via Unix socket HTTP)
sandboxd (Docker Sandboxes daemon)  → enforces actual network policy
```

### 1.2 ภาคแรก: MITM proxy attempt (archived)

**สิ่งที่สร้างแล้ว archive**:
- `mitmproxy` addon + CA generator + Docker container (`docker/sopify-encm/`)
- Sandbox CA trust store installer
- HTTPS interception flow

**สาเหตุที่ทิ้ง**:
- sbx daemon มี forced MITM proxy ของ Docker ที่ดักทุก outbound port
- ลอง disable แล้ว (Docker AI setting, MCP Toolkit feature flags) — ปิดไม่ได้
- Layer ENCM ทับ sbx proxy = ปวดหัวเรื่อง double-TLS + ไม่ได้รับ payload จริง

**ของเก่าอยู่ที่**: `archive/2026-05-24-encm-mitm-attempt/` (ลบ 2026-07-23)

### 1.3 ภาคใหม่: Control Plane ที่ใช้งานได้จริง

| ส่วน | LoC | สถานะ |
|---|---|---|
| Pydantic schema (K8s-style `NetworkRule` YAML) | 203 | ✅ พร้อม |
| RuleFileWriter (atomic write, scope-aware paths) | 155 | ✅ |
| Config + token auth (Jupyter style, 0600 mode) | 168 | ✅ |
| ISandboxBackend + SbxBackend (HTTP read + CLI write) | 350 | ✅ |
| Reconciler (30s tick + drift detection + 3-layer filter) | 280 | ✅ |
| Audit ingester (CLI snapshot diff) | 151 | ✅ |
| FastAPI app + 5 routes | 350 | ✅ |
| CLI thin client + PID lifecycle | 460 | ✅ |
| OpenAPI mini-spec (hand-written) | 220 | ✅ |
| Tests (schema/writer/config/routes/reconciler/sbx_backend) | 1,000+ | ✅ 133/133 pass |

### 1.4 ปัญหาที่เจอ + แก้ระหว่างทาง

| Issue | Root cause | Fix |
|---|---|---|
| MITM proxy approach ติด Docker MCP gateway | sbx forced proxy intercepts all ports | Pivot to Control Plane |
| Port 7777 ค้างหลัง Ctrl+C | uvicorn ไม่ตายเสมอ | `sopify stop` + PID file + lsof verification |
| `POST /policy/rules` 400 | sandboxd HTTP write schema unknown | Switch to `sbx policy allow/deny network` CLI for writes |
| `/policy/log` 404 | ไม่มี HTTP audit endpoint | `sbx policy log --json` snapshot + diff |
| `default-allow-all` drift | sbx ใช้ `origin=local` ไม่ใช่ `default` | Filter by name+resources fingerprint |
| `kit:*` rules drift | HTTP API ส่ง `origin="scoped"` + `sandbox_id` separate | Filter by name prefix + sandbox_id populated |
| typo `sopify rule` (singular) spawn sandbox | shim fall-through ไป Hermes | Whitelist + typo suggestion map |

### 1.5 End-to-end verified

```
✅ sopify install        — ENCM container + CA archived ไม่ใช้แล้ว, install ปกติ
✅ sopify start          — daemon boots, PID file written
✅ sopify start (dup)    — refuses with friendly hint
✅ sopify status         — sandboxd reachable, reconciler ticked, audit events 614+
✅ sopify rules add      — YAML created, reconciler picks up
✅ sopify rules list     — JSON output of YAML files
✅ sopify reconcile      — applied: 1, drift_count: 0
✅ sbx policy ls         — rule landed in sbx with UUID
✅ sopify rules remove   — cleaned from disk + sbx
✅ sopify drift          — empty (kit-managed filtered)
✅ sopify audit          — events from sbx policy log
✅ sopify stop           — clean SIGTERM + PID file removed
```

---

## 2. โครงสร้างไฟล์ปัจจุบัน

```
sopify-harness/
├── sopify_daemon/                 ← ใหม่ session นี้ (~3,500 LoC)
│   ├── app.py                     FastAPI + lifespan + PID lifecycle
│   ├── auth.py                    Bearer token (constant-time compare)
│   ├── config.py                  ~/.sopify/config.yaml
│   ├── paths.py                   filesystem layout
│   ├── schema.py                  Pydantic NetworkRule (K8s-style)
│   ├── rule_writer.py             atomic YAML write
│   ├── sbx_backend.py             ISandboxBackend + SbxBackend
│   ├── reconciler.py              30s tick + drift filter
│   ├── audit_ingester.py          poll sbx CLI snapshot
│   ├── cli.py                     thin HTTP client (start/stop/status/...)
│   ├── routes/
│   │   ├── rules.py               /api/v1/rules
│   │   ├── audit.py               /api/v1/audit
│   │   └── system.py              /api/v1/{status,reconcile,drift}
│   └── tests/                     67 tests
│
├── specs/
│   └── sandboxd-openapi-v0.24.yaml  hand-written mini-spec
│
├── plugins/sopify_encm/           ← เก็บ schema v1 + audit writer + matcher
│   ├── schema.py                  (เก่า — legacy network-policy.json v2)
│   ├── audit/                     ← reused by sopify_daemon
│   ├── rules/matcher.py           ← จะใช้ใน Custom Rule Engine (Week 4)
│   └── tests/                     66 tests (surviving from MITM era)
│
└── archive/2026-05-24-encm-mitm-attempt/
    ├── README.md                  context + cleanup date
    ├── plugins/sopify_encm/proxy/ (mitmproxy addon)
    ├── plugins/sopify_encm/ca.py  (CA generator)
    └── docker/sopify-encm/        (proxy container)
```

---

## 3. CLI surface ใช้งานจริง

```bash
# Lifecycle
sopify start                       # daemon ที่ :7777 (foreground)
sopify stop                        # SIGTERM + cleanup PID
sopify status                      # health + counts

# Rules
sopify rules list
sopify rules add <name> --pattern "*.example.com" \
    [--decision allow|deny] [--type domain|cidr|port] \
    [--scope global|sandbox] [--sandbox-id <id>]
sopify rules show <name>
sopify rules remove <name>
sopify rules disable <name>        # flips decision → deny (keeps history)

# Audit + reconcile
sopify audit [--since <ISO>] [--limit N] [--decision allow|deny] [--src <sandbox>]
sopify reconcile                   # force immediate tick
sopify drift                       # list sbx-side rules ENCM doesn't track

# Typo protection
sopify rule list                   # → "did you mean `sopify rules`?" (no Hermes spawn)
```

---

## 4. Plan ต่อไป

### Phase 1 — Week 3 (เสนอ session ถัดไป)

**4.1 Web Dashboard UI** *(เป้าหลัก)*

- หน้า `/network` ใน existing `web/` React app (ที่ build ลง `hermes_cli/web_dist/`)
- ส่วนประกอบ:
  - **Rules table** — list + status badge (sync/error/drift) + filter by scope/decision/labels
  - **Add wizard** — step-by-step สำหรับ Non-Dev (ตามที่ออกแบบใน NETWORK_CONFIGURE.md):
    - Step 1: ประเภท service (Web API / Database / Message broker / Real-time)
    - Step 2: hostname + auto-detect protocol
    - Step 3: preview + save
  - **10 quick-add templates**: SharePoint / Microsoft 365 / PostgreSQL / MySQL / Anthropic / GitHub / PyPI+NPM / MQTT broker / Internal API / Custom
  - **Audit timeline** — live feed (poll `/api/v1/audit` ทุก 5s) + filters
  - **Active connections** — snapshot live
  - **Drift panel** — warnings + "import drift" action
- ต่อ daemon ผ่าน token (cookie or sessionStorage)
- **เวลา**: ~5-7 วัน

**4.2 Audit log retention**

- Daily rotation by UTC date (มีอยู่แล้วใน writer)
- เพิ่ม **90-day rolling window** + compress `.jsonl.gz` → ย้ายไป `audit/archive/`
- เพิ่ม background task ใน daemon lifespan
- ส่ง config ผ่าน `~/.sopify/config.yaml` (`audit_retention_days`)
- **เวลา**: ~1 วัน

**4.3 Browser auto-open**

- `sopify start` auto-open `http://127.0.0.1:7777?token=...` ตามแบบ Jupyter
- มี `--no-browser` flag สำหรับ headless/CI
- **เวลา**: ~half day

### Phase 2 — Week 4

**4.4 Custom Rule Engine** *(value add ที่ sbx ทำไม่ได้)*

- **Time-window rules**: เช่น "block npm install หลัง 18:00 ของวันธรรมดา"
  - Cron-like syntax in YAML `spec.schedule`
  - ENCM emit/remove sbx rule ตามเวลา
- **Rate limits with TTL**: "max 100 req/min ต่อ domain"
  - Reuse `plugins/sopify_encm/rules/rate_limiter.py` (มี sliding window แล้ว)
  - เมื่อเกิน → emit temporary deny rule (TTL: 5 min) → auto-remove
- **OSV reputation lookup**: ก่อน apply allow rule, query OSV → reject ถ้า domain มี report
- **Templates**: bundled rule sets ("Block crypto miners", "Strict npm install", "Allow only Microsoft 365")
- **เวลา**: ~1 สัปดาห์

**4.5 Audit enrichment**

- Lookup `rule_name` ใน reconciler state cache (caching แทน file scan ทุก event)
- Add `created_by`, `labels` จาก source YAML
- Emit OTel `tool_decision` event (Sopify-wide audit pipeline)

### Phase 3 — Week 5

**4.6 Contract test suite ใน CI**

- ทดสอบกับ 3 sbx versions: 0.24, 0.27, 0.29
- ใช้ Docker-in-Docker หรือ testcontainers
- Assert:
  - `GET /policy/rules` returns expected schema
  - `sbx policy allow network -g foo.com` produces rule that GET picks up
  - `sbx policy log --json` returns blocked_hosts/allowed_hosts shape
- รัน **weekly** ใน GitHub Actions เพื่อตรวจ sbx API churn early

**4.7 Multi-source rules**

- รองรับ MDM push (Boss said skip for now แต่ตามแผน v1.0)
- Endpoint `POST /api/v1/sync-mdm?url=...` — pull rules from central server
- Rules marked `managed: true` lock จาก UI edit
- Re-validate ทุก 6 ชั่วโมง

### Phase 4 — Week 6+

**4.8 Polish + docs**

- ถ้า `sopify install-autostart` (systemd/launchd unit registration)
- Update [DOCUMENTATION_ARCHITECTURE.md](DOCUMENTATION_ARCHITECTURE.md) §9 ENCM section
- Update [MANUAL.md](MANUAL.md) ENCM usage + troubleshooting
- **/network help docs in dashboard** — embedded "what does this template do?"

**4.9 Inbound proxy (M4 — defer)**

- ตามแผนเดิม: webhook receiver pattern
- ตอนนี้ยังไม่จำเป็น (use case ใน GS Battery = outbound only)
- Defer ถึง real customer ask

---

## 5. Open issues / risks

| Issue | Likelihood | Impact | Mitigation |
|---|---|---|---|
| sbx API breaking change in minor version | Medium | High | contract tests (Phase 3) + version pin `>=0.24.0,<0.30.0` already in place |
| HTTP API POST shape for `/policy/rules` undocumented | Confirmed | Medium | use CLI subcommand for writes (workaround in place) |
| Audit log size grows unbounded | Medium | Medium | Phase 1.2 retention task |
| Token leak from `config.yaml` | Low | High | mode 0600 enforced; ถ้า leak → ลบ file → ใหม่ generate |
| User edits YAML with syntax error | Medium | Low | reconciler skip + warn (already handled) |
| Docker deprecates sbx (experimental) | Low–Medium 18mo | High | `ISandboxBackend` adapter ready for Kata/Firecracker swap |
| Audit ingester back-pressure if sbx slow | Low | Low | timeout 10s + retry backoff implemented |

---

## 6. Quick reference

**Daemon files:**
- Config + token: `~/.sopify/config.yaml` (0600)
- PID: `~/.sopify/daemon.pid`
- Rules: `~/.sopify/encm/rules/global/*.yaml` + `~/.sopify/encm/rules/sandboxes/<sid>/*.yaml`
- Audit: `~/.sopify/encm/audit/YYYY-MM-DD.jsonl`
- Sync state: `~/.sopify/encm/.state/sync.yaml`

**Daemon endpoints:**
- Public: `GET /health`
- Token-protected: `GET|POST|DELETE /api/v1/rules`, `GET /api/v1/audit`, `GET /api/v1/{status,drift}`, `POST /api/v1/reconcile`

**Where sbx state lives:**
- Socket: `~/Library/Application Support/com.docker.sandboxes/sandboxes/sandboxd/sandboxd.sock`
- View: `sbx policy ls` and `sbx policy log --json`
- Logs: `~/Library/Application Support/com.docker.sandboxes/sandboxes/sandboxd/daemon.log`

**Test commands:**
- `pytest plugins/sopify_encm/tests/ sopify_daemon/tests/` — 133 tests
- Smoke: `sopify start` → another shell → `sopify status && sopify rules list && sopify drift`

---

## 7. คำถามสำหรับ Boss

1. **Web UI design** — เริ่มจาก React หน้า `/network` ใน existing dashboard หรือ standalone web app?
2. **Default ruleset** — Boss บอกว่า "เดี๋ยวมาใส่เองที่หน้า Web" — ตกลงไม่ปนกับ Phase 1 (เพิ่ม templates เท่านั้น) ใช่ไหม?
3. **Phase 1 vs Phase 2 priority** — เริ่ม UI ก่อน หรือ Custom Rule Engine ก่อน?
   - UI = end-user value (Non-Dev / Vibe Coder ใช้งานได้)
   - Custom Engine = differentiator (time-window, rate-limit, OSV — sbx ทำไม่ได้)
4. **Browser auto-open** — เห็นด้วยให้เป็น default + `--no-browser` flag?
5. **PID file path** — ตอนนี้ `~/.sopify/daemon.pid` — ตามแบบ ollama/jupyter หรือ `/var/run/sopify.pid` (ต้องsudo)?
6. **Test sandbox cleanup** — sandbox `sopify-c98a10c5f5` ที่ค้างอยู่ ลบเลยไหม? (ไม่กระทบ Sopify แต่ใช้ disk)

ตอบเสร็จเริ่ม Phase 1 ได้ทันที

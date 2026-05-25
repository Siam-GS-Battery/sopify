# REQ-ENCM-M1 — External Network Control Module (Milestone 1)

> **Status:** Design (approved 2026-05-24)
> **Scope:** ENCM standalone proxy — outbound traffic enforcement
> **Excludes:** Dashboard UI (M3), MDM sync (M5), Inbound (M4+)
>
> เอกสารคู่กัน:
> - [DESIGN_ARCHITECTURE.md](../../DESIGN_ARCHITECTURE.md) REQ-1.2.* — original network egress requirements
> - [DOCUMENTATION_ARCHITECTURE.md](../../DOCUMENTATION_ARCHITECTURE.md) — code-reading guide
> - [MANUAL.md](../../MANUAL.md) — user manual

---

## 1. Overview

**ENCM = External Network Control Module** — layer-7 forward proxy ที่นั่งระหว่าง Sopify sandbox กับ external network เพื่อ:

1. **บังคับ protocol-level whitelist** (HTTP/HTTPS/WS/MQTT + raw TCP สำหรับ DB)
2. **บังคับ per-rule policy** (rate limit, method, topic ACL, query filter)
3. **เก็บ audit log** (allowed + denied) ในรูปแบบ JSON ที่ Admin app ดูดต่อได้
4. **HTTPS interception** (ผ่าน CA cert) เพื่อ view payload ใน dashboard

```
┌── microVM (sandbox-XXX) ──┐         ┌── ENCM container ──┐         ┌── Internet/Internal ──┐
│                            │         │                     │         │                       │
│  Hermes runtime            │ proxy   │  mitmproxy + addons │ direct  │  api.anthropic.com    │
│  HTTP_PROXY=encm:3128      │ ──────→ │  :3128 (HTTP/HTTPS) │ ──────→ │  *.sharepoint.com     │
│  HTTPS_PROXY=encm:3128     │         │  :1883 (MQTT)       │         │  pg.gsbattery.local   │
│  MQTT_BROKER=encm:1883     │         │  :5432 (TCP/PG)     │         │  broker.iot...local   │
│                            │         │  :9001 (WS)         │         │                       │
└────────────────────────────┘         └──┬──────────────────┘         └───────────────────────┘
                                          │
                                          ▼
                                  ~/.sopify/network-policy.json (v2)
                                  ~/.sopify/audit-log/YYYY-MM-DD.jsonl
```

---

## 2. Use cases (in scope)

| # | Use case | Rule type |
|---|---|---|
| UC-1 | อ่าน + ส่ง Outlook ผ่าน Graph API | HTTPS `graph.microsoft.com:443` |
| UC-2 | ดึง Excel จาก SharePoint | HTTPS `*.sharepoint.com:443` + auth |
| UC-3 | Query PostgreSQL บริษัท | TCP `pg.gsbattery.local:5432` + SQL filter |
| UC-4 | Subscribe MQTT IoT data | MQTT broker + topic ACL |
| UC-5 | Anomaly detection: MQTT in → log to PG | combo of UC-3 + UC-4 |
| UC-6 | Slack/LINE alert webhook | HTTPS `hooks.slack.com:443` |
| UC-7 | Anthropic API (existing) | HTTPS `api.anthropic.com:443` |
| UC-8 | npm install / pip install (skills) | HTTPS `pypi.org`, `registry.npmjs.org` |
| UC-9 | Audit ทุก request ดูใน Admin app ภายหลัง | structured JSON log |

**Out of scope (deferred):**
- Inbound webhooks (M4+)
- MDM sync (M5)
- Dashboard UI (M3)
- Multi-tenant ENCM (one ENCM serves multiple sandboxes simultaneously — already works incidentally)

---

## 3. Schema v2

### 3.1 Top-level file: `~/.sopify/network-policy.json`

```json
{
  "schema_version": 2,
  "default_action": "deny",
  "rules": [ /* see §3.2 */ ],
  "audit": {
    "log_dir": "~/.sopify/audit-log",
    "retention_days": 30,
    "log_allowed": false,
    "log_denied": true,
    "log_payload": false,
    "otel_emit": true
  },
  "encm": {
    "http_proxy_port": 3128,
    "mqtt_broker_port": 1883,
    "websocket_port": 9001,
    "tcp_forward_ports": { "postgresql": 5432, "mysql": 3306, "redis": 6379 },
    "ca_cert_path": "~/.sopify/encm-ca/ca.crt"
  }
}
```

### 3.2 Rule shapes (discriminated by `protocol`)

**HTTP/HTTPS rule:**
```json
{
  "id": "rule_01HXX...",
  "protocol": "https",
  "domain": "graph.microsoft.com",
  "ports": [443],
  "methods": ["GET", "POST", "PUT", "DELETE", "PATCH"],
  "paths_allow": ["/v1.0/me/messages*", "/v1.0/me/sendMail"],
  "paths_deny": [],
  "rate_limit_per_min": 100,
  "log_payload": false,
  "description": "Microsoft Graph — read/send Outlook",
  "added_by": "user",
  "added_at": "2026-05-24T10:00:00Z",
  "managed": false,
  "tags": ["m365", "outlook"]
}
```

**WebSocket rule:**
```json
{
  "id": "rule_01HXY...",
  "protocol": "ws",
  "domain": "realtime.gsbattery.co.th",
  "ports": [443, 8443],
  "rate_limit_per_min": null,
  "log_messages": false,
  "added_by": "user"
}
```

**MQTT rule:**
```json
{
  "id": "rule_01HXZ...",
  "protocol": "mqtt",
  "domain": "broker.iot.gsbattery.local",
  "ports": [1883, 8883],
  "topics_allow": ["sensors/+/telemetry", "alerts/#", "machines/+/status"],
  "topics_deny": ["#"],
  "qos_max": 1,
  "log_messages": false,
  "added_by": "it_admin"
}
```

**TCP forward rule (PG/MySQL/Redis):**
```json
{
  "id": "rule_01HXW...",
  "protocol": "tcp",
  "wire_protocol": "postgresql",
  "domain": "pg.gsbattery.local",
  "ports": [5432],
  "query_filter": {
    "non_dev_block": ["DROP", "TRUNCATE", "ALTER", "GRANT", "REVOKE",
                      "DELETE_WITHOUT_WHERE", "UPDATE_WITHOUT_WHERE"],
    "log_queries": false
  },
  "description": "Battery telemetry DB",
  "added_by": "it_admin",
  "managed": true
}
```

### 3.3 Default rules (shipped on first boot)

```json
[
  { "protocol": "https", "domain": "api.anthropic.com", "ports": [443],
    "description": "Default LLM provider", "added_by": "default" },
  { "protocol": "https", "domain": "otel-collector.gsbattery.local", "ports": [443, 4317, 4318],
    "description": "OTel telemetry", "added_by": "default" },
  { "protocol": "https", "domain": "pypi.org", "ports": [443],
    "description": "Python packages", "added_by": "default" },
  { "protocol": "https", "domain": "files.pythonhosted.org", "ports": [443],
    "description": "Python wheels", "added_by": "default" },
  { "protocol": "https", "domain": "registry.npmjs.org", "ports": [443],
    "description": "npm packages", "added_by": "default" }
]
```

### 3.4 Migration v1 → v2

v1:
```json
{ "version": 1, "whitelist": ["api.anthropic.com"], "user_added": ["pg.local"] }
```

v2:
```json
{
  "schema_version": 2,
  "default_action": "deny",
  "rules": [
    { "protocol": "https", "domain": "api.anthropic.com", "ports": [443], "added_by": "default", ... },
    { "protocol": "https", "domain": "pg.local", "ports": [443], "added_by": "user", ... }
  ],
  ...
}
```

Implemented by `plugins/sopify_encm/migration.py::migrate_v1_to_v2()`. Auto-runs on first boot of M1 if v1 detected.

---

## 4. Protocol enforcement details

### 4.1 HTTP/HTTPS proxy

- **Engine:** mitmproxy 11.x (Python addon for rule matching)
- **HTTPS interception:** มี CA cert ที่ install ใน sandbox image — sandbox trust CA → mitmproxy decrypt
- **Matching algorithm:**
  1. Match domain (exact หรือ wildcard `*.example.com`)
  2. Match port (ใน `ports` list)
  3. Match method (ใน `methods` list)
  4. Match path (`paths_allow` regex/glob; `paths_deny` overrides)
  5. Check rate limit (sliding window per-rule)
  6. Allow + log (with optional payload) OR Deny + log
- **Path matching:** glob (`/v1.0/me/*`) or regex (`^/api/v\d+/.+`)
- **Payload viewer:** ถ้า `log_payload: true` → เก็บ request body + response body ใน audit log (มี size cap 64KB ต่อ direction, redact `Authorization` + `Cookie` headers)

### 4.2 WebSocket

- mitmproxy ทำหน้าที่ proxy upgrade handshake แล้ว forward frames
- `log_messages: true` → log frame size + direction (ไม่ตามค่าใน frame โดย default — privacy)
- Domain match same as HTTPS rule

### 4.3 MQTT

- **Engine:** custom Python broker proxy (asyncio + `aiomqtt` upstream connection)
- **Flow:** sandbox connect ที่ ENCM:1883 → ENCM authenticate → forward connection ไป upstream broker
- **Topic ACL:** check ก่อน publish/subscribe — ถ้า topic match `topics_allow` และไม่อยู่ใน `topics_deny` → forward
- **QoS cap:** ลด QoS ลงเป็น `qos_max` ถ้า sandbox ขอสูงกว่า
- **Multi-broker:** หลาย MQTT rule = หลาย broker (key by `domain`)

### 4.4 TCP forward (PG/MySQL/Redis)

- **Engine:** Python asyncio TCP proxy
- **Per-protocol parser:**
  - **PostgreSQL:** parse startup message + simple query (`Q` frame) — extract SQL → check with `query_filter`
  - **MySQL:** parse COM_QUERY packet (0x03) — extract SQL → check
  - **Redis:** parse RESP protocol — check commands (`FLUSHDB`, `FLUSHALL`, `KEYS *` blocked for Non-Dev)
- **Non-Dev query filter:** regex match (case-insensitive):
  - Block: `\bDROP\b`, `\bTRUNCATE\b`, `\bALTER\b`, `\bGRANT\b`, `\bREVOKE\b`
  - Block `DELETE FROM` ถ้าไม่มี `WHERE`
  - Block `UPDATE` ถ้าไม่มี `WHERE`
  - Send error response ตามแบบ wire protocol (e.g. PG ErrorResponse "Sopify policy: DROP not allowed")
- **Role detection:** อ่าน `~/.sopify/profile.json` (ผ่าน mount) — ถ้า `role == "dev"` → skip filter, ถ้า `role == "user"` → enforce

### 4.5 Default-deny + dialog (REQ-1.2.3)

ถ้า rule ไม่ match → log denied + return error ตาม protocol:
- HTTP: 403 Forbidden + body `{ "error": "Sopify policy: domain not whitelisted", "rule_id": null }`
- MQTT: CONNACK with `Not_authorized` (code 5)
- TCP: close connection ทันที + log

ส่วน "Allow once / Always / Deny" dialog → ทำใน M3 (UI) สำหรับ M1 ใช้ default-deny ก่อน

---

## 5. CA cert distribution

### 5.1 Generation

- ตอน `sopify install` หรือ ENCM container บูตครั้งแรก:
  - Generate ed25519 key + self-signed CA cert (ใช้ `cryptography` lib)
  - เก็บที่ `~/.sopify/encm-ca/ca.key` (0600) + `~/.sopify/encm-ca/ca.crt` (0644)
- ใน ENCM container — mount `~/.sopify/encm-ca` เข้า `/etc/encm/ca/` — mitmproxy ใช้ key/cert นี้

### 5.2 Distribution into sandbox

- Sandbox image (Dockerfile):
  ```dockerfile
  # Inject Sopify CA cert into system trust store at runtime
  COPY scripts/install-sopify-ca.sh /usr/local/bin/install-sopify-ca.sh
  RUN chmod +x /usr/local/bin/install-sopify-ca.sh
  ```
- ที่ `entrypoint.sh` ของ sandbox + `inner_cmd` ของ sbx_launcher.py:
  ```bash
  /usr/local/bin/install-sopify-ca.sh  # copies ca.crt to /usr/local/share/ca-certificates/ + update-ca-certificates
  ```
- Mount `~/.sopify/encm-ca/ca.crt` เข้า sandbox เป็น read-only

### 5.3 Trust scope

- CA cert ใช้ภายใน sandbox เท่านั้น (sandbox มี trust store แยกจาก host)
- Host ไม่ trust CA นี้ — ไม่กระทบ user browser
- Audit: cert มี issued_at + valid_until 5 ปี

---

## 6. Audit log format

### 6.1 File layout

```
~/.sopify/audit-log/
├── 2026-05-24.jsonl       ← วันนี้ (append-only)
├── 2026-05-23.jsonl
├── ...
└── 2026-04-24.jsonl       ← 30 วันก่อน (จะถูก rotate ลบทิ้งวันถัดไป)
```

### 6.2 Log entry format (JSON Lines)

```json
{"ts":"2026-05-24T14:23:47.123Z","decision":"allow","protocol":"https","src":"sopify-2a36ea0ad1","dst":"api.anthropic.com:443","rule_id":"rule_01HXX...","method":"POST","path":"/v1/messages","duration_ms":234,"bytes_sent":1024,"bytes_recv":8192,"status":200}
{"ts":"2026-05-24T14:23:46.789Z","decision":"deny","protocol":"http","src":"sopify-2a36ea0ad1","dst":"evil.example.com:80","rule_id":null,"reason":"no matching rule","method":"GET","path":"/leak"}
{"ts":"2026-05-24T14:23:42.012Z","decision":"allow","protocol":"tcp","wire_protocol":"postgresql","src":"sopify-2a36ea0ad1","dst":"pg.gsbattery.local:5432","rule_id":"rule_01HXW...","bytes_sent":127,"bytes_recv":4321,"query_sample":"SELECT * FROM battery_logs WHERE..."}
{"ts":"2026-05-24T14:23:38.555Z","decision":"deny","protocol":"tcp","wire_protocol":"postgresql","src":"sopify-2a36ea0ad1","dst":"pg.gsbattery.local:5432","rule_id":"rule_01HXW...","reason":"policy:non_dev_block:DROP","query_sample":"DROP TABLE battery_logs"}
```

### 6.3 Payload log (optional, opt-in per rule)

ถ้า rule มี `log_payload: true`:
- Request: `{ "ts":..., "decision":"allow", ..., "req_body":"<base64 หรือ utf-8>", "req_headers":{...redacted...} }`
- Response: separate entry `{ "ts":..., "type":"response_body", "rule_id":..., "resp_body":"<...>" }`
- Cap 64KB ต่อ direction
- Redact: `Authorization`, `Cookie`, `Set-Cookie`, `X-API-Key`, `Anthropic-Api-Key`

### 6.4 Retention

- Daily rotation by date stamp
- Background task (in ENCM container) ลบไฟล์เก่ากว่า `retention_days` ทุกชั่วโมง
- Pre-shipment hook: Admin-app pull endpoint จะอ่าน `.jsonl` files ทาง shared volume (M2+)

### 6.5 OTel emit

ถ้า `audit.otel_emit: true` → emit event `tool_decision` ทุก decision (เพิ่ม attribute `encm.rule_id`, `encm.protocol`, `encm.dst`)

---

## 7. Files to create / modify

### 7.1 New files

```
docker/sopify-encm/
├── Dockerfile                          ← mitmproxy + Python + asyncio TCP proxy
├── entrypoint.sh
├── healthcheck.sh
└── scripts/
    └── install-sopify-ca.sh            ← copied into sandbox image at build time

plugins/sopify_encm/
├── __init__.py
├── plugin.yaml
├── README.md
├── schema.py                           ← Pydantic models for v2 policy
├── migration.py                        ← v1 → v2 converter
├── ca.py                               ← CA cert generation
├── proxy/
│   ├── __init__.py
│   ├── http_proxy.py                   ← mitmproxy addon
│   ├── ws_proxy.py
│   ├── mqtt_proxy.py
│   ├── tcp_forward.py                  ← asyncio TCP proxy + parser dispatcher
│   ├── parsers/
│   │   ├── postgresql.py
│   │   ├── mysql.py
│   │   └── redis.py
│   └── query_filter.py                 ← SQL filter for Non-Dev
├── audit/
│   ├── __init__.py
│   ├── writer.py                       ← JSONL writer + rotation
│   └── rotator.py                      ← background retention task
├── rules/
│   ├── __init__.py
│   ├── matcher.py                      ← rule lookup + rate-limit tracker
│   └── store.py                        ← read/write policy file (file watcher for hot-reload)
└── tests/
    ├── test_schema.py
    ├── test_migration.py
    ├── test_http_proxy.py
    ├── test_mqtt_topic_acl.py
    ├── test_postgresql_filter.py
    ├── test_audit_writer.py
    └── test_ca_install.py

docs/sopify/
└── REQ-ENCM-M1.md                      ← นี้
```

### 7.2 Modified files

```
plugins/sopify_sandbox/sbx_launcher.py  ← export HTTP_PROXY/HTTPS_PROXY/MQTT_BROKER + mount CA cert
docker/sopify-sandbox/Dockerfile        ← add install-sopify-ca.sh + ENCM env defaults
docker/sopify-sandbox/entrypoint.sh     ← run install-sopify-ca.sh at boot
plugins/sopify_core/install.py          ← add _ensure_encm_container() step + CA cert gen
plugins/sopify_core/doctor.py           ← add encm-health row
infra/sbx/sopify-kit/spec.yaml          ← change allowedDomains → only encm container itself
DOCUMENTATION_ARCHITECTURE.md           ← new §ENCM section
MANUAL.md                               ← document network rules + add ENCM troubleshooting
```

---

## 8. Test plan

### 8.1 Unit tests

| File | Tests |
|---|---|
| `test_schema.py` | parse valid v2, reject invalid (missing protocol, bad regex) |
| `test_migration.py` | v1 → v2 idempotent + preserves user_added |
| `test_http_proxy.py` | mock mitmproxy flow, assert allow/deny based on rule |
| `test_mqtt_topic_acl.py` | topic regex `sensors/+/telemetry` matches `sensors/cell-01/telemetry` but not `alerts/#` |
| `test_postgresql_filter.py` | parse PG `Q` frame, extract SQL, assert filter blocks `DROP` for non-dev |
| `test_audit_writer.py` | JSONL append + daily rotation + retention purge |
| `test_ca_install.py` | generate CA → assert cert validates expected hostname when used by mitmproxy |

### 8.2 Integration tests (Docker-in-docker หรือ testcontainers)

| Scenario | Expected |
|---|---|
| sandbox curl `api.anthropic.com` ผ่าน ENCM | 200 OK, audit log entry "allow" |
| sandbox curl `evil.com` ผ่าน ENCM | 403 + audit "deny" |
| sandbox `psql -c "DROP TABLE x"` (Non-Dev) | ErrorResponse "Sopify policy" |
| sandbox `psql -c "DROP TABLE x"` (Dev) | passes through (still allowed) |
| sandbox MQTT subscribe `sensors/+/telemetry` | allowed, broker forwards |
| sandbox MQTT subscribe `#` | denied (matches topics_deny) |
| sandbox WS connect to whitelisted host | allowed, frame count logged |
| Audit file > 30 days old | purged on next rotation tick |

### 8.3 Smoke tests

```bash
# Full e2e: install → ENCM up → sandbox uses ENCM → audit log written
sopify install --rebuild
sopify dashboard &
sleep 5
# Inside sandbox: curl https://api.anthropic.com → audit log entry created
grep "api.anthropic.com" ~/.sopify/audit-log/$(date +%F).jsonl
```

---

## 9. Implementation order (sub-milestones)

| Sub-MS | งาน | LoC est. | วัน |
|---|---|---|---|
| M1.1 | Schema v2 + migration | ~300 | 1 |
| M1.2 | CA cert generation + plumb into install + sandbox | ~200 | 1 |
| M1.3 | ENCM Dockerfile + entrypoint + bare mitmproxy | ~150 | 0.5 |
| M1.4 | Rule matcher + rate limiter | ~250 | 1 |
| M1.5 | HTTP/HTTPS addon (allow/deny + rule lookup + path match) | ~300 | 1 |
| M1.6 | WS passthrough | ~100 | 0.5 |
| M1.7 | Audit logger + JSONL + rotation | ~200 | 1 |
| M1.8 | MQTT broker proxy + topic ACL | ~400 | 1.5 |
| M1.9 | TCP forward + PG/MySQL/Redis parsers + query filter | ~500 | 2 |
| M1.10 | Sandbox integration (sbx_launcher env exports + CA install) | ~150 | 0.5 |
| M1.11 | Tests + docs | ~600 | 1.5 |
| | **Total** | **~3150** | **~11 วัน** |

---

## 10. Open questions / decisions deferred to M2-M5

- **M2:** Allow/deny dialog UI (TUI prompt + dashboard modal) — REQ-1.2.3
- **M3:** Dashboard `/network` page (rule editor + audit log feed + active connections)
- **M3:** Role gate UI — Non-Dev → Dev upgrade request flow
- **M4:** Inbound proxy (webhooks)
- **M5:** MDM sync (auto pull rules from central server)
- **M5:** Admin app integration — log shipment

---

## 11. Compatibility / migration plan

- **v1 policy file** detected at boot → auto-migrate to v2, backup v1 to `network-policy.v1.json.bak`
- **Existing sandboxes** ที่ใช้ sbx kit `allowedDomains` — สอดคล้องเพราะ ENCM enforces same DNS-level via rules; kit ลด `allowedDomains` เหลือแค่ ENCM endpoint
- **`SOPIFY_NO_ENCM=1`** env var → skip ENCM (สำหรับ dev debug + fallback ถ้า ENCM ตาย)
- **Existing OTel events** — ENCM emit additional events but original schema unchanged

---

## 12. Acceptance criteria

M1 ถือว่าเสร็จเมื่อ:

1. ✓ ENCM container build + boot ได้, health endpoint ตอบ 200
2. ✓ Sandbox boot → CA cert ถูก install อัตโนมัติ + trust ENCM cert
3. ✓ Sandbox curl HTTPS ปลายทาง whitelist → ผ่าน, audit "allow"
4. ✓ Sandbox curl HTTPS ปลายทางไม่อยู่ใน whitelist → 403, audit "deny"
5. ✓ Sandbox MQTT subscribe whitelisted topic → success, audit "allow"
6. ✓ Sandbox MQTT subscribe denied topic → CONNACK reject, audit "deny"
7. ✓ Sandbox psql DROP (Non-Dev) → ErrorResponse, audit "deny:policy"
8. ✓ Sandbox psql SELECT (Non-Dev) → success, audit "allow"
9. ✓ Sandbox psql DROP (Dev) → success (passes through)
10. ✓ Audit log file ≥ 31 วัน → purged
11. ✓ v1 policy file → auto-migrate to v2
12. ✓ `sopify doctor` → encm-health row OK
13. ✓ Unit tests + integration tests pass (>90% coverage on new code)
14. ✓ `SOPIFY_NO_ENCM=1` bypass ENCM (dev mode)

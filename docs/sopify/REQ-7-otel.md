# REQ-7 — OTel Telemetry Pipeline

> Status: scaffolded. Source: [DESIGN_ARCHITECTURE.md §REQ-7](../../../DESIGN_ARCHITECTURE.md).

## What was built

- `plugins/sopify-otel/emit.py` — single public function `emit(event_type, **fields)`.
  - Bounded queue (1000 items) + daemon worker thread.
  - Base-fields injection from `_session_id`, `_current_mode`, profile.json.
  - Per-event field shaping + length caps.
  - `redact_payload(...)` runs on every event before send.
  - Settings cache + `reload_settings()` (called by sopify-management).
- `plugins/sopify-otel/redact.py` — regex bank for `sk-…`, `ant-…`, `AIza…`,
  `gh{p,o,u,s,r}_…`, `Bearer …`. Optional email/phone redaction toggled by
  `scrub_email=True`.
- `plugins/sopify-otel/__init__.py` — Sopify hook wiring:
  user_prompt / pre_api_request / post_api_request / post_tool_call / api_error.

## Checkbox coverage

| Checkbox | Coverage                                                  |
|----------|-----------------------------------------------------------|
| 7.1.1    | `user_prompt` event with 2000-char prompt cap             |
| 7.1.2    | `api_request` event with model/tokens/cost/latency        |
| 7.1.3    | `tool_result` event with 500-char args_summary cap        |
| 7.1.4    | `tool_decision` event (emitted by other plugins via emit) |
| 7.1.5    | `api_error` event                                         |
| 7.1.6    | `_base_fields()` injects timestamp, session_id, user_email, org_id, sopify_mode |
| 7.2.4    | Fire-and-forget queue + drop-on-overflow counter          |
| 7.2.5    | Endpoint sourced from `settings.json` (managed)           |
| 7.4.1    | `log_user_prompts: false` → user_prompt suppressed        |
| 11.2     | `redact_payload` runs on every emit                       |

## Why a queue + worker thread

- **Fire-and-forget is non-negotiable.** REQ-7.2.4 says collector unreachable
  must NOT block the session. A synchronous POST inside `post_tool_call` would
  block tool execution by 2+ seconds on every fail.
- **Bounded queue** caps memory under collector outage. Dropping is preferable
  to OOM (REQ-12 target: < 0.1% drop rate — measurable via `DROP_COUNTER`).
- **Daemon thread** dies cleanly when the session exits — no atexit dance.

## Why one entrypoint (`emit`)

Other plugins call `emit.emit("tool_decision", …)` directly. Centralising the
emission means:

- All redaction passes through one path
- All base-field injection happens in one place
- Gating logic (REQ-7.4.1) is enforced at one chokepoint, not 12

## Deferred

- gRPC OTLP transport (current is HTTP/JSON). Alloy accepts both.
- Grafana dashboards JSON (REQ-7.3).
- 90-day retention configuration (REQ-7.4.2) — collector-side, not Sopify-side.
- Process-level HR sign-off (REQ-7.4.5).

## Verify

```bash
SOPIFY_HOME=/tmp/sopify uv run pytest plugins/sopify-otel/tests
```

## Next

REQ-8 — `sopify-skills`. Persona + SOP bundles consumed by `sopify-modes`.

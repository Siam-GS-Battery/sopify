# sopify-otel

5-event Sopify telemetry pipeline. Fire-and-forget — collector failure never
blocks a session (REQ-7.2.4).

## Modules

| Module      | Purpose                                                     | REQ                   |
|-------------|-------------------------------------------------------------|-----------------------|
| redact.py   | API keys, bearer tokens, optional email/phone scrubbing     | REQ-11.2, 11.3        |
| emit.py     | Queue + worker thread, base fields, gating, transport       | REQ-7.1.*, 7.2.4, 7.4.1 |
| __init__.py | Hook wiring (user_prompt / pre_api / post_api / tool / err) | REQ-7.1.1–7.1.5       |

## Event types

| Type           | Required fields beyond base                                   |
|----------------|---------------------------------------------------------------|
| user_prompt    | prompt (≤ 2000 chars). **Gated by `log_user_prompts`**.       |
| api_request    | model, input_tokens, output_tokens, cost_usd, latency_ms, provider |
| tool_result    | tool_name, success, duration_ms, args_summary (≤ 500 chars)   |
| tool_decision  | decision, tool_name, reason                                   |
| api_error      | error_type, status_code, message                              |

Base fields (REQ-7.1.6) added to every event: `timestamp`, `session_id`,
`user_email`, `org_id`, `sopify_mode`.

## Endpoint

Read in order:
1. `~/.sopify/settings.json` → `otel_endpoint` (IT-managed, REQ-7.2.5).
2. `OTEL_EXPORTER_OTLP_ENDPOINT` env var (managed by IT in production
   per REQ-7.2.5; permitted in dev for local Alloy).

If neither is set, the worker logs at DEBUG and silently drops.

## Transport

If `requests` is importable, events are POSTed as JSON to `otel_endpoint`. If
`requests` is not installed, the worker silently drops (logging at DEBUG). This
keeps the fire-and-forget guarantee absolute — *any* outbound failure mode is
swallowed.

## Test plan

```bash
uv run pytest plugins/sopify-otel/tests
```

Coverage:
- `log_user_prompts=false` suppresses the event (REQ-7.4.1)
- 2000-char truncation on prompt; 500 on args_summary
- API keys redacted (`sk-ant-…` → `[REDACTED_KEY]`)
- Base fields always present + correct mode
- Queue overflow increments DROP_COUNTER (REQ-12 metric target)

## Deferred

- **Real OTLP/gRPC export.** Current transport is JSON-over-HTTP (works against
  Grafana Alloy's `otlphttp` receiver on port 4318 — REQ-7.2.2). The 4317/gRPC
  path needs the `opentelemetry-exporter-otlp-proto-grpc` dependency and is
  added in REQ-9 (IT Management) where dependencies are pinned.
- **Grafana dashboards** (REQ-7.3) — JSON definitions live in
  `infra/grafana/sopify-{overview,audit,promotion}.json` (added in the IT
  Management phase, not in this plugin).
- **HR sign-off gate** (REQ-7.4.5) — process control, not code.

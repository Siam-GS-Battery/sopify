# Archived: ENCM-as-custom-MITM-proxy attempt

**Archived on:** 2026-05-24
**Scheduled deletion:** 2026-07-23 (60 days)
**Reason:** Architecture pivot — see [SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md](../../../SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md) §1.2

---

## What was here

A working implementation of ENCM as a **custom MITM proxy**:

- **`plugins/sopify_encm/proxy/`** — mitmproxy 12.2.3 addon with HTTP/HTTPS request inspection, rule matching, payload viewer
- **`plugins/sopify_encm/ca.py`** — self-signed CA generator (RSA 4096, 5y validity) for TLS interception
- **`docker/sopify-encm/`** — container packaging (Dockerfile, entrypoint, healthcheck) that ran the proxy on host port 9118 (later, originally 3128)
- **`install-sopify-ca.sh`** — sandbox-side script that built a combined CA bundle (system roots + Sopify CA) at `/tmp/sopify-ca-bundle.pem` and exported `CURL_CA_BUNDLE` / `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` / `NODE_EXTRA_CA_CERTS`

## Why it was abandoned

`sbx` daemon (Docker Sandboxes) injects a forced HTTPS proxy at `gateway.docker.internal:3128` into every microVM. This proxy:
- Intercepts **all** outbound TCP ports (not just 3128) — verified empirically: TCP connect succeeded to arbitrary host:port from sandbox even with ENCM stopped
- Cannot be disabled via CLI/config (we tried `EnableDockerAI=false`, `docker mcp feature ls`, sandbox kit `env:` block — all no-op for the proxy)
- Uses its own CA which our sandbox didn't trust, but more importantly: even if it did, our ENCM at a different port couldn't be reached because MCP gateway swallowed the connection

Conclusion: layering our MITM proxy on top of (or beside) sbx's MITM proxy is architecturally a dead end. Documented in Docker forum threads:
- https://forums.docker.com/t/anthropic-api-proxy-with-docker-sandbox/151445
- https://forums.docker.com/t/please-generalize-docker-sandbox/151421

The new design (Control Plane over sbx) skips the MITM problem entirely by treating sbx's proxy as the data plane and using sandboxd's HTTP API for policy management.

## What stayed in `plugins/sopify_encm/`

Still useful for the new architecture (will be refactored, not deleted):
- `schema.py` — Pydantic models, will be reshaped from JSON-policy to Kubernetes-style YAML `kind: NetworkRule`
- `audit/writer.py` + `audit/rotator.py` — JSONL append + retention. Reusable in the new audit ingester
- `rules/matcher.py` + `rules/rate_limiter.py` — for the Custom Rule Engine (Week 4+, things sbx can't express like time-window + rate limit)
- `rules/store.py` — file-watched hot-reload, will repoint to YAML dir
- `migration.py` — v1→v2 JSON migrator. Likely also gets archived once we lock the new YAML schema, but kept for now to avoid breaking tests that exercise it

## What was un-wired from active codebase

These files in the live codebase had references to the archived code; they were edited to remove those references on 2026-05-24:

- `plugins/sopify_core/install.py` — `_ensure_encm_ca` / `_ensure_encm_image` / `_ensure_encm_running` / `_migrate_encm_policy` functions removed from `run()` flow (functions kept in file as `_DEFER_*` for reference, will be deleted at archive expiry)
- `plugins/sopify_sandbox/sbx_launcher.py` — `HTTPS_PROXY` / `HTTP_PROXY` / `SOPIFY_ENCM_CA_DIR_HOST` env exports removed from `inner_cmd`; ENCM CA dir mount removed from `workspaces`
- `docker/sopify-sandbox/Dockerfile` — `COPY install-sopify-ca.sh` line removed; wrapper script reverted to direct Python exec (no CA bundle build step)

## How to read the archived code

Each top-level entry mirrors its original path under `sopify-harness/`. So `archive/2026-05-24-encm-mitm-attempt/plugins/sopify_encm/proxy/http_proxy.py` is where the file used to live.

## Scheduled deletion: 2026-07-23

If you're reading this after that date and the file still exists, the deletion was forgotten. Safe to `rm -rf` this directory once:
1. The new ENCM Control Plane has shipped successfully and been in use for 30+ days
2. No live code paths reference any module under here (`grep -r "sopify_encm.ca\|sopify_encm.proxy\|install-sopify-ca" plugins/ docker/ sopify` returns nothing)

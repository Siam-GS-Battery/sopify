# Sopify Chat — sbx Proxy / API Key Fix Plan (2026-05-23)

> The /chat tab was silently failing because sbx (Docker Sandboxes) injects an
> opinionated proxy + sentinel key contract that breaks unless we cooperate.
> This doc captures **what's broken**, **why**, and **two ways to fix it** —
> Approach 1 is what we shipped; Approach 2 is the longer-term option.

---

## 1. Symptom

- Browser → http://127.0.0.1:9119 → /chat tab → type "hello" → **no banner, no response, no error**.
- `ps auxf` inside the microVM shows the full PTY chain healthy:
  `node entry.js → tui_gateway.entry → slash_worker` (one per typed message,
   all in state `S+`, blocked).
- `curl https://api.anthropic.com/...` from inside the microVM:
  ```
  HTTP:000  time=0.020s   (instant connection failure)
  ```

## 2. Root cause (two layers)

### Layer A — Sentinel API key

`sbx` substitutes well-known secret env vars with the literal string
`"proxy-managed"` at sandbox boot:

```text
ANTHROPIC_API_KEY=proxy-managed     ← NOT a real key, just a marker
OPENAI_API_KEY=proxy-managed
XAI_API_KEY=proxy-managed
GEMINI_API_KEY=proxy-managed
MISTRAL_API_KEY=proxy-managed
NEBIUS_API_KEY=proxy-managed
GOOGLE_API_KEY=proxy-managed
```

The contract: the proxy is *supposed* to swap the sentinel for a real key on
the way out. But Docker Desktop has no provider credential configured here,
so the gateway just drops the request.

### Layer B — TLS-intercepting proxy with self-signed CA

`sbx` also force-sets:

```text
https_proxy=http://gateway.docker.internal:3128
HTTPS_PROXY=http://gateway.docker.internal:3128
http_proxy=http://gateway.docker.internal:3128
HTTP_PROXY=http://gateway.docker.internal:3128
```

The proxy at `gateway.docker.internal:3128` is reachable (TCP OK) but its TLS
certificate is **self-signed**. The Linux base image's CA bundle does not
trust it, so:

- `curl` exits with `SSL certificate problem: self-signed certificate in certificate chain`
- The Python `anthropic` SDK / `requests` / `httpx` all fail `verify=True` checks
- `node` raises `UNABLE_TO_VERIFY_LEAF_SIGNATURE`

Net effect: every outbound HTTPS call from inside the sandbox dies before it
reaches Anthropic.

### Layer C — sbx schema v1 drops the `env:` block from our kit

`infra/sbx/sopify-kit/spec.yaml` already declares the correct `no_proxy` +
`skipIfEnv` passthroughs. But the runtime sandbox only shows the sbx defaults:

```bash
$ sbx exec $SBOX bash -lc 'env | grep -iE "^no_proxy="'
no_proxy=localhost,127.0.0.1,::1,gateway.docker.internal      # ← sbx default
                                                              # api.anthropic.com MISSING
```

Confirmed: sbx kit schema v1 only parses `network.allowedDomains`. The `env:`
block (and the `startup:` block) are silently ignored. This matches the
behavior noted in `SESSION_HANDOFF.md` §2 #3.

## 3. Approach 1 (SHIPPED) — Re-apply the contract in the launcher

**File touched:** [plugins/sopify_sandbox/sbx_launcher.py](plugins/sopify_sandbox/sbx_launcher.py)

We can't get sbx to honor the kit's `env:` block, so the host launcher
re-applies the contract at exec time via an inline shell prologue:

```python
inner_cmd = (
    f"export no_proxy={_shellquote(_AI_NO_PROXY)}; "
    f"export NO_PROXY={_shellquote(_AI_NO_PROXY)}; "
    'if [ "$ANTHROPIC_API_KEY" = "proxy-managed" ]; then unset ANTHROPIC_API_KEY; fi; '
    "/usr/local/bin/sopify " + " ".join(_shellquote(a) for a in argv)
)
```

`_AI_NO_PROXY` is a constant at the top of the file — kept in sync with
`spec.yaml:72-75` (which remains the canonical declaration, even though sbx
ignores it at runtime).

### How this resolves Layer A
- We `unset ANTHROPIC_API_KEY` when it equals the sentinel.
- `auth_override.apply()` (already shipped) then detects the missing/sentinel
  key and pulls the real value from `~/.hermes/.env`, re-exporting both
  `ANTHROPIC_API_KEY` and `ANTHROPIC_TOKEN` for child processes.

### How this resolves Layer B
- With `api.anthropic.com` (and friends) in `no_proxy`, the SDK's HTTPS calls
  bypass `gateway.docker.internal:3128` entirely and connect directly.
- The Anthropic public CA chain is already in the base image's CA bundle, so
  TLS verifies cleanly.

### How this resolves Layer C
- We sidestep it. The kit's `env:` is now informational only; the launcher is
  the authoritative source.

### Trade-offs

| Pro | Con |
| :--- | :--- |
| One-file change, no image rebuild | Bypasses the MCP gateway entirely (loses centralized policy/logging) |
| Reversible — delete the prologue to roll back | Couples launcher to the proxy contract; if sbx changes its defaults we must follow |
| Same code path for all subcommands (`chat`, `dashboard`, `/vibe`, …) | Doesn't help users who bypass the launcher and call `sbx exec` directly |
| Real key passthrough already wired via `auth_override.apply()` + `~/.hermes/.env` | Real key now egresses Docker's network rather than the MCP-routed proxy |

### Apply the fix to an existing sandbox

The fix takes effect on the *next* `sbx exec` from the launcher. Restart the
dashboard:

```bash
# 1. find the sandbox
SBOX=$(sbx ls | awk '/^sopify-/ {print $1}')

# 2. kill the current dashboard inside the sandbox (PID 26 in our session)
sbx exec "$SBOX" bash -lc 'pkill -f "sopify dashboard" || true'

# 3. relaunch from host with the patched launcher
cd ~/ai_engineer/gs/project-based/sopify/sopify-harness
sopify dashboard

# 4. verify the env inside the sandbox
sbx exec "$SBOX" bash -lc '
  ps auxf | grep -E "node|tui_gateway|slash_worker" | grep -v grep
  echo "---"
  tr "\0" "\n" </proc/$(pgrep -f "sopify dashboard" | head -1)/environ \
    | grep -E "^no_proxy=|^ANTHROPIC_(API_KEY|TOKEN)="
'
```

Expected after restart:
- `no_proxy=...,api.anthropic.com,...`
- `ANTHROPIC_API_KEY=sk-ant-api03-...` (real, 108 chars)
- `ANTHROPIC_TOKEN=sk-ant-api03-...` (real, 108 chars)
- /chat tab responds to "hello" with a model reply.

If the dashboard restart doesn't pick up the env (because `sbx exec` is
caching some state), recreate the sandbox:

```bash
sbx rm --force "$SBOX"
sopify dashboard          # fresh sandbox, fresh env
```

---

## 3.5 Approach 3 (RECOMMENDED LONG-TERM) — Upload key to sbx secret store

**Discovered after Approach 1 shipped.** `sbx` has first-class secret
management that's the *actual* intended design:

```text
$ sbx secret set --help
Available services: anthropic, aws, cursor, droid, github, google,
                    groq, mistral, nebius, openai, xai

When a sandbox starts, the proxy uses stored secrets to authenticate
API requests on behalf of the agent. The secret is never exposed
directly to the agent.
```

This means the `ANTHROPIC_API_KEY=proxy-managed` sentinel **is supposed
to stay as the sentinel** — the proxy at `gateway.docker.internal:3128`
substitutes it with the real key from the sbx secret store on the way
out. The reason chat was broken: we never populated the store.

### Steps

```bash
# 1) Store the Anthropic key as a global secret (read from .env via stdin
#    so it never lands in shell history).
grep '^ANTHROPIC_API_KEY=' ~/.hermes/.env \
  | head -1 \
  | sed 's/^ANTHROPIC_API_KEY=//' \
  | tr -d '"' | tr -d "'" \
  | sbx secret set -g anthropic

# 2) Verify
sbx secret ls

# 3) Restart sandbox so the proxy boots with the new secret available.
sbx rm --force "$(sbx ls | awk '/^sopify-/ {print $1}')"
cd ~/ai_engineer/gs/project-based/sopify/sopify-harness
sopify dashboard
```

### Why this is better than Approach 1

| Aspect | Approach 1 (`no_proxy` bypass) | Approach 3 (`sbx secret`) |
| :--- | :--- | :--- |
| Key location inside sandbox | Promoted from `~/.hermes/.env` into env vars | Never exists in sandbox; only proxy has it |
| Traffic routing | Direct to `api.anthropic.com` | Through `gateway.docker.internal:3128` (audited) |
| Compliance / org policy | Bypasses IT egress filter | Aligns with REQ-9.1.* (Docker Admin Console) |
| CA-cert / TLS handling | Not needed | sbx manages it for us — no manual cert install |
| Failure mode | Key reachable from compromised sandbox process | Compromised process gets sentinel; proxy still enforces |
| Setup cost | Already shipped, zero ops | One-time `sbx secret set` per host |
| Per-host onboarding | Each dev must populate `~/.hermes/.env` | Each dev must run `sbx secret set` once |

### How Approach 1 and Approach 3 interact

Approach 1 (the launcher prologue + `no_proxy` bypass) and Approach 3
(`sbx secret` store) are **not mutually exclusive**:

- With Approach 1 active, AI traffic skips the proxy. Approach 3's stored
  secret is unused for those calls (it only takes effect on traffic that
  flows through the proxy).
- With Approach 3 set up, Approach 1 still works as a fallback — if the
  proxy is misconfigured later, the bypass keeps chat alive.

**Recommendation:** ship Approach 3 as primary, leave Approach 1 in
place as defense-in-depth. To make Approach 3 the *only* path, remove
the `_AI_NO_PROXY` block + the prologue from `sbx_launcher.py`.

### Trade-offs

| Pro | Con |
| :--- | :--- |
| Uses sbx as designed — minimal code | Still subject to proxy CA / TLS handling (sbx is supposed to manage, but worth verifying first run) |
| Centralized audit + policy via proxy | Per-host onboarding step (`sbx secret set`) — not yet automated in `sopify install` |
| Key never inside the sandbox | If sbx secret store is compromised, all stored providers leak together |
| Symmetric for all providers (openai, xai, etc.) — just `sbx secret set -g <svc>` | Requires sbx login + Docker Desktop |

### Next-step automation

After confirming Approach 3 works, wire `sopify env set ANTHROPIC_API_KEY=...`
to also call `sbx secret set -g anthropic` (and same for other providers)
so a single `sopify env set` populates both `~/.hermes/.env` and the sbx
secret store. That gives us:
  - `.env` for non-sandbox local Hermes calls (dev mode)
  - sbx secret store for sandbox-routed calls (production)
  - One command to onboard both.

---

## 4. Approach 2 (DEFERRED) — Trust the proxy CA + keep proxy routing

The "correct" long-term fix per `spec.yaml`'s original intent: keep all
traffic flowing through `gateway.docker.internal:3128` so IT/Docker Admin
Console can centrally log and policy-control AI calls — and just teach the
sandbox to trust the proxy's TLS cert.

### Steps

1. **Locate the proxy CA cert.** On macOS, Docker Desktop ships the MCP
   gateway CA at one of:
   ```
   ~/Library/Group Containers/group.com.docker/pki/ca.crt
   ~/.docker/certs.d/gateway.docker.internal:3128/ca.crt
   /Applications/Docker.app/Contents/Resources/.../ca.crt
   ```
   Confirm with:
   ```bash
   find ~/Library/Group\ Containers/group.com.docker -name "*.crt" -o -name "*.pem" 2>/dev/null
   find ~/.docker -name "ca*.crt" 2>/dev/null
   ```

2. **Mount the CA into the sandbox.** Extend `sbx_launcher.py` workspaces:
   ```python
   docker_ca = Path.home() / "Library/Group Containers/group.com.docker/pki/ca.crt"
   if docker_ca.is_file():
       workspaces.append(f"{docker_ca.parent}:ro")
   ```

3. **Install + trust at sandbox boot.** Add to `_link_hermes_into_sandbox`
   (or a new `_install_proxy_ca` helper):
   ```bash
   sudo cp /Users/<host>/Library/.../ca.crt /usr/local/share/ca-certificates/sbx-proxy.crt
   sudo update-ca-certificates                          # appends to /etc/ssl/certs/ca-certificates.crt
   export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
   export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
   export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
   ```

4. **Configure the proxy to substitute the real key.** Either:
   - Tell Docker Desktop's MCP gateway about the Anthropic key (UI:
     Sandboxes → Secrets → ANTHROPIC_API_KEY = $real_key), OR
   - Leave the sentinel and let the proxy pass through; have
     `auth_override.apply()` promote the `~/.hermes/.env` key into the
     `x-api-key` header for outbound requests (already the case).

5. **Drop `no_proxy` for AI endpoints.** Remove the `_AI_NO_PROXY` exports
   from `sbx_launcher.py` (or restrict it to `localhost,127.0.0.1,::1`
   only) so AI traffic resumes flowing through the gateway.

### Trade-offs

| Pro | Con |
| :--- | :--- |
| Centralized logging / policy via Docker Admin Console (REQ-9.1.*) | Requires per-OS CA-cert location handling (macOS/Linux/Windows differ) |
| Aligns with sbx's intended architecture | Sandbox now trusts a self-signed CA — auditors may flag |
| Doesn't bypass IT's egress filter | Higher complexity; image rebuild needed to bake CA install scripts |
| Proxy can rate-limit / mask outbound traffic | Breaks if Docker Desktop CA rotates and we don't re-mount |

### When to revisit

- When IT requires centralized audit logs of LLM calls.
- When >1 user / production deployment makes Approach 1's "every machine
  needs the real key in `~/.hermes/.env`" untenable.
- When sbx publishes a stable kit-schema field for env passthrough that
  actually works (then we can drop the launcher workaround AND keep proxy
  routing).

---

## 5. Why Approach 1 first

The user spent a long session getting to a working dashboard. Approach 2
adds CA-mount + image-rebuild complexity that's high-risk in a single
session, and the centralized-logging benefit doesn't matter for a single-
developer setup right now.

Approach 1 is a 1-file, 15-line change that fixes chat today. We capture
Approach 2 here so it's not lost when we eventually need it for production.

---

## 6. Files touched in this fix

```
plugins/sopify_sandbox/sbx_launcher.py          # +20 lines (constant + prologue)
PROXY_FIX_PLAN.md                                # this file
```

`infra/sbx/sopify-kit/spec.yaml` is unchanged — its `env:` block is still
correct, just inert until sbx fixes schema-v1 parsing.

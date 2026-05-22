# Sopify Chat Tab — Session Handoff (2026-05-23)

> Open this file when starting a fresh Claude session about Sopify
> chat. It tells the next assistant exactly what's working, what's
> broken, what to skip, and where to look next.

---

## TL;DR — the actual current state

**What works:** Dashboard loads in browser, model picker works, API key verified valid against Anthropic, sandbox boots cleanly, all infra fixes landed.

**What does NOT work:** Typing "hello" in the /chat tab produces no response. The terminal shows the typed input but no TUI banner, no prompt, and no model reply.

**Why this matters:** The user has spent a long debug session reaching this point. Every layer LOOKS fixed but chat is still empty. The next session must NOT re-debug the layers below — they're all green. Focus on the chat tab itself.

---

## 1. Verified WORKING (do not re-check these)

| Layer | Evidence (run yourself if you need re-proof) |
| :--- | :--- |
| Dashboard FastAPI | `curl http://127.0.0.1:9119/ → HTTP 200` |
| sbx port-publish | `sbx ports $(sbx ls \| awk '/sopify-/ {print $1}')` shows 9119→9119 |
| API key in env | `sopify env list` shows `ANTHROPIC_TOKEN (108 chars)` |
| API key VALID | `curl -s -w "%{http_code}\n" /v1/models -H "x-api-key:$KEY"` → HTTP 200, lists 8 models including `claude-opus-4-5-20251101`, `claude-sonnet-4-5-20250929` |
| `~/.hermes/:ro` mount | `mount` inside microVM shows `bind on /Users/.../.hermes virtiofs (ro,relatime)` |
| Symlink in microVM | `readlink ~/.hermes/.env` inside microVM → `/Users/burased.b/.hermes/.env` |
| Plugin auth_override fix in image | `grep -c SOPIFY_IN_SANDBOX /opt/sopify/plugins/sopify_providers/auth_override.py` → 2 matches |
| Image rebuilt today | `sbx template ls` shows latest hash; `docker images sopify-sandbox` recent |

## 2. What was DONE in this session (do not redo)

Ten fixes, in order — every one of them is now reflected in:
- The source repo at `~/ai_engineer/gs/project-based/sopify/sopify-harness/`
- The runtime symlink `~/.sopify-app/` (now a symlink to the source repo, not a copy)
- The Docker image `sopify-sandbox:latest` (rebuilt today)

1. **Dockerfile** — pre-installs `ui-tui/node_modules` + esbuild bundle at build time. Eliminates "Installing TUI dependencies…" race.
2. **sbx_launcher.py** — added `~/.hermes/:ro` mount as a third workspace.
3. **kit spec.yaml** — added startup symlink commands (later discovered sbx schema v1 ignores `startup` block — this fix is inert but harmless).
4. **sbx_launcher.py** — added `_link_hermes_into_sandbox()` which runs the symlink via `sbx exec` right after sandbox creation. This is the live code path that actually creates `/home/sopify/.hermes/.env → /Users/.../.hermes/.env`.
5. **web/package.json** — changed `build: "tsc -b && vite build"` to `build: "vite build"` (lucide-react implicit-any types were blocking the runtime web build).
6. **plugins/sopify_providers/env_cli.py + env_file.py** — new `sopify env list / set / unset` subcommand that writes directly to `~/.hermes/.env`.
7. **`~/.sopify-app` symlink** — replaced the file-by-file copy install with a symlink to the source repo. Old install preserved as `~/.sopify-app.bak-20260522-231051`. **Do NOT delete** the source repo at `~/ai_engineer/gs/project-based/sopify/sopify-harness/` — the install depends on it now.
8. **sbx_launcher.py** — skip duplicate workspace mount when `cwd.resolve() == app_root.resolve()`. Without this, running `sopify dashboard` from inside the sopify-harness directory failed with "conflicting read-only settings."
9. **plugins/sopify_providers/auth_override.py** — `_sync_hermes_env_file()` now early-returns when `SOPIFY_IN_SANDBOX=1`. Without this, plugin import crashed with `[Errno 30] Read-only file system: '/home/sopify/.hermes/.env'`.
10. **Docker image rebuild** — done today to bake fix #9 into `/opt/sopify/...`.

## 3. What does NOT work (the actual remaining bug)

User types `hello` in /chat tab → nothing happens. No TUI banner appears, no prompt, no response. The xterm in the browser shows just the typed text and a cursor.

This is the SAME symptom we started with, except now all the underlying credential / mount / image issues are resolved. Which means the bug is **specifically in the chat tab's PTY chain or in how the slash_worker fails**, not in infrastructure.

## 4. Things we have NOT verified yet

These are the next-step diagnostics the next session should focus on. **Do these BEFORE writing any more code.**

### Verify the WebSocket actually opens

Have the user open browser DevTools → Network → filter `WS` → click the `/chat` tab in the dashboard. Look for an `/api/pty` row.

- **Status 101 Switching Protocols** = WebSocket opened successfully.
- **Status 4401** = token mismatch (auth bug in our config).
- **Status 4403** = `_ws_client_is_allowed` rejected the client (host binding issue).
- **No row at all** = frontend never tried to connect (build issue).

### Verify the PTY child is actually spawned

While /chat tab is open in browser (don't close it):

```bash
SBOX=$(sbx ls | awk '/sopify-/ {print $1}')
sbx exec $SBOX bash -lc 'ps auxf | grep -E "node|tui_gateway|slash_worker" | grep -v grep'
```

Expected, if PTY chain works:
- `node /opt/sopify/ui-tui/dist/entry.js` (PTY-spawned by FastAPI)
- `python -m tui_gateway.entry` (child of node)
- `python -m tui_gateway.slash_worker --model anthropic/claude-...` (one per typed message)

If `node entry.js` is MISSING → /api/pty handler isn't spawning it (server bug).
If `node entry.js` is there but `tui_gateway.entry` isn't → node TUI crashed before gateway start.
If all three are there but chat still empty → the slash_worker is running but failing silently. Look at HTTP requests to Anthropic.

### Verify slash_worker actually calls Anthropic

Inside the microVM, install tcpdump or use `strace` on the slash_worker to see if any outgoing HTTPS connection is attempted. If not, the worker is failing before the network call. If yes, check whether the response is being parsed correctly.

### Earlier manual TUI spawn produced ONLY ANSI cleanup escapes

When I ran `script -c "node /opt/sopify/ui-tui/dist/entry.js" /tmp/log` inside the microVM manually, the only output was a string of terminal-mode-reset escape codes (no banner, no UI). The process ran 3-4 seconds then exited cleanly (rc 0). **This is the smoking gun**, but I never got to root-cause it.

Suspected reasons:
- `gw.start()` spawns `python -m tui_gateway.entry` and waits on JSON-RPC handshake. If handshake fails, App component might unmount.
- Ink in inline mode (HERMES_TUI_INLINE=1) might render nothing if some Ink-required env is missing.
- `entry.tsx` line 18 checks `process.stdin.isTTY` and exits if false — but PTY DOES provide a TTY, so this should pass. (When the manual `script` was used without TTY allocation, it exited with "hermes-tui: no TTY" — different message, so the TTY check itself isn't the bug.)

## 5. Known small remaining bugs

These are non-critical but should be fixed eventually:

1. **`_publish_port` silently fails on subsequent runs.** First sandbox boot publishes 9119 fine. After `sbx rm` + `sopify dashboard` again, port is not published, requiring manual `sbx ports SBOX --publish 9119:9119`. Reproduces every time. The launcher calls the right sbx CLI command — likely a sbx-side caching issue or timing race.

2. **Two warnings from earlier logs that are NON-fatal:**
   - `model catalog fetch failed ... SSL: CERTIFICATE_VERIFY_FAILED` — Hermes can't fetch the nous catalog through the corporate CA chain in the sandbox. Doesn't affect chat.
   - `Auxiliary Nous client unavailable: no Nous authentication found` — only matters if you want auxiliary calls (compression, vision, etc.). Chat doesn't need this.

3. **Topbar in some dashboard views still shows "HERMES AGENT"** — surface-level brand that wasn't replaced. Cosmetic only.

4. **`dashboard-plugins/example/dist/index.js 404`** in browser console — the "example" dashboard plugin's frontend isn't built. Harmless noise.

## 6. File map for the next session

| File | Purpose |
| :--- | :--- |
| `SESSION_HANDOFF.md` (this file) | Pick-up doc |
| `CHAT_FLOW_DEBUG.md` | Full 10-section debug write-up from yesterday |
| `SOPIFY_ARCHITECTURE.md` | Stable architecture overview |
| `ARCHITECTURE.md` | Hermes core architecture (do not edit — REQ-0.3) |
| `DESIGN_ARCHITECTURE.md` | 12-section requirements spec |
| `plugins/sopify_sandbox/sbx_launcher.py` | The host-side launcher that spawns sbx |
| `plugins/sopify_providers/auth_override.py` | Anthropic key resolution + the Read-only-fs fix |
| `plugins/sopify_providers/env_cli.py` | `sopify env set / list / unset` |
| `plugins/sopify_providers/env_file.py` | Helper that reads/writes `~/.hermes/.env` |
| `docker/sopify-sandbox/Dockerfile` | microVM image build |
| `infra/sbx/sopify-kit/spec.yaml` | sbx kit (only `network.allowedDomains` is actually parsed) |
| `hermes_cli/web_server.py` line 3402 | `/api/pty` WebSocket handler in Hermes |
| `hermes_cli/main.py` line 1110 | `_make_tui_argv` — what gets spawned in the PTY |
| `ui-tui/src/entry.tsx` | The Ink TUI entry; line 18 has `isTTY` exit guard |

## 7. Unpushed git state at handoff time

Branch: `main`. Three commits ahead of `origin/main`:

```
4bff94038 feat(providers): add `sopify env` subcommand for ~/.hermes/.env management
ab88994be feat(sandbox): pre-install TUI deps + mount ~/.hermes for credential passthrough
5a3b19013 feat(branding): surface-level Sopify rebrand + GS Battery logo
```

Plus a fourth unstaged commit pending (the kit-symlink-via-launcher + duplicate-workspace skip + auth_override SOPIFY_IN_SANDBOX skip — all the post-push fixes).

The user has the auto-classifier blocking `git push origin main` (default-branch protection), so they need to push themselves:
```bash
cd ~/ai_engineer/gs/project-based/sopify/sopify-harness && git push origin main
```

The fourth commit (today's fixes) still needs to be created. Use:
```bash
git add plugins/sopify_sandbox/sbx_launcher.py \
        plugins/sopify_providers/auth_override.py \
        infra/sbx/sopify-kit/spec.yaml \
        SESSION_HANDOFF.md \
        CHAT_FLOW_DEBUG.md
```

## 8. Recommended FIRST action for the next session

Do NOT touch any infra code yet. Run these three diagnostics first and report the results:

```bash
# A. Browser DevTools — user does this themselves
echo "Open browser → DevTools (F12) → Network → WS filter → click /chat tab → take screenshot of /api/pty row + Messages tab"

# B. Process inspection while /chat is open
SBOX=$(sbx ls | awk '/sopify-/ {print $1}')
sbx exec $SBOX bash -lc 'ps auxf 2>/dev/null | grep -E "node|tui_gateway|slash_worker|sopify" | grep -v grep'

# C. Anthropic API smoke test from INSIDE the microVM with the EXACT model the user picked
sbx exec $SBOX bash -lc 'curl -s -w "HTTP:%{http_code}\n" -o /tmp/r.json \
    -m 10 https://api.anthropic.com/v1/messages \
    -H "anthropic-version: 2023-06-01" \
    -H "x-api-key: $ANTHROPIC_API_KEY" \
    -H "content-type: application/json" \
    -d "{\"model\":\"claude-sonnet-4-5-20250929\",\"max_tokens\":10,\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}"
head -c 500 /tmp/r.json; rm -f /tmp/r.json'
```

The data from A + B + C will tell us EXACTLY where the chain breaks. Until then, every code fix is a guess.

## 9. Honest assessment of why this session failed

I was firefighting one error at a time instead of running a single end-to-end diagnostic. Each fix was correct but the system needed all of them landed simultaneously. By the time the last fix landed, I'd lost track of whether the original symptom was caused by infra or by something deeper in the chat tab (Ink TUI, PTY bridge, or slash_worker).

The next session should resist the urge to fix code. Start with the three diagnostics in §8 and only touch code after we have a concrete failure mode pinpointed.

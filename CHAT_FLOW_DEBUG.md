# Sopify Chat — Complete Data Flow + Why It's Still Broken

> A no-handwaving walk-through of every layer between "user types in
> /chat" and "Claude responds." Each layer lists the contract it
> provides, the evidence we have it's working, and the failure modes
> that fit the symptom (chat tab stays blank).

---

## 1. The complete chat request flow

```
[Browser tab] http://127.0.0.1:9119/chat
       │
       │ 1. Loads React bundle from /opt/sopify/hermes_cli/web_dist/
       │ 2. Pages/ChatPage.tsx mounts an xterm.js terminal
       │ 3. Opens WebSocket: ws://127.0.0.1:9119/api/pty?token=<sess>
       ▼
[Host TCP:9119]
       │ sbx port-publish forwards to microVM:9119 (verified — HTTP 200)
       ▼
[microVM uvicorn FastAPI :9119]   ← hermes_cli/web_server.py
       │ /api/pty handler:
       │   - validates ?token= against _SESSION_TOKEN  (4401 if bad)
       │   - calls _ws_client_is_allowed (4403 if bad)
       │   - await ws.accept()
       │   - _resolve_chat_argv() → ['/usr/bin/node', '.../entry.js']
       │   - bridge = PtyBridge.spawn(argv, cwd=..., env=...)
       ▼
[node PTY child] /opt/sopify/ui-tui/dist/entry.js
       │ ui-tui/src/entry.tsx:
       │   - if (!process.stdin.isTTY) exit         ← passes (PTY has TTY)
       │   - resetTerminalModes()                     ← writes ANSI escapes
       │   - new GatewayClient(); gw.start()          ← spawns python child
       │   - ink.render(<App gw={gw} />)              ← renders TUI
       ▼
[python child] /opt/sopify/.venv/bin/python -m tui_gateway.entry
       │ Subprocess of node; stdio JSON-RPC pipe to parent
       │   - dispatch RPCs from TUI (e.g. "send a message")
       │   - spawn slash_worker subprocesses (one per active model)
       ▼
[slash_worker] /opt/sopify/.venv/bin/python -m tui_gateway.slash_worker
       │   - load_dotenv("/home/sopify/.hermes/.env", override=True)
       │     → reads symlinked file → host's .env → ANTHROPIC_TOKEN
       │   - resolve provider for model "anthropic/claude-..."
       │   - HTTP POST to api.anthropic.com (via sbx-allowed egress)
       │   - stream tokens back via JSON-RPC to gateway → TUI → PTY → WS → xterm
```

---

## 2. What works today (verified evidence)

| Layer | Evidence |
| :--- | :--- |
| Browser → host:9119 | `curl 127.0.0.1:9119 → HTTP 200` |
| Host → microVM port | `sbx ports SBOX` shows `127.0.0.1:9119 -> 9119/tcp` |
| FastAPI serving React | Browser shows GS\|SOPIFY sidebar + tabs |
| `~/.hermes/.env` mount | `mount` inside VM shows `bind on /Users/.../.hermes virtiofs (ro)` |
| Symlink applied | `ls -la ~/.hermes/.env` inside VM → symlink to `/Users/.../.env` |
| .env contains real key | `sopify env list` shows ANTHROPIC_TOKEN 108 chars (real key length) |
| Dashboard loads plugins | No "plugin sopify_providers failed to load" on latest run |
| `sopify env set` works | Wrote 108-char key + verified inside microVM |

## 3. What we DON'T yet have evidence of working

| Layer | Why uncertain | How to verify |
| :--- | :--- | :--- |
| WS /api/pty connects | No DevTools Network tab capture shared | F12 → Network → WS → look for `/api/pty` row |
| PtyBridge spawns node | `ps auxf` snapshots are point-in-time | `ps auxf \| grep entry.js` while /chat tab open |
| node TUI renders to PTY | Earlier manual spawn showed only ANSI cleanup escapes | `script -c "node entry.js" /tmp/log` + check non-escape output |
| gateway.entry child alive | Need `pgrep -f tui_gateway.entry` after typing | Process inspection while chatting |
| slash_worker spawned per msg | Logs earlier showed 4× workers — but no model output | Watch `ps` during a single hello |
| Anthropic HTTP 200 | Earlier logs showed `payment / credit error` from OpenRouter | curl the API directly with the key (108 chars) |
| Tokens stream back | If model returns, do bytes reach xterm? | DevTools → Network → WS Messages frames |

---

## 4. The two-file install pitfall (the meta-bug)

```
/Users/.../sopify-harness/      ← canonical source (git tracked, where you edit)
~/.sopify-app                   ← previously a copy, NOW a symlink → source
/opt/sopify/                    ← inside the microVM, baked into Docker image
                                  (separate from both above)
```

**Three places** that hold the same files:

- **Source repo** — your edits.
- **`~/.sopify-app/`** — what `sopify` CLI loads on the host. (Symlinked now.)
- **`/opt/sopify/`** — what the microVM loads. Frozen at image build time.

**Implication:** an edit to a plugin or shim takes effect:

- Immediately on the host (since `~/.sopify-app` is the symlink to source).
- Only inside the microVM if you either (a) rebuild the Docker image,
  or (b) `sbx cp` the file into the running sandbox.

Plugin loading runs INSIDE the microVM. So `auth_override.py` fixes
need (a) or (b) to be active.

---

## 5. Every fix attempted today, in order

| # | Fix                                                                 | Layer        | Verified active? |
| :-: | :------------------------------------------------------------------ | :----------- | :--------------- |
| 1 | Pre-install TUI npm + esbuild bundle in Dockerfile                  | image build  | ✓ rebuilt once   |
| 2 | Mount `~/.hermes/:ro` as third workspace                            | sbx_launcher | ✓ visible in `mount` |
| 3 | Kit `startup` symlink for /home/sopify/.hermes/.env                 | kit          | ✗ kit ignores `startup` (schema v1 only honors `network.allowedDomains`) |
| 4 | Move symlink logic to `_link_hermes_into_sandbox` via `sbx exec`    | sbx_launcher | ✓ runs at sandbox boot |
| 5 | `web/package.json` build = `vite build` only (skip tsc)             | host build   | ✓ confirmed     |
| 6 | `sopify env set` subcommand for ~/.hermes/.env                      | host CLI     | ✓ wrote 108-char key |
| 7 | Symlink `~/.sopify-app` → source repo                               | host install | ✓ verified       |
| 8 | Skip duplicate-workspace error when cwd == app_root                 | sbx_launcher | ✓ creates fine now |
| 9 | `auth_override.py` skip `.env` write when `SOPIFY_IN_SANDBOX=1`     | host plugin  | ⚠ on host symlink, NOT in microVM image |
| 10 | `sbx cp` plugin file into running sandbox                          | runtime      | ✓ at the time, lost on recreation |

---

## 6. Why chat is still empty — three hypotheses ranked

### H1 (most likely): `auth_override.py` fix isn't in the microVM

After `sbx rm` + fresh `sopify dashboard`, the new sandbox loads
`/opt/sopify/plugins/sopify_providers/auth_override.py` **from the
Docker image** (frozen at fix #1's build time). Fix #9 only landed in
the symlinked source repo, not the image. So plugin import still
crashes with EROFS, dashboard never reaches uvicorn startup → no
PTY bridge → chat blank.

**Evidence:** earlier logs showed `plugin sopify_providers failed
to load: [Errno 30] Read-only file system`. That's import-time
crash. After that, the rest of Hermes loaded with sopify_providers
**missing** — so no `auth_override`, no plugin hooks, no provider
cascade. Hermes might still serve the dashboard HTTP page but the
chat backend is partially broken.

**Verify:** `sbx exec <SBOX> grep -c SOPIFY_IN_SANDBOX /opt/sopify/plugins/sopify_providers/auth_override.py`
Returns 0 → microVM has the old file.
Returns ≥1 → it has the fix.

### H2: PTY WS connects but `node entry.js` exits before render

Earlier manual tests showed node entry.js running for ~3-4s then
exiting with only ANSI cleanup escapes — no UI ever rendered. This
might be because `gw.start()` fails to spawn `python -m
tui_gateway.entry`, then App component throws or unmounts.

**Verify:** in a fresh sandbox while /chat is open in browser:
`sbx exec <SBOX> ps auxf | grep -E "node|tui_gateway.entry"`
- If node + python child both present → PTY chain works.
- If only node, no python child → gateway spawn failing.
- If neither → /api/pty never spawned (WS auth failing).

### H3: Slash_worker calls Anthropic but auth fails

Even with the right 108-char key, the request could fail with 401 if:
- The key is for a different account than the model picker shows.
- The model name (claude-opus-4-5-20251101) doesn't exist for this
  account (would return 404 → silent failure).
- Network policy blocks api.anthropic.com (we have it allowed, but
  let's verify).

**Verify** (no key leak — uses length only):
```bash
sbx exec <SBOX> bash -lc '
  curl -s -o /dev/null -w "HTTP:%{http_code}\n" \
       -m 8 https://api.anthropic.com/v1/messages \
       -H "anthropic-version: 2023-06-01" \
       -H "x-api-key: $ANTHROPIC_API_KEY" \
       -H "content-type: application/json" \
       -d "{\"model\":\"claude-3-5-sonnet-latest\",\"max_tokens\":5,\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}"
'
```
- HTTP 200 → key works.
- HTTP 401 → bad key.
- HTTP 404 → model name wrong.
- HTTP 403/network err → policy blocking.

---

## 7. The recommended fix order (root-cause, not symptom)

Step 1. **Rebuild the Docker image** so all today's plugin/launcher
fixes are baked in:

```bash
cd ~/.sopify-app
docker build -t sopify-sandbox:latest -f docker/sopify-sandbox/Dockerfile . \
  && docker save -o /tmp/s.tar sopify-sandbox:latest \
  && sbx template load /tmp/s.tar \
  && rm /tmp/s.tar
```

This eliminates H1 entirely. Time: ~3-5 min (most layers cached).

Step 2. **Recreate sandbox from new image**:

```bash
sbx rm --force $(sbx ls | awk '/^sopify-/ {print $1}')
sopify dashboard
```

Step 3. **While dashboard is running, verify H2 + H3 in parallel:**

```bash
# H2 — is the PTY chain alive?
SBOX=$(sbx ls | awk '/^sopify-/ {print $1}')
sbx exec $SBOX ps auxf | grep -E "node|tui_gateway"

# H3 — does the API key work?
sbx exec $SBOX bash -lc 'curl -s -o /dev/null -w "%{http_code}\n" \
  -m 8 https://api.anthropic.com/v1/messages \
  -H "anthropic-version: 2023-06-01" \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "content-type: application/json" \
  -d "{\"model\":\"claude-3-5-sonnet-latest\",\"max_tokens\":5,\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}"'
```

Step 4. Browser DevTools Network → WS → click `/api/pty` row →
report status code and any frame data.

The first time all three signals say "OK," chat will start
responding. We're stuck because we never had all three green at
once.

---

## 8. Long-term architectural improvements (after chat works)

1. **Single source of truth for code.** The two-file install is a
   constant footgun. Either install Sopify as a proper Python
   package (`pip install -e .`) or always symlink. Today's symlink
   trick covers host-side but the Docker image still ships a frozen
   snapshot.

2. **Live-mount the source repo into the microVM** as a workspace,
   then set `PYTHONPATH=/Users/.../sopify-harness:/opt/sopify` so
   Python imports plugins from the mount first. Then plugin edits
   are picked up without an image rebuild.

3. **Health-check + structured error reporting in /chat.** Today
   the chat tab silently shows nothing on any failure. Add a sentinel
   server message at WS connect that confirms the PTY child + gateway
   + worker are all alive. If any layer is dead, show a banner
   ("Anthropic key unauthorized — run `sopify env set anthropic`")
   instead of an empty terminal.

4. **`sopify doctor --inside-sandbox`** that walks the chain inside
   the microVM and reports each layer's status. Today we have host
   doctor only.

5. **Lock the model picker to models that the configured provider
   actually supports.** Today we can pick `claude-opus-4-5-20251101`
   which might not even exist on the account, with no validation.

---

## 9. What you should do RIGHT NOW

```bash
# 1. Stop everything cleanly
# (Ctrl+C in the dashboard terminal)

# 2. Remove the running sandbox (fresh start)
sbx rm --force $(sbx ls 2>/dev/null | awk '/^sopify-/ {print $1}')

# 3. Rebuild Docker image (~3-5 min)
cd ~/.sopify-app && docker build -t sopify-sandbox:latest \
    -f docker/sopify-sandbox/Dockerfile . 2>&1 | tail -10

# 4. Sync into sbx template store
docker save -o /tmp/sopify.tar sopify-sandbox:latest \
    && sbx template load /tmp/sopify.tar && rm /tmp/sopify.tar

# 5. Launch
sopify dashboard

# 6. While dashboard loads, verify H3 — Anthropic API key actually works:
SBOX=$(sbx ls | awk '/^sopify-/ {print $1}')
sbx exec $SBOX bash -lc 'curl -s -o /dev/null -w "%{http_code}\n" \
    -m 8 https://api.anthropic.com/v1/messages \
    -H "anthropic-version: 2023-06-01" \
    -H "x-api-key: $ANTHROPIC_API_KEY" \
    -H "content-type: application/json" \
    -d "{\"model\":\"claude-3-5-sonnet-latest\",\"max_tokens\":5,\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}"'
```

If step 6 returns `200`, the API key chain is fine — chat should work.
If `401` or `404`, that's the real bug and we fix it at the provider
config layer, not the sandbox layer.

If step 6 says `200` but chat still empty, the breakage is between
slash_worker and xterm.js — and we move to H2 (PTY chain inspection)
with concrete evidence.

---

## 10. Why I kept missing this

Honest answer: I've been fixing symptoms one mount, one error
message at a time. Each fix uncovered the next one. The root cause
chain is:

  • Anthropic key missing in microVM
     → because ~/.hermes/.env wasn't mounted
     → fixed mount (#2)
  • but .env wasn't symlinked into /home/sopify
     → fixed via kit startup (#3, which silently failed)
     → moved to launcher exec (#4)
  • but auth_override.py tried to WRITE the read-only mount
     → fixed source repo (#9)
     → but microVM image still ships old copy
     → which causes the current "plugin failed to load" error

Each fix was correct in isolation but the system needs ALL of them
landed simultaneously. The Docker image rebuild in step 3 above
is what binds them together. I should have rebuilt the image after
fix #9 instead of trying to `sbx cp` it.

I'm sorry for the runaround. Step-3 image rebuild is the
one-shot remedy.

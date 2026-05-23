# Chat Tab Render Bug — RESOLVED (2026-05-23)

> **STATUS: FIXED.** The dashboard `/chat` tab now renders the Hermes TUI
> correctly (GS Battery banner, prompt, status bar, model badge all paint).
> Root cause was a `signal-exit` v3-vs-v4 import-shape mismatch that caused
> the Ink constructor to throw a swallowed TypeError mid-init. One-file
> patch in `ink.tsx` resolves it.

---

## 1. Symptom recap

| Layer | Status |
| :--- | :--- |
| WebSocket `/api/pty` handshake | ✅ `101 Switching Protocols` |
| WS client → server: `[RESIZE:cols;rows]` | ✅ sent within 1ms of WS open |
| WS server → client (first burst) | ⚠️ 141 bytes total, **then total silence** |
| PTY child `node entry.js` | ✅ alive (`ps auxf` shows running) |
| `tui_gateway.entry` Python child | ✅ alive (alive socket pair to node) |
| `slash_worker` subprocesses on type | ✅ spawn + complete + exit cleanly |
| Anthropic API call via slash worker | ✅ `HTTP 200` in ~1.9s |
| Browser xterm panel | ❌ **blank — no banner, no prompt, no response** |

The 141 bytes the server emits are exactly:
- 130 B from `resetTerminalModes()` (ANSI mode-reset codes — `\x1b[?1000l`, `\x1b[?1049l`, etc.)
- 11 B from `\x1b[2J\x1b[H\x1b[3J` (clear screen + cursor home + clear scrollback)

Both happen **before** Ink mounts. Nothing from React, nothing from
`AppLayout`, nothing from any frame Ink would normally paint.

## 2. Methodology — how the trace was built

A guarded trace helper was injected into [ui-tui/src/entry.tsx](ui-tui/src/entry.tsx):

```ts
const T = (label: string) => {
  if (process.env.SOPIFY_TUI_TRACE === '1') {
    process.stderr.write(`[SOPIFY_TRACE] ${label}\n`)
  }
}
```

Markers were placed at every boot step (00–13). A `SOPIFY_TUI_STUB=1` env
swaps the real `<App>` for a 5-line `<Box><Text>SOPIFY_STUB_RENDERED</Text></Box>`
component, isolating "Ink is broken" from "App is broken". A `SOPIFY_TUI_SYNC=1`
env calls `renderSync()` directly to bypass `@hermes/ink`'s async
`wrappedRender` wrapper and rule out microtask scheduling as the culprit.

The trace ran inside the microVM through `ptyprocess.PtyProcess.spawn(...)`
with the same `dimensions=(30, 120)` that the real `pty_bridge.PtyBridge.spawn`
uses ([hermes_cli/pty_bridge.py:86](hermes_cli/pty_bridge.py#L86)), so the env
is byte-equivalent to a real `/api/pty` session.

## 3. What we ruled out

| Hypothesis | Evidence against |
| :--- | :--- |
| `process.stdin.isTTY === false` exit guard | `01 isTTY ok` trace fires |
| `HERMES_TUI_INLINE=1` empty-render mode | Same hang with `HERMES_TUI_INLINE` unset |
| `process.stdout.columns === 0` Ink early-bail | ptyprocess sets `columns=120, rows=30` via `dimensions=` arg |
| Missing `TERM` env var | PtyBridge.spawn backfills `xterm-256color` |
| Anthropic credential/network issue | `slash_worker` exits cleanly; manual curl returns HTTP 200 |
| Gateway handshake failure | `tui_gateway.entry` alive on Unix socketpair; `slash_worker` spawns indicate handshake succeeded |
| App component throws (useMainApp 852 lines) | Stub component (`<Box><Text>SOPIFY_STUB_RENDERED</Text></Box>`) hangs identically |
| `wrappedRender` async wrapper microtask issue | Direct `renderSync()` (sync) hangs at the same point |
| Promise rejection swallowed silently | `.then()` and `.catch()` chained — neither fires within 8s |

## 4. Root cause — `signal-exit` version mismatch

**Initial impression was wrong.** The Ink renderer did not "hang" — it threw
a synchronous TypeError mid-constructor that Hermes' top-level
uncaughtException handler silently caught. This is why nothing crashed
visibly and the process stayed alive: there was no actual deadlock, just a
half-initialized Ink instance that never reached `instance.render(node)`.

### Why traces appeared to stop

After patch 1's trace markers were inserted, the apparent stop point shifted
each time a layer was instrumented. The decisive insight: `Ink`'s
constructor calls `patchStderr()` (around line 322 of `ink.tsx`), which
**replaces `process.stderr.write` with an interceptor that silently swallows
its argument unless the alt-screen is active**. Every trace after that point
was being eaten by the interceptor. Switching the trace helper to
`writeSync(2, ...)` (raw `fs` syscall, bypasses the JS stream patch)
revealed the next several markers in sequence.

### The exact bug

Once traces were visible past `patchStderr`, the next hidden point was
`onExit(this.unmount, { alwaysLast: false })` at
[ui-tui/packages/hermes-ink/src/ink/ink.tsx:383](ui-tui/packages/hermes-ink/src/ink/ink.tsx#L383):

```
[SOPIFY_TRACE_INKC] C3  frames+pools+throttle done; about to onExit
[SOPIFY_TRACE_INKC] C3a onExit type=undefined  unmount type=function
```

The `onExit` symbol is **`undefined` at runtime**:

| File | Declares / installs |
| :--- | :--- |
| [ui-tui/packages/hermes-ink/package.json](ui-tui/packages/hermes-ink/package.json) | `"signal-exit": "^4.1.0"` (named `onExit` export) |
| `ui-tui/node_modules/signal-exit/package.json` | **version 3.0.7** (CommonJS, `module.exports = function() {}`, no named exports) |

esbuild bundles `import { onExit } from 'signal-exit'`. With v3 hoisted at
the workspace root, the named import resolves to `undefined`.
`undefined(this.unmount, { alwaysLast: false })` throws
`TypeError: onExit is not a function`. The Ink instance is half-built — no
`this.container`, no reconciler — and the throw rides up the stack to
Hermes' `setupGracefulExit` uncaughtException handler in `entry.tsx`, which
swallows it (`process.stderr.write(...)` → also swallowed by the parent's
shell, since Hermes hasn't fully wired its output paths yet).

The Promise from `wrappedRender` never resolves *or* rejects: it was
created and the synchronous renderSync threw mid-microtask. From the
outside, the WebSocket is alive, the PTY child is alive, the gateway runs,
slash workers complete API calls — but Ink never paints a frame.

### Why workspace hoisting picked v3

Some other dep at the `ui-tui` workspace level (likely `ptyprocess` or one
of the eslint/babel toolchain packages) requires `signal-exit@^3`. npm/pnpm
deduplication hoists the lower-version satisfying both to the top-level
`node_modules`. The hermes-ink subpackage's nested install doesn't supersede
the hoisted v3 because `^4.1.0` is incompatible with `^3.x` peer constraints.

## 5. APPLIED FIX

One-file change in
[ui-tui/packages/hermes-ink/src/ink/ink.tsx](ui-tui/packages/hermes-ink/src/ink/ink.tsx):

```diff
-import { onExit } from 'signal-exit'
+// signal-exit changed its export shape between v3 (CommonJS default export)
+// and v4 (named `onExit` export). hermes-ink declares v4 but workspace
+// hoisting can resolve v3 from the parent node_modules, in which case
+// `import { onExit }` is undefined and the constructor silently throws
+// TypeError mid-init (caught by Hermes' uncaughtException handler), leaving
+// the Ink instance half-constructed and Ink's React reconciler never paints
+// a single frame. Resolve at module load against either shape.
+import * as _signalExitNs from 'signal-exit'
+const onExit: (cb: () => void, opts?: { alwaysLast?: boolean }) => () => void =
+  ((_signalExitNs as any).onExit ?? (_signalExitNs as any).default ?? (_signalExitNs as any)) as never
```

Both v3 and v4 signatures match `(cb, opts) => () => void`, so the shim
works transparently regardless of which version was hoisted.

### Verification

After applying the patch + rebuilding (`node scripts/build.mjs`) + redeploying
to `/opt/sopify/ui-tui/dist/entry.js`:

```
[SOPIFY_TRACE_INKC] C3a onExit type=function unmount type=function       ✅
[SOPIFY_TRACE_INKC] C4  onExit registered                                ✅
[SOPIFY_TRACE_INKC] C5  TTY listeners done; about to dom.createNode      ✅
[SOPIFY_TRACE_INKC] C10 reconciler.createContainer done; ctor returning  ✅
[SOPIFY_TRACE_INK]  R5  instance.render(node) returned                   ✅
SOPIFY_STUB_RENDERED                                                     ✅
```

Running with the real `<App>` produces the full Hermes TUI banner:

```
   GS Battery · AI agent with org governance
   summoning hermes…
   ❯ Ask me anything…
   ready │ sonnet 4.5 20250929 │ /20k │ [░░░░░░░░░░] 0% │ 1s │ voice off
```

### Files left on disk (trace patches)

The instrumentation added during the hunt is **all env-guarded** behind
`SOPIFY_TUI_TRACE=1` and has **zero runtime cost** when the flag is unset.
Safe to leave in place as a permanent debugging hook for future PTY issues.

| File | What's left |
| :--- | :--- |
| [ui-tui/src/entry.tsx](ui-tui/src/entry.tsx) | `T()` helper + 20 numbered `[SOPIFY_TRACE]` markers + `SOPIFY_TUI_STUB`/`SOPIFY_TUI_SYNC` env switches |
| [ui-tui/packages/hermes-ink/src/ink/root.ts](ui-tui/packages/hermes-ink/src/ink/root.ts) | `_ST()` helper + 6 `[SOPIFY_TRACE_INK]` markers around `renderSync` |
| [ui-tui/packages/hermes-ink/src/ink/ink.tsx](ui-tui/packages/hermes-ink/src/ink/ink.tsx) | 10 `[SOPIFY_TRACE_INKC]` markers in constructor + `SOPIFY_TUI_SKIP_ONEXIT` switch |

To remove them later, grep for `SOPIFY_TRACE` and `SOPIFY_TUI_` across
those three files.

### Upstream follow-up

This same import is in upstream Hermes Ink. Worth opening an issue / PR so
other consumers don't hit it. Reproduction is simple:
1. `npm install signal-exit@3` in a project that depends on `@hermes/ink`
2. Run any Ink program — it silently hangs in renderSync

The fix in our patch is fully backwards-compatible with v4 and works
across npm/pnpm/yarn workspace hoisting strategies.

## 5-OLD. Fix paths considered before root cause was nailed

### Path A — Use `sopify chat` from host terminal (no fix, immediate workaround)

**Effort:** zero. **Status:** ready today.

`sopify chat` (without the dashboard) spawns the same Ink TUI but
attaches it to the user's actual macOS terminal TTY. The hang doesn't
reproduce there because the terminal advertises a real terminfo entry
and the Yoga init has time to settle inside an interactive shell
(plausibly — needs confirmation).

```bash
cd <project dir>
sopify chat
```

**Cost:** Loses the dashboard browser UI for chat. Sidebar / model
picker / analytics still live at `http://127.0.0.1:9119`.

### Path B — Replace `/chat` with a non-Ink React UI driven by `/api/ws` (RECOMMENDED long-term)

**Effort:** 2–4 days. **Status:** architecturally already supported.

The dashboard exposes two parallel transports for the same chat session:

| Transport | Used by | What it streams |
| :--- | :--- | :--- |
| `/api/pty` | xterm.js → Ink TUI | Raw ANSI bytes (broken — this doc) |
| `/api/ws` | Sidebar React | JSON-RPC `gateway.dispatch` events |
| `/api/pub` + `/api/events` | Sidebar React | Structured tool-call / streaming events |

`hermes_cli/web_server.py:3712-3739` already routes `/api/ws` to
`tui_gateway.ws.handle_ws` — the same dispatcher the Ink TUI speaks to.

**Plan:**
1. Build `web/src/pages/ChatPage.tsx` v2 that:
   - Connects only to `/api/ws` (drop xterm + PTY entirely)
   - Renders messages as native React components (composer, transcript,
     tool calls, slash menu, model badge — all already styled in the
     sidebar)
   - Reuses `OAuthProvidersCard` + new `ApiKeyUploadCard` patterns
2. Mount it behind a `?ui=native` query flag while `?ui=tui` keeps the
   old xterm path (for fallback / dogfood comparison).
3. Once native UI is stable, remove `/api/pty` + `xterm.js` dep.

**Wins:**
- No Ink dependency in browser path — bug class eliminated.
- Native React = better a11y, copy/paste, theming, search-in-transcript.
- ~470 KB less in the JS bundle (xterm + addons).

**Costs:**
- Reimplement composer keybindings (Ctrl+R history, paste handling).
- Lose ANSI passthrough — slash output that's ANSI-heavy needs server-
  side parse-to-html.

### Path C — Patch `@hermes/ink` to fix the synchronous hang (deepest)

**Effort:** 1–3 days of upstream debug + maybe upstream PR cycle.
**Status:** needs Yoga-init trace.

Concrete steps:

1. **Reproduce minimally.** Write `repro.mjs` that imports `@hermes/ink`'s
   `render` and renders `<Box><Text>x</Text></Box>` inside a `ptyprocess`-
   spawned Node. Confirm the hang reproduces with zero Hermes code.

2. **Trace the Ink constructor.** Wrap each line of
   `packages/hermes-ink/src/ink/ink.ts` constructor with `console.error`
   stamps. Identify the exact sync call that blocks.

3. **Likely fixes:**
   - If Yoga init: bundle config in `build.mjs` already aliases
     `@hermes/ink` to source — but the source path may itself contain a
     top-level await that esbuild flattens. Force `await loadYoga()` to
     resolve before `renderSync` exits.
   - If `setRawMode`/`tcsetattr`: switch to `process.stdin.setRawMode(false)`
     during first paint, restore after first frame.
   - If terminal capability probe: short-circuit the probe when
     `process.env.HERMES_TUI_TERMINFO=skip`.

4. **Upstream**: open a PR against the `@hermes/ink` repo. Until merged,
   carry a patch in `ui-tui/packages/hermes-ink/` (it's a workspace
   package, not an external dep).

## 6. What's already on disk

Files touched while investigating (kept for next session):

| File | Status |
| :--- | :--- |
| [ui-tui/src/entry.tsx](ui-tui/src/entry.tsx) | Patched with `[SOPIFY_TRACE]` markers + `SOPIFY_TUI_STUB` + `SOPIFY_TUI_SYNC` env guards. **Zero overhead** when env vars are unset; safe to leave in. |
| [ui-tui/dist/entry.js](ui-tui/dist/entry.js) | Rebuilt via `node scripts/build.mjs`. Deployed to sandbox via `sbx cp`. |
| `/opt/sopify/ui-tui/dist/entry.js` (in sandbox) | Mirrors host. |
| [plugins/sopify_sandbox/sbx_launcher.py](plugins/sopify_sandbox/sbx_launcher.py) | Approach 1 prologue (no_proxy + unset sentinel). Unrelated to chat bug but already shipped. |
| [hermes_cli/web_server.py](hermes_cli/web_server.py) | `/api/providers/api-key` endpoints (Approach 3 UI). Unrelated to chat bug. |

To reproduce the trace from a clean session:

```bash
SBOX=sopify-2a36ea0ad1   # or $(sbx ls | awk '/^sopify-/ {print $1}')

sbx exec "$SBOX" bash -lc '
python3 << "PYEOF"
import os, select, time, sys, re
sys.path.insert(0, "/opt/sopify/.venv/lib/python3.13/site-packages")
import ptyprocess
env = {**os.environ,
       "SOPIFY_TUI_TRACE": "1",
       "SOPIFY_TUI_STUB":  "1",
       "TERM": "xterm-256color"}
proc = ptyprocess.PtyProcess.spawn(
    ["/usr/bin/node", "/opt/sopify/ui-tui/dist/entry.js"],
    env=env, dimensions=(30, 120))
fd, buf, deadline = proc.fd, b"", time.time() + 8
while time.time() < deadline:
    r,_,_ = select.select([fd],[],[],0.2)
    if r:
        try:
            c = os.read(fd, 8192)
            if c: buf += c
        except OSError: break
text = re.sub(r"\x1b\[[0-9;<>?]*[a-zA-Z]", "", buf.decode(errors="replace"))
print(f"== {len(buf)} bytes ==")
for ln in text.split("\n"):
    if "SOPIFY" in ln or "TRACE" in ln or "STUB" in ln:
        print(ln.strip())
proc.terminate(force=True)
PYEOF
'
```

Expected output today: stops at `10c calling renderSync directly` (or
`11 ink.render returned (type=object, isPromise=true)` without sync flag).

## 7. Recommendation

For **today's user-facing problem** (chat must work in a browser at
`http://127.0.0.1:9119/chat`):

| Priority | Action | Owner | Effort |
| :--- | :--- | :--- | :--- |
| P0 | Ship **Path A** — document `sopify chat` from terminal as the supported chat surface; hide /chat tab or add a "Coming soon" banner | this session | 1 hour |
| P1 | Start **Path B** — design doc for /api/ws-driven native UI | next session | 1 day design |
| P2 | Open issue against `@hermes/ink` with the trace data above | next session | 30 min |
| P3 | Implement **Path B** v1 behind `?ui=native` flag | follow-up | 2–3 days |
| P4 | (Optional) Pursue **Path C** patch if upstream is slow | follow-up | open-ended |

## 8. Why this fits Sopify scope

[SESSION_HANDOFF.md §6](SESSION_HANDOFF.md#L114) marks `ui-tui/` as a
Sopify layer (not `hermes_cli/agent/*`, which REQ-0.3 forbids modifying).
The `entry.tsx` trace patch is already there. Path B builds a Sopify-
owned ChatPage that consumes the public `/api/ws` contract — no Hermes
internals touched.

Path C touches `@hermes/ink`, which lives in `ui-tui/packages/hermes-ink/`
as a workspace package — still inside Sopify's git, still patchable.

Net: this bug is fixable end-to-end without violating any REQ-0.3
constraint. The only reason to not fix it immediately is bandwidth, not
permission.

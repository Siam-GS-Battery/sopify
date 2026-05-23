#!/usr/bin/env -S node --max-old-space-size=8192 --expose-gc
// Must be first import. If the user explicitly opts into truecolor, this
// nudges chalk / supports-color before either package is initialized.
import './lib/forceTruecolor.js'

import type { FrameEvent } from '@hermes/ink'

import { TERMUX_TUI_MODE } from './config/env.js'
import { GatewayClient } from './gatewayClient.js'
import { setupGracefulExit } from './lib/gracefulExit.js'
import { formatBytes, type HeapDumpResult, performHeapDump } from './lib/memory.js'
import { type MemorySnapshot, startMemoryMonitor } from './lib/memoryMonitor.js'
import { openExternalUrl } from './lib/openExternalUrl.js'
import { resetTerminalModes } from './lib/terminalModes.js'

// SOPIFY TRACE — instrument boot path so we can pinpoint where Ink stops
// rendering. Writes are guarded by SOPIFY_TUI_TRACE=1 so production runs
// are unaffected. Remove once the chat-empty bug is rooted.
const T = (label: string) => {
  if (process.env.SOPIFY_TUI_TRACE === '1') {
    process.stderr.write(`[SOPIFY_TRACE] ${label}\n`)
  }
}
T('00 boot enter')

if (!process.stdin.isTTY) {
  console.log('hermes-tui: no TTY')
  process.exit(0)
}
T('01 isTTY ok')

// Start from a clean slate. If a previous TUI crashed or was kill -9'd, the
// terminal tab can still have mouse/focus/paste modes enabled.
resetTerminalModes()
T('02 resetTerminalModes done')

// Desktop terminals benefit from a clean startup slate because the TUI usually
// runs in AlternateScreen. On Termux we keep prior output intact so users can
// review/copy earlier assistant replies after reopening the app.
if (TERMUX_TUI_MODE) {
  process.stdout.write('\n')
} else {
  process.stdout.write('\x1b[2J\x1b[H\x1b[3J')
}
T(`03 clear-screen done (termux=${TERMUX_TUI_MODE})`)

const gw = new GatewayClient()
T('04 GatewayClient constructed')

gw.start()
T('05 gw.start() returned (fire-and-forget)')

const dumpNotice = (snap: MemorySnapshot, dump: HeapDumpResult | null) =>
  `hermes-tui: ${snap.level} memory (${formatBytes(snap.heapUsed)}) — auto heap dump → ${dump?.heapPath ?? '(failed)'}\n`

setupGracefulExit({
  cleanups: [
    () => {
      resetTerminalModes()

      return gw.kill()
    }
  ],
  onError: (scope, err) => {
    const message = err instanceof Error ? `${err.name}: ${err.message}` : String(err)

    process.stderr.write(`hermes-tui ${scope}: ${message.slice(0, 2000)}\n`)
  },
  onSignal: signal => {
    resetTerminalModes()
    process.stderr.write(`hermes-tui: received ${signal}\n`)
  }
})
T('06 setupGracefulExit done')

const stopMemoryMonitor = startMemoryMonitor({
  onCritical: (snap, dump) => {
    resetTerminalModes()
    process.stderr.write(dumpNotice(snap, dump))
    process.stderr.write('hermes-tui: exiting to avoid OOM; restart to recover\n')
    process.exit(137)
  },
  onHigh: (snap, dump) => process.stderr.write(dumpNotice(snap, dump))
})
T('07 startMemoryMonitor done')

if (process.env.HERMES_HEAPDUMP_ON_START === '1') {
  void performHeapDump('manual')
}

process.on('beforeExit', () => stopMemoryMonitor())
T('08 about to await Promise.all([ink, app, perfPane, fpsStore])')

const inkModP = import('@hermes/ink').then(m => { T('08a ink imported'); return m })
const appModP = import('./app.js').then(m => { T('08b app imported'); return m })
const perfModP = import('./lib/perfPane.js').then(m => { T('08c perfPane imported'); return m })
const fpsModP = import('./lib/fpsStore.js').then(m => { T('08d fpsStore imported'); return m })

const [ink, { App }, { logFrameEvent }, { trackFrame }] = await Promise.all([
  inkModP, appModP, perfModP, fpsModP
])
T('09 Promise.all resolved')

// Both consumers are undefined when their env flags are off; only attach
// onFrame when at least one is on so ink skips timing in the default case.
const onFrame =
  logFrameEvent || trackFrame
    ? (event: FrameEvent) => {
        logFrameEvent?.(event)
        trackFrame?.(event.durationMs)
      }
    : undefined
T('10 about to call ink.render')

// SOPIFY TRACE — when SOPIFY_TUI_STUB=1, swap App for a minimal Ink component
// to isolate whether Ink itself paints, or App is the one returning null /
// throwing.
const { Box, Text, renderSync } = ink as unknown as { Box: any; Text: any; renderSync: any }
const StubApp = () => {
  T('11_inside_stub_app render call')
  return <Box><Text>SOPIFY_STUB_RENDERED</Text></Box>
}
const RenderTarget = process.env.SOPIFY_TUI_STUB === '1' ? <StubApp /> : <App gw={gw} />
T(`10a using ${process.env.SOPIFY_TUI_STUB === '1' ? 'StubApp' : 'real App'}`)

// SOPIFY TRACE — try renderSync() (the underlying sync renderer) to bypass
// the async `wrappedRender` microtask path entirely. If StubApp renders here
// but not via render(), the bug is in wrappedRender's await Promise.resolve()
// microtask scheduling (likely event-loop-blocked by gw.start()).
if (process.env.SOPIFY_TUI_SYNC === '1') {
  T('10b calling renderSync directly')
  try {
    const syncInst = renderSync(RenderTarget, {
      exitOnCtrlC: false,
      onFrame: (event: FrameEvent) => T(`11a-sync onFrame durationMs=${event.durationMs}`)
    })
    T(`10c renderSync returned (type=${typeof syncInst})`)
  } catch (err) {
    const msg = err instanceof Error ? `${err.name}: ${err.message}` : String(err)
    T(`10c renderSync THREW: ${msg.slice(0, 500)}`)
  }
  // Block briefly so we can see if onFrame fires.
  await new Promise(r => setTimeout(r, 3000))
  T('10d post-renderSync wait done — exiting')
  process.exit(0)
}

const renderResult = ink.render(RenderTarget, {
  exitOnCtrlC: false,
  onFrame: (event: FrameEvent) => {
    T(`11a onFrame durationMs=${event.durationMs}`)
    onFrame?.(event)
  },
  // Open URLs in the user's default browser when a link cell is clicked.
  // The TUI's mouse tracking captures click events before Terminal.app's
  // own URL detection can fire, so without this hook clicks on `<Link>`
  // do nothing in any terminal where mouseTracking is on.
  onHyperlinkClick: url => {
    openExternalUrl(url)
  }
})
T(`11 ink.render returned (type=${typeof renderResult}, isPromise=${renderResult instanceof Promise})`)

// @hermes/ink's wrappedRender is async — chain .then/.catch so any rejection
// surfaces instead of being silently swallowed.
;(renderResult as Promise<unknown>)
  .then((inst: unknown) => {
    T(`12 render promise resolved (instance type=${typeof inst})`)
    if (inst && typeof inst === 'object' && 'waitUntilExit' in inst) {
      ;(inst as { waitUntilExit: () => Promise<void> })
        .waitUntilExit()
        .then(() => T('13 ink waitUntilExit resolved'))
        .catch(err => T(`13 ink waitUntilExit rejected: ${String(err).slice(0, 300)}`))
    }
  })
  .catch((err: unknown) => {
    const msg = err instanceof Error ? `${err.name}: ${err.message}\n${err.stack ?? ''}` : String(err)
    T(`12 render promise REJECTED: ${msg.slice(0, 800)}`)
  })

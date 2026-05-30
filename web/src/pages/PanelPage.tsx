import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { AlertCircle, MessageCirclePlus } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { useSearchParams } from "react-router-dom";

import { CanvasPanel } from "@/components/canvas/CanvasPanel";
import type { CanvasSelection } from "@/components/canvas/PreviewFrame";
import { ChatThread } from "@/components/chat/ChatThread";
import { Composer } from "@/components/chat/Composer";
import { useBelowBreakpoint } from "@/hooks/useBelowBreakpoint";
import { useCanvasPreview } from "@/hooks/useCanvasPreview";
import { useChatStream } from "@/hooks/useChatStream";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { PANEL_DEV_PORT, pickDevServerForPort } from "@/lib/vibe-ports";

const SPLIT_STORAGE_KEY = "sopify:panelChatPct";
const PANEL_PREVIEW_MODE_KEY = "sopify:panelPreviewMode";
// PR-009 — durable Panel session key so reloads rehydrate the chat
// instead of starting fresh. Single global key (Panel has one session
// at a time). Vibe Code uses project.json:session_id on disk instead —
// the per-project marker survives browser cache clears + cross-device
// access, so we don't mirror to localStorage there.
const PANEL_SESSION_STORAGE_KEY = "sopify:panelSessionId";

function readStoredPanelSession(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const v = window.localStorage.getItem(PANEL_SESSION_STORAGE_KEY);
    return v && v.trim() ? v : null;
  } catch {
    return null;
  }
}
const SPLIT_DEFAULT = 58;
// Min chat-pane share — kept low enough that the chat can collapse to a
// narrow rail (~15%) when the user wants the preview to take most of the
// width. The pane itself still has `min-w-0` so its inner content
// (composer, bubbles) wraps gracefully at that size.
const SPLIT_MIN = 15;
const SPLIT_MAX = 85;

const clampSplit = (pct: number) =>
  Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, pct));

/** Format a clicked element into an editable instruction block for the agent. */
function formatSelection(sel: CanvasSelection): string {
  const lines = [
    "Edit this element on the page:",
    `- selector: ${sel.selector || "(unknown)"}`,
    `- tag: <${sel.tag}>${sel.id ? ` id="${sel.id}"` : ""}${
      sel.classes ? ` class="${sel.classes}"` : ""
    }`,
  ];
  if (sel.text) lines.push(`- text: "${sel.text}"`);
  lines.push("", "```html", sel.html, "```", "", "Change: ");
  return lines.join("\n");
}

/**
 * PanelPage — bubble-style chat (left) + interactive canvas (right).
 *
 * Distinct from /chat (which embeds the xterm/PTY TUI): this page talks the
 * structured GatewayClient protocol directly, so it can render chat bubbles,
 * a live "Thinking…" disclosure, and inline tool calls as real components.
 *
 * The right canvas pane is a Phase-2 placeholder; it will host an <iframe>
 * preview of the website the agent builds, with click-to-select editing.
 */
export default function PanelPage() {
  const [searchParams] = useSearchParams();
  // PR-009 — resume priority is URL ?resume= > localStorage > fresh.
  // Read once on mount (not via state-setter callback) so the resume target
  // stays stable across renders; `useChatStream` only refetches when the
  // captured resumeId actually changes. URLSearchParams.get returns "" for
  // a bare `?resume=` so we coerce empty to null before falling back.
  const initialResumeId = useRef<string | null>(
    (searchParams.get("resume") || null) ?? readStoredPanelSession(),
  ).current;
  const {
    state,
    sessionId,
    sessionKey,
    turns,
    devServers,
    busy,
    error,
    send,
    interrupt,
  } = useChatStream(initialResumeId);

  // Persist whatever session_key the gateway hands us so the next reload
  // rehydrates the same conversation. Clearing happens through the New
  // chat button below; clear-on-error is intentionally NOT done — a
  // transient gateway error shouldn't lose the user's history.
  useEffect(() => {
    if (!sessionKey) return;
    try {
      window.localStorage.setItem(PANEL_SESSION_STORAGE_KEY, sessionKey);
    } catch {
      /* localStorage unavailable — ignore. */
    }
  }, [sessionKey]);

  const onNewChat = useCallback(() => {
    try {
      window.localStorage.removeItem(PANEL_SESSION_STORAGE_KEY);
    } catch {
      /* ignore */
    }
    // Strip the ?resume= query if present so the reload truly starts fresh.
    const url = new URL(window.location.href);
    url.searchParams.delete("resume");
    window.location.replace(url.toString());
  }, []);
  const canvas = useCanvasPreview(turns);
  // PR-006 — Panel right pane is locked to the fixed port. Other 517x
  // servers the gateway detects still show up in `devServers`, but the
  // Canvas only ever points its iframe at 5173. Null when 5173 isn't up.
  const detectedDevUrl =
    pickDevServerForPort(devServers, PANEL_DEV_PORT)?.url ?? null;

  // Selected-element context injected into the composer. `key` bumps per
  // selection so picking the same element twice re-injects the block.
  const [prefill, setPrefill] = useState<{ text: string; key: number }>({
    text: "",
    key: 0,
  });
  const onSelectElement = useCallback((sel: CanvasSelection) => {
    setPrefill((p) => ({ text: formatSelection(sel), key: p.key + 1 }));
  }, []);

  // PR-008 — every time Panel resolves to Live mode (Static→Live click or
  // mount-time restore), kill anything on the fixed port so the preview
  // never serves stale state from a prior session. Idempotent on the
  // backend; failure is silent so the iframe still loads if a stale
  // server happens to be the right thing anyway.
  const onPanelModeChange = useCallback((next: "static" | "live") => {
    if (next !== "live") return;
    api.killDevServerPort(PANEL_DEV_PORT).catch(() => {
      /* quiet — best-effort cleanup */
    });
  }, []);

  // ── Resizable split between chat (left) and canvas (right) ──
  // Only active at lg+ (below that the panes stack vertically and the
  // canvas is hidden). `chatPct` is the chat pane's share of the row; the
  // canvas takes the remainder. Persisted so the choice survives reloads.
  const isStacked = useBelowBreakpoint(1024);
  const splitRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);
  const [chatPct, setChatPct] = useState<number>(() => {
    if (typeof window === "undefined") return SPLIT_DEFAULT;
    const raw = Number(window.localStorage.getItem(SPLIT_STORAGE_KEY));
    return Number.isFinite(raw) && raw > 0 ? clampSplit(raw) : SPLIT_DEFAULT;
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(SPLIT_STORAGE_KEY, String(Math.round(chatPct)));
    } catch {
      // localStorage may be unavailable (private mode / blocked) — ignore.
    }
  }, [chatPct]);

  const updateFromClientX = useCallback((clientX: number) => {
    const el = splitRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0) return;
    setChatPct(clampSplit(((clientX - rect.left) / rect.width) * 100));
  }, []);

  const onDividerPointerDown = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      draggingRef.current = true;
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [],
  );
  const onDividerPointerMove = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (!draggingRef.current) return;
      updateFromClientX(e.clientX);
    },
    [updateFromClientX],
  );
  const onDividerPointerUp = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      e.currentTarget.releasePointerCapture?.(e.pointerId);
    },
    [],
  );
  const onDividerKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLDivElement>) => {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        setChatPct((p) => clampSplit(p - 2));
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        setChatPct((p) => clampSplit(p + 2));
      } else if (e.key === "Home" || e.key === "End") {
        e.preventDefault();
        setChatPct(SPLIT_DEFAULT);
      }
    },
    [],
  );
  const resetSplit = useCallback(() => setChatPct(SPLIT_DEFAULT), []);

  // Inline grow ratios drive the row split; only applied at lg+ so the
  // stacked (column) layout keeps relying on the `flex-1` class for height.
  const chatStyle = isStacked
    ? undefined
    : { flexGrow: chatPct, flexBasis: 0 };
  const canvasStyle = isStacked
    ? undefined
    : { flexGrow: 100 - chatPct, flexBasis: 0 };

  const tokenMissing =
    typeof window !== "undefined" && !window.__HERMES_SESSION_TOKEN__;
  const disabled = tokenMissing || state !== "open" || !sessionId;

  return (
    <div
      ref={splitRef}
      className="flex min-h-0 flex-1 flex-col gap-2 pb-2 normal-case lg:flex-row lg:gap-0 lg:pb-4"
    >
      {/* Left: chat */}
      <section
        style={chatStyle}
        className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-lg border border-border/60 bg-background-base/40"
      >
        <header className="flex h-11 shrink-0 items-center justify-between gap-2 border-b border-border/60 px-4">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Chat
          </span>
          <div className="flex items-center gap-2">
            {/* PR-009 — clears the durable Panel session and reloads so a
              * persisted conversation can be retired without devtools. */}
            <Button
              ghost
              size="icon"
              onClick={onNewChat}
              aria-label="Start a new Panel chat"
              title="New chat — clears the saved session"
              className="h-7 w-7"
            >
              <MessageCirclePlus className="h-3.5 w-3.5" />
            </Button>
            <Badge tone={state === "open" ? "success" : state === "error" ? "destructive" : "secondary"}>
              {state === "open" ? "live" : state}
            </Badge>
          </div>
        </header>

        {(tokenMissing || error) && (
          <div className="flex items-start gap-2 border-b border-destructive/30 bg-destructive/5 px-4 py-2 text-xs text-destructive">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="min-w-0 break-words">
              {tokenMissing
                ? "Session token unavailable. Open this page through `hermes dashboard`."
                : error}
            </span>
          </div>
        )}

        <ChatThread turns={turns} />

        <Composer
          busy={busy}
          disabled={disabled}
          onSend={send}
          onStop={interrupt}
          prefill={prefill.text}
          prefillKey={prefill.key}
        />
      </section>

      {/* Drag handle — resize chat vs. canvas (desktop only) */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize chat and preview panes"
        aria-valuemin={SPLIT_MIN}
        aria-valuemax={SPLIT_MAX}
        aria-valuenow={Math.round(chatPct)}
        tabIndex={0}
        onPointerDown={onDividerPointerDown}
        onPointerMove={onDividerPointerMove}
        onPointerUp={onDividerPointerUp}
        onKeyDown={onDividerKeyDown}
        onDoubleClick={resetSplit}
        className={cn(
          "group hidden shrink-0 cursor-col-resize touch-none items-stretch lg:flex",
          "mx-1 w-1.5 select-none",
          "focus-visible:outline-none",
        )}
        title="Drag to resize · double-click to reset"
      >
        <span
          aria-hidden
          className={cn(
            "m-auto h-10 w-1 rounded-full bg-border/70 transition-colors",
            "group-hover:bg-midground/60 group-focus-visible:bg-midground/80",
          )}
        />
      </div>

      {/* Right: canvas — live website preview */}
      <aside
        style={canvasStyle}
        className={cn(
          "hidden min-h-0 min-w-0 flex-col overflow-hidden rounded-lg",
          "border border-border/60 bg-background-base/40 lg:flex",
        )}
        aria-label="Canvas preview"
      >
        <CanvasPanel
          canvas={canvas}
          onSelectElement={onSelectElement}
          detectedDevUrl={detectedDevUrl}
          sessionId={sessionId}
          // PR-006 — first Panel load is chat-only; user explicitly clicks
          // the Live toggle to open the preview. If they did so previously
          // and resume, the persisted mode brings them back in Live.
          autoOpenLive={false}
          persistModeKey={PANEL_PREVIEW_MODE_KEY}
          // PR-008 — kill 5173 on every Static→Live transition so the
          // preview always starts from a clean port.
          onModeChange={onPanelModeChange}
        />
      </aside>
    </div>
  );
}

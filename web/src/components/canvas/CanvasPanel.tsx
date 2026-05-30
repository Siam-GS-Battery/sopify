import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import {
  ExternalLink,
  MousePointerClick,
  Play,
  RotateCw,
  Square,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { PreviewFrame, type CanvasSelection } from "@/components/canvas/PreviewFrame";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useDevServer } from "@/hooks/useDevServer";
import type { UseCanvasPreview } from "@/hooks/useCanvasPreview";

type Mode = "static" | "live";

const DEFAULT_LIVE_URL = "http://localhost:3000";

/**
 * Right-hand Canvas with two preview modes:
 *
 *   - **Static** — serves raw workspace files via /preview (same origin), with
 *     click-to-select. Right for plain HTML/CSS/JS sites.
 *   - **Live** — points the iframe directly at a running dev server (e.g. a
 *     Create-React-App / Vite `npm run dev` on http://localhost:3000). This is
 *     how React/build-step apps render: the dev server handles bundling + HMR.
 *     It's cross-origin, so Select mode (which needs the injected inspector)
 *     is unavailable here.
 */
export function CanvasPanel({
  canvas,
  onSelectElement,
  detectedDevUrl,
  sessionId,
  autoOpenLive = true,
  persistModeKey,
}: {
  canvas: UseCanvasPreview;
  onSelectElement: (sel: CanvasSelection) => void;
  /** URL of the active chat session's dev server, sourced from the
   * gateway's `dev_server.detected` event stream. When set, automatically
   * switches the canvas to Live mode and seeds the URL field. Null/empty
   * means the session has no known dev server (agent hasn't started one). */
  detectedDevUrl?: string | null;
  /** Current chat session ID — the dev-server manager is scoped per session
   * so switching sessions keeps the prior server running (we don't stop it
   * unless its port collides with the new session's). Start/Stop buttons
   * are disabled while this is null. */
  sessionId: string | null;
  /** When false, suppress the auto-flip to Live mode on first dev URL
   * detection. The Panel uses this (per spec/VIBE_CODE_PANEL_SPEC.md §4 —
   * "Panel preview is NOT auto-opened") so the user explicitly clicks
   * Live to see localhost:5173. Defaults to true for Vibe Code surfaces. */
  autoOpenLive?: boolean;
  /** localStorage key for persisting the Static/Live mode choice. When
   * set, the panel restores the last selected mode on mount. Used by
   * Panel so a resumed session with Live mode previously open re-enters
   * Live without waiting for `detectedDevUrl`. */
  persistModeKey?: string;
}) {
  const { path, setPath, version, reload, hasPreview } = canvas;
  const [mode, setMode] = useState<Mode>(() => {
    if (persistModeKey && typeof window !== "undefined") {
      const stored = window.localStorage.getItem(persistModeKey);
      if (stored === "live" || stored === "static") return stored;
    }
    return "static";
  });
  // Persist mode whenever the user (or auto-switch) changes it.
  useEffect(() => {
    if (!persistModeKey || typeof window === "undefined") return;
    try {
      window.localStorage.setItem(persistModeKey, mode);
    } catch {
      /* localStorage unavailable — ignore. */
    }
  }, [mode, persistModeKey]);
  const [draft, setDraft] = useState(path);
  const [liveUrl, setLiveUrl] = useState(DEFAULT_LIVE_URL);
  const [liveDraft, setLiveDraft] = useState(DEFAULT_LIVE_URL);
  const [inspect, setInspect] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const focused = useRef(false);
  const dev = useDevServer(sessionId);

  // Adopt the URL the dev server prints once it's up. Session-scoped
  // detection (from the chat agent's tool output) wins over the
  // /api/preview-server/status poll because it's per-session, not global.
  useEffect(() => {
    const url = detectedDevUrl || dev.url;
    if (!url) return;
    setLiveUrl(url);
    setLiveDraft(url);
  }, [detectedDevUrl, dev.url]);

  // Auto-switch to Live mode the first time a dev server URL is detected
  // for this session, so the user doesn't have to flip the toggle manually.
  // Suppressed on the Panel surface (autoOpenLive=false) per
  // spec/VIBE_CODE_PANEL_SPEC.md §4 — the user must explicitly open Live.
  const switchedToLiveRef = useRef(false);
  useEffect(() => {
    if (!autoOpenLive) return;
    if (detectedDevUrl && !switchedToLiveRef.current) {
      switchedToLiveRef.current = true;
      setMode("live");
    }
  }, [detectedDevUrl, autoOpenLive]);

  // Clicking an element completes one selection — drop out of Select mode so
  // the user can immediately interact with the page (and the composer) again.
  const handleSelect = (sel: CanvasSelection) => {
    setInspect(false);
    onSelectElement(sel);
  };

  // Keep the static entry field synced when detection seeds a new entry, but
  // don't clobber what the user is actively typing.
  useEffect(() => {
    if (!focused.current) setDraft(path);
  }, [path]);

  const isLive = mode === "live";
  const showPreview = isLive ? liveUrl.trim().length > 0 : hasPreview;
  const src = isLive
    ? liveUrl.trim()
    : hasPreview
      ? api.previewUrl(path, version, true)
      : "";
  const openHref = isLive
    ? liveUrl.trim()
    : hasPreview
      ? api.previewUrl(path, version)
      : undefined;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border/60 px-3">
        {/* Static / Live segmented toggle */}
        <div className="flex shrink-0 overflow-hidden rounded border border-border text-[0.7rem]">
          {(["static", "live"] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => {
                setMode(m);
                if (m === "live") setInspect(false);
              }}
              className={cn(
                "px-2 py-1 font-medium uppercase tracking-wide transition-colors",
                mode === m
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-foreground/5",
              )}
            >
              {m}
            </button>
          ))}
        </div>

        {isLive ? (
          <input
            value={liveDraft}
            onChange={(e) => setLiveDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && setLiveUrl(liveDraft.trim())}
            onBlur={() => setLiveUrl(liveDraft.trim())}
            placeholder={DEFAULT_LIVE_URL}
            className={cn(
              "min-w-0 flex-1 rounded border border-border bg-background px-2 py-1",
              "font-mono text-xs text-foreground placeholder:text-muted-foreground",
              "focus:outline-none focus:ring-1 focus:ring-primary/50",
            )}
          />
        ) : (
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onFocus={() => (focused.current = true)}
            onKeyDown={(e) => e.key === "Enter" && setPath(draft.trim())}
            onBlur={() => {
              focused.current = false;
              setPath(draft.trim());
            }}
            placeholder="index.html"
            className={cn(
              "min-w-0 flex-1 rounded border border-border bg-background px-2 py-1",
              "font-mono text-xs text-foreground placeholder:text-muted-foreground",
              "focus:outline-none focus:ring-1 focus:ring-primary/50",
            )}
          />
        )}

        {!isLive && (
          <Button
            ghost={!inspect}
            size="icon"
            onClick={() => setInspect((v) => !v)}
            disabled={!hasPreview}
            aria-pressed={inspect}
            aria-label="Select an element to edit"
            title="Select an element to edit"
            className={cn("h-7 w-7 shrink-0", inspect && "text-primary")}
          >
            <MousePointerClick className="h-3.5 w-3.5" />
          </Button>
        )}

        {isLive &&
          (dev.running ? (
            <Button
              ghost
              size="icon"
              onClick={dev.stop}
              aria-label="Stop dev server"
              title="Stop dev server"
              className="h-7 w-7 shrink-0 text-destructive"
            >
              <Square className="h-3.5 w-3.5" />
            </Button>
          ) : (
            <Button
              ghost
              size="icon"
              onClick={() => {
                setShowLogs(true);
                dev.start("npm run dev", "");
              }}
              disabled={dev.pending || !sessionId}
              aria-label="Start dev server (npm run dev)"
              title="Start dev server (npm run dev)"
              className="h-7 w-7 shrink-0 text-primary"
            >
              {dev.pending ? (
                <Spinner className="text-[0.875rem]" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
            </Button>
          ))}
        <Button
          ghost
          size="icon"
          onClick={reload}
          disabled={!showPreview}
          aria-label="Reload preview"
          className="h-7 w-7 shrink-0"
        >
          <RotateCw className="h-3.5 w-3.5" />
        </Button>
        <a
          href={openHref}
          target="_blank"
          rel="noreferrer"
          aria-label="Open preview in new tab"
          className={cn(
            "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-muted-foreground hover:text-foreground",
            !showPreview && "pointer-events-none opacity-40",
          )}
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </header>

      {inspect && !isLive && (
        <div className="shrink-0 border-b border-primary/30 bg-primary/10 px-3 py-1 text-[0.7rem] text-primary">
          Select mode — click any element on the page to edit it.
        </div>
      )}

      {isLive && dev.error && (
        <div className="shrink-0 border-b border-destructive/30 bg-destructive/5 px-3 py-1 text-[0.7rem] text-destructive">
          {dev.error}
        </div>
      )}

      {isLive && (dev.pending || dev.running) && (
        <div className="shrink-0 border-b border-border/60">
          <button
            type="button"
            onClick={() => setShowLogs((v) => !v)}
            className="flex w-full items-center justify-between px-3 py-1 text-[0.7rem] text-muted-foreground hover:bg-foreground/5"
          >
            <span className="inline-flex items-center gap-1.5">
              {dev.pending && <Spinner className="text-[0.7rem]" />}
              {dev.running && !dev.pending && (
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-success" />
              )}
              {dev.pending
                ? "Starting dev server…"
                : `dev server running${dev.url ? ` — ${dev.url}` : ""}`}
            </span>
            <span className="underline">{showLogs ? "hide logs" : "logs"}</span>
          </button>
          {showLogs && dev.logs.length > 0 && (
            <pre className="max-h-40 overflow-auto border-t border-border/60 bg-black/90 px-3 py-2 font-mono text-[0.65rem] leading-relaxed text-white/80">
              {dev.logs.join("\n")}
            </pre>
          )}
        </div>
      )}

      <div className="min-h-0 flex-1 bg-white">
        {showPreview ? (
          <PreviewFrame
            src={src}
            reloadKey={version}
            inspect={inspect && !isLive}
            onSelect={handleSelect}
            sameOrigin={isLive}
          />
        ) : isLive ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-sm text-muted-foreground">
            <p>
              Press <Play className="inline h-3.5 w-3.5 align-text-bottom text-primary" /> to
              start the dev server (<code className="mx-1">npm run dev</code>),
              or enter a URL above if it's already running.
            </p>
            <p className="text-xs">
              Dependencies must be installed first
              (<code className="mx-1">npm run install:all</code>).
            </p>
          </div>
        ) : (
          <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
            The website preview will render here once Sopify writes frontend
            code — or type an entry file (e.g. <code className="mx-1">index.html</code>) above.
            For a React/build app, switch to <strong className="mx-1">Live</strong> mode.
          </div>
        )}
      </div>
    </div>
  );
}

import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

/** Element descriptor posted by the injected inspector on click. */
export interface CanvasSelection {
  selector: string;
  tag: string;
  id: string;
  classes: string;
  text: string;
  html: string;
}

/**
 * Sandboxed iframe for the Canvas. Takes a fully-formed `src` so the same
 * component serves both modes:
 *
 *   - Static: a /preview URL (same origin) with the click-to-select inspector
 *     injected by the backend when `_inspect=1`.
 *   - Live: a dev-server origin (e.g. http://localhost:3000) pointed at
 *     directly — handles HTTP + HMR WebSocket natively. It's cross-origin, so
 *     the inspector bridge stays dormant (the message guard never matches a
 *     foreign origin); Select mode is disabled by the caller in this mode.
 *
 * Sandbox tokens depend on the mode (`sameOrigin`):
 *   - Static (false): the content is served from the *dashboard's* origin, so
 *     we omit `allow-same-origin` to force an opaque origin — agent-generated
 *     scripts can't reach the dashboard's storage. postMessage still crosses
 *     the opaque origin for the inspector bridge.
 *   - Live (true): the content is a *different* origin (the dev server), so
 *     same-origin policy already isolates it from the dashboard. We grant
 *     `allow-same-origin` so the app can use its own origin — localStorage,
 *     history, requests to its own API — which real React apps need to boot.
 */
export function PreviewFrame({
  src,
  reloadKey,
  inspect,
  onSelect,
  sameOrigin = false,
}: {
  src: string;
  reloadKey: number;
  inspect: boolean;
  onSelect: (sel: CanvasSelection) => void;
  sameOrigin?: boolean;
}) {
  const frameRef = useRef<HTMLIFrameElement | null>(null);

  const postInspect = (enabled: boolean) => {
    frameRef.current?.contentWindow?.postMessage(
      { source: "sopify-canvas-host", type: "set-inspect", enabled },
      "*",
    );
  };

  // Receive selection + ready handshake from the injected inspector.
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      const d = e.data;
      if (!d || d.source !== "sopify-canvas") return;
      if (d.type === "ready") {
        postInspect(inspect);
      } else if (d.type === "select" && d.payload) {
        onSelect(d.payload as CanvasSelection);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [inspect, onSelect]);

  // Push mode changes to the (already-loaded) inspector.
  useEffect(() => {
    postInspect(inspect);
  }, [inspect]);

  return (
    <iframe
      ref={frameRef}
      // Remount on reload so the browser refetches rather than serving from
      // the bfcache. reloadKey changes on every reload / write.
      key={`${src}::${reloadKey}`}
      src={src}
      title="Website preview"
      className="h-full w-full border-0 bg-white"
      sandbox={cn(
        "allow-scripts allow-forms allow-popups allow-modals",
        sameOrigin && "allow-same-origin",
      )}
    />
  );
}

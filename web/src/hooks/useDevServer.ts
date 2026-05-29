/**
 * useDevServer — drives the backend preview dev-server manager so the Panel's
 * Live mode can start `npm run dev` without the user opening a terminal.
 *
 * Lifecycle: start() POSTs the command, then we poll /status until the server
 * prints a localhost URL (or dies). The detected URL is surfaced so the
 * Canvas can point its iframe at it; logs are exposed so install/build
 * failures are visible rather than a silent blank preview.
 *
 * Servers are tracked per chat session on the backend — switching sessions
 * keeps the previous server alive. Pass the active sessionId so the hook
 * polls/starts/stops the right one. While sessionId is null, the hook is
 * idle (no polling, start/stop are no-ops).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";

export interface UseDevServer {
  running: boolean;
  url: string | null;
  logs: string[];
  pending: boolean;
  error: string | null;
  start: (command?: string, cwd?: string) => void;
  stop: () => void;
}

const POLL_MS = 1500;

export function useDevServer(sessionId: string | null): UseDevServer {
  const [running, setRunning] = useState(false);
  const [url, setUrl] = useState<string | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const poll = useCallback(async () => {
    if (!sessionId) return;
    try {
      const s = await api.previewServerStatus(sessionId);
      setRunning(s.running);
      setUrl(s.url);
      setLogs(s.logs ?? []);
      // Keep polling while running but no URL yet (server still booting).
      if (s.running && !s.url) {
        timerRef.current = setTimeout(poll, POLL_MS);
      } else {
        setPending(false);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPending(false);
    }
  }, [sessionId]);

  // Reflect whatever server (if any) is registered for this session — and
  // re-run when the session changes so we follow the user's active chat.
  useEffect(() => {
    // Clear stale view of the previous session before the new one's status
    // arrives.  Without this, the panel briefly shows the previous session's
    // URL/logs while the first poll is in flight.
    setRunning(false);
    setUrl(null);
    setLogs([]);
    setError(null);
    setPending(false);
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!sessionId) return;
    void poll();
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [sessionId, poll]);

  const start = useCallback(
    (command?: string, cwd?: string) => {
      if (!sessionId) return;
      setError(null);
      setPending(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      api
        .startPreviewServer(sessionId, command, cwd)
        .then(() => poll())
        .catch((e: Error) => {
          setError(e.message);
          setPending(false);
        });
    },
    [sessionId, poll],
  );

  const stop = useCallback(() => {
    if (!sessionId) return;
    setError(null);
    if (timerRef.current) clearTimeout(timerRef.current);
    api
      .stopPreviewServer(sessionId)
      .then(() => {
        setRunning(false);
        setUrl(null);
      })
      .catch((e: Error) => setError(e.message));
  }, [sessionId]);

  return { running, url, logs, pending, error, start, stop };
}

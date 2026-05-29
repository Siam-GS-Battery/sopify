/**
 * useChatStream — turns the gateway's JSON-RPC event stream into a flat,
 * render-ready transcript for the bubble-style Panel UI.
 *
 * Unlike ChatPage (xterm + PTY), this hook drives chat entirely through the
 * structured `GatewayClient` protocol:
 *
 *   - connect() + session.create  → obtain a session id
 *   - prompt.submit               → send a user turn
 *   - message.start/delta/complete → assistant answer text (streamed)
 *   - thinking.delta / reasoning.delta → the "Thinking…" stream
 *   - tool.start/progress/complete → inline tool-call rows (reusing ToolEntry)
 *   - session.interrupt           → stop a running turn
 *
 * Transcript model: an ordered list of turns. A user turn is a single bubble.
 * An assistant turn is one block that accumulates thinking text, any tool
 * calls, and the answer text for that turn — rendered in a stable sub-order
 * (thinking → tools → answer) so we never depend on the fragile interleaving
 * of deltas vs tool events on the wire.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { GatewayClient, type ConnectionState } from "@/lib/gatewayClient";
import type { ToolEntry } from "@/components/ToolCall";

export interface UserTurn {
  kind: "user";
  id: string;
  text: string;
}

export interface AssistantTurn {
  kind: "assistant";
  id: string;
  /** Streamed reasoning/thinking text for this turn (may be empty). */
  thinking: string;
  /** True while thinking is actively streaming and the answer hasn't started. */
  thinkingActive: boolean;
  /** Tool calls emitted during this turn, in arrival order. */
  tools: ToolEntry[];
  /** Final answer markdown (accumulates from message.delta). */
  text: string;
  /** True until message.complete (or interrupt/error). */
  streaming: boolean;
  status: "streaming" | "complete" | "interrupted" | "error";
  error?: string;
}

export type Turn = UserTurn | AssistantTurn;

/** A dev server detected for this session — driven by the gateway's
 * `dev_server.detected` event. The preview iframe in Vibe Code Building
 * and /panel reads `devServers[0]?.url` directly. */
export interface DevServerHint {
  port: number;
  url: string;
  status: string;
  detectedAt: number;
}

export interface UseChatStream {
  state: ConnectionState;
  /** In-memory gateway handle. Used for prompt.submit / session.interrupt. */
  sessionId: string | null;
  /**
   * Durable DB session key. Persist this — not ``sessionId`` — for resume
   * across reloads. The gateway hands it out alongside ``session_id`` on
   * both session.create and session.resume.
   */
  sessionKey: string | null;
  turns: Turn[];
  /** Dev servers the agent has started in this session (deduped by port,
   * most-recently-seen first). Empty when no http://localhost:<port> URL
   * has been observed in any tool output. */
  devServers: DevServerHint[];
  /** True while the current assistant turn is still running. */
  busy: boolean;
  error: string | null;
  send: (text: string) => void;
  interrupt: () => void;
}

let turnSeq = 0;
const nextId = (prefix: string) => `${prefix}-${++turnSeq}-${Date.now()}`;

/** One entry of the `messages` list returned by session.resume/history. */
interface ResumeMessage {
  role: string;
  text?: string;
  name?: string;
  context?: string;
}

/**
 * Rebuild the bubble transcript from a resumed session's flat message list.
 * Tool messages attach to the preceding assistant turn (or seed a fresh one);
 * historical tools carry no timestamps (startedAt 0), which ToolCall renders
 * without an elapsed badge.
 */
function messagesToTurns(msgs: ResumeMessage[]): Turn[] {
  const turns: Turn[] = [];
  const freshAssistant = (): AssistantTurn => ({
    kind: "assistant",
    id: nextId("a"),
    thinking: "",
    thinkingActive: false,
    tools: [],
    text: "",
    streaming: false,
    status: "complete",
  });

  for (const m of msgs) {
    if (m.role === "user") {
      turns.push({ kind: "user", id: nextId("u"), text: m.text ?? "" });
    } else if (m.role === "assistant" || m.role === "system") {
      const a = freshAssistant();
      a.text = m.text ?? "";
      turns.push(a);
    } else if (m.role === "tool") {
      let last = turns[turns.length - 1];
      if (!last || last.kind !== "assistant") {
        last = freshAssistant();
        turns.push(last);
      }
      const a = last as AssistantTurn;
      a.tools.push({
        kind: "tool",
        id: `tool-resume-${turns.length}-${a.tools.length}`,
        tool_id: `resume-${turns.length}-${a.tools.length}`,
        name: m.name ?? "tool",
        context: m.context,
        status: "done",
        startedAt: 0,
      });
    }
  }
  return turns;
}

export function useChatStream(resumeId?: string | null): UseChatStream {
  const gwRef = useRef<GatewayClient | null>(null);
  if (gwRef.current === null) gwRef.current = new GatewayClient();
  const gw = gwRef.current;

  const [state, setState] = useState<ConnectionState>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionKey, setSessionKey] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [devServers, setDevServers] = useState<DevServerHint[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Latest session id available to event handlers without re-subscribing.
  const sidRef = useRef<string | null>(null);
  sidRef.current = sessionId;

  /**
   * Append-or-update the open assistant turn. If the last turn isn't an
   * in-flight assistant turn, create one. The mutator receives a draft copy.
   */
  const upsertAssistant = useCallback(
    (mutate: (draft: AssistantTurn) => void) => {
      setTurns((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.kind === "assistant" && last.streaming) {
          const draft: AssistantTurn = {
            ...last,
            tools: [...last.tools],
          };
          mutate(draft);
          return [...prev.slice(0, -1), draft];
        }
        const draft: AssistantTurn = {
          kind: "assistant",
          id: nextId("a"),
          thinking: "",
          thinkingActive: false,
          tools: [],
          text: "",
          streaming: true,
          status: "streaming",
        };
        mutate(draft);
        return [...prev, draft];
      });
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    // Reset transcript when the resume target changes (or on first mount) so
    // navigating between sessions doesn't bleed turns across.
    setTurns([]);
    setSessionId(null);
    setSessionKey(null);
    setDevServers([]);
    setBusy(false);
    setError(null);
    const offState = gw.onState(setState);

    const offStart = gw.on("message.start", () => {
      upsertAssistant((d) => {
        d.thinkingActive = false;
      });
    });

    const offDelta = gw.on<{ text?: string }>("message.delta", (ev) => {
      const t = ev.payload?.text;
      if (!t) return;
      upsertAssistant((d) => {
        d.thinkingActive = false;
        d.text += t;
      });
    });

    const offComplete = gw.on<{
      text?: string;
      status?: string;
      warning?: string;
    }>("message.complete", (ev) => {
      const p = ev.payload ?? {};
      upsertAssistant((d) => {
        // message.complete carries the authoritative full text; prefer it
        // over the accumulated deltas (covers dropped frames).
        if (typeof p.text === "string" && p.text.length >= d.text.length) {
          d.text = p.text;
        }
        d.streaming = false;
        d.thinkingActive = false;
        d.status =
          p.status === "interrupted"
            ? "interrupted"
            : p.status === "error"
              ? "error"
              : "complete";
        if (p.warning) d.error = p.warning;
      });
      setBusy(false);
    });

    const onThinking = (ev: { payload?: { text?: string } }) => {
      const t = ev.payload?.text;
      if (!t) return;
      upsertAssistant((d) => {
        if (d.text.length === 0) d.thinkingActive = true;
        d.thinking += t;
      });
    };
    const offThinking = gw.on<{ text?: string }>("thinking.delta", onThinking);
    const offReasoning = gw.on<{ text?: string }>("reasoning.delta", onThinking);

    const offToolStart = gw.on<{
      tool_id?: string;
      name?: string;
      context?: string;
    }>("tool.start", (ev) => {
      const p = ev.payload ?? {};
      if (!p.tool_id) return;
      upsertAssistant((d) => {
        d.thinkingActive = false;
        d.tools.push({
          kind: "tool",
          id: `tool-${p.tool_id}-${d.tools.length}`,
          tool_id: p.tool_id!,
          name: p.name ?? "tool",
          context: p.context,
          status: "running",
          startedAt: Date.now(),
        });
      });
    });

    const offToolProgress = gw.on<{ name?: string; preview?: string }>(
      "tool.progress",
      (ev) => {
        const p = ev.payload ?? {};
        if (!p.name || !p.preview) return;
        upsertAssistant((d) => {
          for (const tl of d.tools) {
            if (tl.status === "running" && tl.name === p.name) {
              tl.preview = p.preview;
            }
          }
        });
      },
    );

    const offToolComplete = gw.on<{
      tool_id?: string;
      summary?: string;
      error?: string;
      inline_diff?: string;
    }>("tool.complete", (ev) => {
      const p = ev.payload ?? {};
      if (!p.tool_id) return;
      upsertAssistant((d) => {
        d.tools = d.tools.map((tl) =>
          tl.tool_id === p.tool_id
            ? {
                ...tl,
                status: p.error ? "error" : "done",
                summary: p.summary,
                error: p.error,
                inline_diff: p.inline_diff,
                completedAt: Date.now(),
              }
            : tl,
        );
      });
    });

    const offError = gw.on<{ message?: string }>("error", (ev) => {
      const message = ev.payload?.message;
      if (message) setError(message);
      // An error ends the turn — release the composer.
      setBusy(false);
      setTurns((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.kind === "assistant" && last.streaming) {
          return [
            ...prev.slice(0, -1),
            { ...last, streaming: false, status: "error", error: message },
          ];
        }
        return prev;
      });
    });

    // dev_server.detected — emitted when the gateway parses a localhost URL
    // out of a tool's stdout, or when set_active_session revives a paused
    // server. status="running" adds/refreshes the entry; status="failed"
    // (and anything else) removes it so the iframe falls back to empty.
    // The Vibe Code Building iframe + /panel canvas read devServers[0].
    const offDevServer = gw.on<{
      port?: number;
      url?: string;
      status?: string;
    }>("dev_server.detected", (ev) => {
      const port = ev.payload?.port;
      const url = ev.payload?.url;
      if (typeof port !== "number" || typeof url !== "string") return;
      const status = ev.payload?.status ?? "running";
      setDevServers((prev) => {
        const filtered = prev.filter((d) => d.port !== port);
        if (status !== "running") return filtered;
        return [
          { port, url, status, detectedAt: Date.now() },
          ...filtered,
        ];
      });
    });

    gw.connect()
      .then(() => {
        if (cancelled) return;
        if (resumeId) {
          // Resume adopts a fresh sid and replays the stored transcript.
          return gw
            .request<{
              session_id: string;
              session_key?: string;
              messages?: ResumeMessage[];
            }>("session.resume", { session_id: resumeId })
            .then((res) => {
              if (cancelled || !res?.session_id) return;
              setSessionId(res.session_id);
              // Older gateways don't return session_key — fall back to the
              // resume target, which equals the DB key by definition.
              setSessionKey(res.session_key ?? resumeId);
              if (Array.isArray(res.messages)) {
                setTurns(messagesToTurns(res.messages));
              }
            });
        }
        return gw
          .request<{ session_id: string; session_key?: string }>(
            "session.create",
            {},
          )
          .then((created) => {
            if (cancelled || !created?.session_id) return;
            setSessionId(created.session_id);
            // Older gateways omit session_key — fall back to the gateway
            // sid so callers always have *something* to persist, even if
            // resume against it would fail on those older builds.
            setSessionKey(created.session_key ?? created.session_id);
          });
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });

    return () => {
      cancelled = true;
      offState();
      offStart();
      offDelta();
      offComplete();
      offThinking();
      offReasoning();
      offToolStart();
      offToolProgress();
      offToolComplete();
      offError();
      offDevServer();
      gw.close();
    };
  }, [gw, upsertAssistant, resumeId]);

  const send = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      const sid = sidRef.current;
      if (!trimmed || !sid || busy) return;

      setError(null);
      setBusy(true);
      setTurns((prev) => [
        ...prev,
        { kind: "user", id: nextId("u"), text: trimmed },
      ]);

      gw.request("prompt.submit", { session_id: sid, text: trimmed }).catch(
        (e: Error) => {
          setError(e.message);
          setBusy(false);
        },
      );
    },
    [gw, busy],
  );

  const interrupt = useCallback(() => {
    const sid = sidRef.current;
    if (!sid) return;
    void gw.request("session.interrupt", { session_id: sid }).catch(() => {
      /* best-effort */
    });
  }, [gw]);

  return useMemo(
    () => ({
      state,
      sessionId,
      sessionKey,
      turns,
      devServers,
      busy,
      error,
      send,
      interrupt,
    }),
    [
      state,
      sessionId,
      sessionKey,
      turns,
      devServers,
      busy,
      error,
      send,
      interrupt,
    ],
  );
}

import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  Check,
  Loader2,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Typography } from "@/components/NouiTypography";
import { ChatThread } from "@/components/chat/ChatThread";
import { Composer } from "@/components/chat/Composer";
import {
  VIBE_STEPS,
  VerticalStepper,
  type VibeStepKey,
} from "@/components/vibe/VerticalStepper";
import { useBelowBreakpoint } from "@/hooks/useBelowBreakpoint";
import { useChatStream } from "@/hooks/useChatStream";
import { api } from "@/lib/api";
import type {
  VibePhase,
  VibeProjectGetResponse,
  VibeProjectMarker,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Project work view: phase pane on the left, vertical stepper on the right.
 *
 * Backend has 7 phases (brainstorm/requirements/planning/development/
 * improvement/security/approve) but the UI surfaces only 3 of them — the
 * other four are either skipped on accept or hidden as silent end states.
 * See `phaseToStepKey` for the mapping.
 */

interface Props {
  data: VibeProjectGetResponse;
  onBack: () => void;
  onUpdated: (updated: VibeProjectMarker) => void;
  onRefresh: () => void;
}

function phaseToStepKey(phase: VibePhase): VibeStepKey {
  // brainstorm + the now-hidden requirements both stay on "Brainstorm"
  if (phase === "brainstorm" || phase === "requirements") return "brainstorm";
  if (phase === "planning") return "planning";
  // development is the final visible step; improvement/security/approve from
  // legacy projects also map here so the rail doesn't claim more progress
  // than the simplified UI exposes.
  return "building";
}

const PROJECT_DONE_KEYS: VibeStepKey[] = ["name", "theme", "addons"];

export function ProjectView({ data, onBack, onUpdated, onRefresh }: Props) {
  const { project, requirements_md, planning_md } = data;

  const stepperKey = phaseToStepKey(project.phase);
  const doneKeys = useMemo<VibeStepKey[]>(() => {
    const done = [...PROJECT_DONE_KEYS];
    // Treat every step before the current as done.
    const order: VibeStepKey[] = ["brainstorm", "planning", "building"];
    for (const k of order) {
      if (k === stepperKey) break;
      done.push(k);
    }
    return done;
  }, [stepperKey]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 pb-4 normal-case lg:flex-row lg:gap-6">
      <div className="flex min-w-0 min-h-0 flex-1 flex-col gap-3">
        <ProjectHeader project={project} onBack={onBack} />

        <div className="flex min-h-0 flex-1 flex-col">
          {(project.phase === "brainstorm" ||
            project.phase === "requirements") && (
            <BrainstormPane
              project={project}
              initialRequirements={requirements_md ?? ""}
              onUpdated={onUpdated}
              onRefresh={onRefresh}
            />
          )}
          {project.phase === "planning" && (
            <PlanningPane
              project={project}
              existing={planning_md ?? ""}
              requirements={requirements_md ?? ""}
              onUpdated={onUpdated}
              onRefresh={onRefresh}
            />
          )}
          {(project.phase === "development" ||
            project.phase === "improvement" ||
            project.phase === "security" ||
            project.phase === "approve") && (
            <BuildingPane project={project} />
          )}
        </div>
      </div>

      <aside
        aria-label="Project progress"
        className="hidden shrink-0 lg:block lg:w-[240px] xl:w-[260px]"
      >
        <div className="sticky top-4 rounded-lg border border-border/60 bg-background-base/40 px-5 py-5">
          <VerticalStepper
            steps={VIBE_STEPS}
            currentKey={stepperKey}
            doneKeys={doneKeys}
          />
        </div>
      </aside>
    </div>
  );
}

function ProjectHeader({
  project,
  onBack,
}: {
  project: VibeProjectMarker;
  onBack: () => void;
}) {
  return (
    <header className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <Button ghost size="icon" onClick={onBack} aria-label="Back to projects">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <Typography
            mondwest
            className="text-[1rem] font-bold uppercase tracking-[0.05em] text-midground"
          >
            {project.name}
          </Typography>
          <p className="font-mono text-[0.7rem] text-muted-foreground/70">
            {project.mode}
            {project.add_ons.length > 0 ? ` · ${project.add_ons.join(", ")}` : ""}
          </p>
        </div>
      </div>
      <Badge tone="secondary">{project.phase}</Badge>
    </header>
  );
}

// ── Chat panel ───────────────────────────────────────────────────────────────

function ChatPanel({
  project,
  kickoff,
  header,
  onDevServersChange,
}: {
  project: VibeProjectMarker;
  kickoff?: string;
  header?: string;
  /** Called with the latest devServers list each time the chat hook
   * updates. Parent uses it to drive the Live preview iframe. */
  onDevServersChange?: (servers: { port: number; url: string }[]) => void;
}) {
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
  } = useChatStream(project.session_id ?? null);
  const kickoffSentRef = useRef(false);

  // Bubble devServers up to whichever pane wraps us (BuildingPane reads it
  // to set iframe src). Re-emit on every change so the parent stays synced.
  useEffect(() => {
    onDevServersChange?.(devServers);
  }, [devServers, onDevServersChange]);

  // Persist the DB session key (not the gateway sid) so resume after a
  // reload actually rehydrates the conversation. The gateway sid is
  // in-memory only; passing it to session.resume returns 4007 "not found".
  useEffect(() => {
    if (sessionKey && project.session_id !== sessionKey) {
      api
        .patchVibeProject(project.name, { session_id: sessionKey })
        .catch(() => {
          // Non-fatal: chat still works, just won't resume after reload.
        });
    }
  }, [sessionKey, project.name, project.session_id]);

  useEffect(() => {
    if (!kickoff || kickoffSentRef.current) return;
    if (state !== "open" || !sessionId) return;
    if (turns.length > 0) {
      kickoffSentRef.current = true;
      return;
    }
    kickoffSentRef.current = true;
    send(kickoff);
  }, [kickoff, state, sessionId, turns.length, send]);

  const tokenMissing =
    typeof window !== "undefined" && !window.__HERMES_SESSION_TOKEN__;
  const disabled = tokenMissing || state !== "open" || !sessionId;

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-lg border border-border/60 bg-background-base/40">
      <header className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-border/60 px-4">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {header ?? "Chat"}
        </span>
        <Badge
          tone={
            state === "open"
              ? "success"
              : state === "error"
                ? "destructive"
                : "secondary"
          }
        >
          {state === "open" ? "live" : state}
        </Badge>
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
      />
    </section>
  );
}

// ── Brainstorm ───────────────────────────────────────────────────────────────

function BrainstormPane({
  project,
  initialRequirements,
  onUpdated,
  onRefresh,
}: {
  project: VibeProjectMarker;
  initialRequirements: string;
  onUpdated: (m: VibeProjectMarker) => void;
  onRefresh: () => void;
}) {
  const [systemPrompt, setSystemPrompt] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getVibeSystemPrompt(project.name)
      .then((r) => {
        if (!cancelled) setSystemPrompt(r.prompt);
      })
      .catch(() => {
        if (!cancelled) setSystemPrompt("");
      });
    return () => {
      cancelled = true;
    };
  }, [project.name]);

  return (
    <SplitWithSide
      main={
        <ChatPanel
          project={project}
          kickoff={systemPrompt ?? undefined}
          header="Brainstorm"
        />
      }
      side={
        <RequirementsPreview
          project={project}
          initial={initialRequirements}
          onApprove={async () => {
            // Skip the legacy "requirements" review phase — jump straight
            // to Planning. REQUIREMENTS.md is whatever the agent has
            // written into the project folder by now.
            const res = await api.patchVibeProject(project.name, {
              phase: "planning",
            });
            onUpdated(res.project);
            onRefresh();
          }}
        />
      }
    />
  );
}

function RequirementsPreview({
  project,
  initial,
  onApprove,
}: {
  project: VibeProjectMarker;
  initial: string;
  onApprove: () => Promise<void>;
}) {
  const [content, setContent] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Poll the project endpoint so updates the agent writes to
  // REQUIREMENTS.md surface here without a manual reload.
  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      api
        .getVibeProject(project.name)
        .then((r) => {
          if (!cancelled) setContent(r.requirements_md ?? "");
        })
        .catch(() => {
          // Quiet — keep prior content if the fetch fails.
        });
    };
    const id = window.setInterval(tick, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [project.name]);

  const click = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      await onApprove();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [onApprove]);

  return (
    <>
      <header className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-border/60 px-4">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          REQUIREMENTS.md
        </span>
        <Badge tone={content ? "success" : "secondary"}>
          {content ? "drafted" : "awaiting agent"}
        </Badge>
      </header>
      <pre className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap break-words px-4 py-3 font-mono text-xs text-midground">
        {content || "(empty — the agent will write here as you brainstorm.)"}
      </pre>
      <div className="flex flex-col gap-2 border-t border-border/60 px-4 py-3">
        {err && (
          <div className="flex items-start gap-2 text-xs text-destructive">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="break-words">{err}</span>
          </div>
        )}
        <Button onClick={click} disabled={!content.trim() || busy} className="gap-2">
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Check className="h-4 w-4" />
          )}
          <span>Approve plan → Planning</span>
        </Button>
        <p className="text-[0.7rem] text-muted-foreground/60">
          When REQUIREMENTS.md captures the scope, approve to move on.
        </p>
      </div>
    </>
  );
}

// ── Planning ─────────────────────────────────────────────────────────────────

/**
 * Planning is read-only by design: the user is reviewing the plan the agent
 * just wrote, not co-authoring it. The chat from Brainstorm is hidden — but
 * we still mount `useChatStream` (invisibly) on the same session so we can
 * kick the agent to (re)generate PLANNING.md without spinning up a second
 * session.
 */
const PLANNING_KICKOFF_PROMPT =
  "REQUIREMENTS.md is approved. Now write PLANNING.md in the project folder. " +
  "Cover: file structure, components to build (frontend + backend), data model, " +
  "implementation order, key dependencies. Keep it tight — the user will read and " +
  "approve before you start coding, so it must be skim-able. Follow the sopify-sdlc " +
  "skill standards. Do not start coding yet; wait for approval.";

function PlanningPane({
  project,
  existing,
  onUpdated,
  onRefresh,
}: {
  project: VibeProjectMarker;
  existing: string;
  requirements: string;
  onUpdated: (m: VibeProjectMarker) => void;
  onRefresh: () => void;
}) {
  // Invisible chat hook — the chat UI is gone from this phase, but we still
  // need a session handle to ask the agent to write PLANNING.md.
  const { state, sessionId, send } = useChatStream(project.session_id ?? null);
  const kickoffSentRef = useRef(false);

  const [content, setContent] = useState(existing);
  const [err, setErr] = useState<string | null>(null);
  const [advancing, setAdvancing] = useState<"approve" | "reject" | null>(null);

  // First entry → if PLANNING.md is empty, ask the agent to write it.
  useEffect(() => {
    if (kickoffSentRef.current) return;
    if (state !== "open" || !sessionId) return;
    if (content.trim().length > 0) {
      kickoffSentRef.current = true;
      return;
    }
    kickoffSentRef.current = true;
    send(PLANNING_KICKOFF_PROMPT);
  }, [state, sessionId, content, send]);

  // Poll for PLANNING.md updates as the agent writes it.
  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      api
        .getVibeProject(project.name)
        .then((r) => {
          if (!cancelled) setContent(r.planning_md ?? "");
        })
        .catch(() => {
          /* quiet — keep prior content */
        });
    };
    const id = window.setInterval(tick, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [project.name]);

  const onApprove = useCallback(async () => {
    setAdvancing("approve");
    setErr(null);
    try {
      const res = await api.patchVibeProject(project.name, {
        phase: "development",
      });
      onUpdated(res.project);
      onRefresh();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setAdvancing(null);
    }
  }, [project.name, onUpdated, onRefresh]);

  const onReject = useCallback(async () => {
    setAdvancing("reject");
    setErr(null);
    try {
      const res = await api.patchVibeProject(project.name, {
        phase: "brainstorm",
      });
      onUpdated(res.project);
      onRefresh();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setAdvancing(null);
    }
  }, [project.name, onUpdated, onRefresh]);

  const regenerate = useCallback(() => {
    if (state !== "open" || !sessionId) return;
    send(
      "Rewrite PLANNING.md from scratch. The previous draft missed something — " +
        "consider edge cases and any feedback from the user so far. Keep it tight.",
    );
  }, [state, sessionId, send]);

  const isEmpty = content.trim().length === 0;
  const waiting = isEmpty;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border/60 bg-background-base/40">
      <header className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-border/60 px-4">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          PLANNING.md
        </span>
        <div className="flex items-center gap-2">
          <Badge tone={isEmpty ? "secondary" : "success"}>
            {isEmpty ? "awaiting agent" : "drafted"}
          </Badge>
          <Button
            ghost
            size="icon"
            aria-label="Ask the agent to regenerate the plan"
            title="Regenerate"
            onClick={regenerate}
            disabled={state !== "open" || !sessionId}
          >
            <Sparkles className="h-3.5 w-3.5" />
          </Button>
        </div>
      </header>

      {waiting ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-6 py-12 text-center">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            The agent is writing PLANNING.md based on the approved requirements.
            This usually takes 15–60 seconds.
          </p>
        </div>
      ) : (
        <pre className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap break-words px-6 py-4 font-mono text-xs leading-relaxed text-midground">
          {content}
        </pre>
      )}

      <div className="flex flex-col gap-2 border-t border-border/60 px-4 py-3">
        {err && (
          <div className="flex items-start gap-2 text-xs text-destructive">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="break-words">{err}</span>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button
            onClick={onApprove}
            disabled={isEmpty || advancing !== null}
            className="gap-2"
          >
            {advancing === "approve" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Check className="h-4 w-4" />
            )}
            <span>Approve → Build</span>
          </Button>
          <Button
            ghost
            onClick={onReject}
            disabled={advancing !== null}
            className="gap-2"
          >
            {advancing === "reject" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ArrowLeft className="h-4 w-4" />
            )}
            <span>Back to Brainstorm</span>
          </Button>
          <span className="text-[0.7rem] text-muted-foreground/60">
            Approve to let the agent start coding. Reject to keep refining scope.
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Building (development) ───────────────────────────────────────────────────

// Resizable split between chat (left) and live-preview (right). Mirrors the
// pattern used by /panel — same keys/limits so the muscle memory carries over.
const SPLIT_STORAGE_KEY = "sopify:vibeBuildChatPct";
const SPLIT_DEFAULT = 55;
const SPLIT_MIN = 15;
const SPLIT_MAX = 85;
const clampSplit = (pct: number) =>
  Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, pct));

// Sent once when the user lands on Building. ChatPanel's existing
// kickoff machinery suppresses it if the session already has turns,
// so re-entering an in-progress build doesn't re-prompt the agent.
const BUILDING_KICKOFF_PROMPT =
  "PLANNING.md is approved. Start coding now. Follow PLANNING.md step-by-step, " +
  "obey the sopify-sdlc skill standards (TypeScript strict, Tailwind utilities, " +
  "MVC layering, parameterized SQL, loading/error/empty states everywhere). " +
  "When you start a dev server use `--host 0.0.0.0` so the Live preview can reach " +
  "it. Tell me when each milestone in PLANNING.md is done so I can review.";

function BuildingPane({ project }: { project: VibeProjectMarker }) {
  const [reloadKey, setReloadKey] = useState(0);
  const [devServers, setDevServers] = useState<
    { port: number; url: string }[]
  >([]);
  const currentServer = devServers[0];
  const previewSrc = useMemo(
    () => (currentServer ? `${currentServer.url}#${reloadKey}` : null),
    [currentServer, reloadKey],
  );

  // Resizable split: only active at lg+; below that the panes stack and
  // the iframe is given a fixed-ish height via aspect.
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
      // localStorage unavailable — ignore.
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

  // When no dev server is detected, hide the preview pane entirely and let
  // the chat take the full row. Once detected, fall back to the persisted
  // split ratio.
  const chatStyle = isStacked || !previewSrc
    ? undefined
    : { flexGrow: chatPct, flexBasis: 0 };
  const previewStyle = isStacked
    ? undefined
    : { flexGrow: 100 - chatPct, flexBasis: 0 };

  return (
    <div
      ref={splitRef}
      className="flex min-h-0 flex-1 flex-col gap-3 lg:flex-row lg:gap-0"
    >
      <div
        style={chatStyle}
        className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
      >
        <ChatPanel
          project={project}
          header="Building"
          kickoff={BUILDING_KICKOFF_PROMPT}
          onDevServersChange={setDevServers}
        />
      </div>

      {previewSrc ? (
        /* Drag handle — desktop only; matches /panel UX. Hidden when no
         * preview is up so chat takes the full row. */
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
            "mx-1 w-1.5 select-none focus-visible:outline-none",
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
      ) : null}

      {previewSrc ? (
        <aside
          style={previewStyle}
          className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-border/60 bg-background-base/40 lg:flex-1"
          aria-label="Live preview"
        >
          <header className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-border/60 px-3">
            <Typography
              mondwest
              className="text-[0.75rem] tracking-[0.1em] uppercase text-muted-foreground"
            >
              Live preview
            </Typography>
            <div className="flex items-center gap-2">
              <span className="font-mono text-[0.65rem] text-muted-foreground/70">
                {currentServer?.url}
              </span>
              <Button
                ghost
                size="icon"
                aria-label="Reload preview"
                onClick={() => setReloadKey((k) => k + 1)}
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
            </div>
          </header>
          <iframe
            key={previewSrc}
            src={previewSrc}
            title={`${project.name} preview`}
            className="min-h-0 flex-1 border-0"
            sandbox="allow-scripts allow-forms allow-popups allow-modals allow-same-origin"
          />
        </aside>
      ) : null}
    </div>
  );
}

// ── Layout helper ────────────────────────────────────────────────────────────

function SplitWithSide({
  main,
  side,
}: {
  main: React.ReactNode;
  side: React.ReactNode;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 lg:flex-row">
      {main}
      <aside
        className="flex min-h-0 shrink-0 flex-col overflow-hidden rounded-lg border border-border/60 bg-background-base/40 lg:w-[40%] xl:w-[44%]"
        aria-label="Sidebar"
      >
        {side}
      </aside>
    </div>
  );
}

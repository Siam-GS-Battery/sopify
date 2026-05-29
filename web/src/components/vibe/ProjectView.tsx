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
 * Backend has 6 phases (brainstorm/design/backend/improvement/security/
 * approve). For now the UI still routes them through the three original
 * panes (Brainstorm / Planning / Building) — the Planning pane handles
 * the design phase, and the Building pane handles backend / improvement /
 * security / approve. A follow-up PR splits each phase into its own
 * dedicated pane with the right artifact preview (DESIGN.md / DATABASE.md
 * / API.md / SECURITY_REVIEW.md). See `phaseToStepKey` for the rail
 * mapping.
 */

interface Props {
  data: VibeProjectGetResponse;
  onBack: () => void;
  onUpdated: (updated: VibeProjectMarker) => void;
  onRefresh: () => void;
}

function phaseToStepKey(phase: VibePhase): VibeStepKey {
  if (phase === "brainstorm") return "brainstorm";
  if (phase === "design") return "design";
  if (phase === "backend") return "backend";
  if (phase === "improvement") return "improvement";
  if (phase === "security") return "security";
  return "done"; // approve
}

const PROJECT_DONE_KEYS: VibeStepKey[] = ["name", "theme", "addons"];

export function ProjectView({ data, onBack, onUpdated, onRefresh }: Props) {
  const { project, requirements_md, design_md, database_md, api_md } = data;

  const stepperKey = phaseToStepKey(project.phase);
  const doneKeys = useMemo<VibeStepKey[]>(() => {
    const done = [...PROJECT_DONE_KEYS];
    // Treat every step before the current as done.
    const order: VibeStepKey[] = [
      "brainstorm",
      "design",
      "backend",
      "improvement",
      "security",
      "done",
    ];
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
          {project.phase === "brainstorm" && (
            <BrainstormPane
              project={project}
              initialRequirements={requirements_md ?? ""}
              onUpdated={onUpdated}
              onRefresh={onRefresh}
            />
          )}
          {project.phase === "design" && (
            <DesignPane
              project={project}
              initialDesign={design_md ?? ""}
              onUpdated={onUpdated}
              onRefresh={onRefresh}
            />
          )}
          {project.phase === "backend" && (
            <BackendPane
              project={project}
              initialDatabase={database_md ?? ""}
              initialApi={api_md ?? ""}
              onUpdated={onUpdated}
              onRefresh={onRefresh}
            />
          )}
          {(project.phase === "improvement" ||
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
            // REQUIREMENTS.md is whatever the agent has written into the
            // project folder by now; advance directly to the design phase.
            const res = await api.patchVibeProject(project.name, {
              phase: "design",
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
          <span>Approve → Design</span>
        </Button>
        <p className="text-[0.7rem] text-muted-foreground/60">
          When REQUIREMENTS.md captures the scope, approve to move on.
        </p>
      </div>
    </>
  );
}

// ── Design ──────────────────────────────────────────────────────────────────

/**
 * Design is the frontend-mockup phase. Chat is visible (the user iterates
 * with the agent), the Live preview iframe shows the dev server, and the
 * approval bar at the bottom lets the user advance to `backend` once the
 * mockup feels right or roll back to `brainstorm` if scope needs more work.
 *
 * Shares the resizable-split helpers with BuildingPane below; the constants
 * are declared further down but referenced from a function body, so they
 * are in scope at render time.
 */
const DESIGN_KICKOFF_PROMPT =
  "REQUIREMENTS.md is approved. We're now in the DESIGN phase. " +
  "Build a static frontend mockup only — no backend, no Supabase, no fetches. " +
  "Use React 18 + TypeScript strict + Tailwind v4 per the sopify-sdlc skill, " +
  "with realistic placeholder data inlined plus loading / empty / error states. " +
  "Follow the pre-loaded frontend-design skill for a bold visual direction. " +
  "Write DESIGN.md at the project root summarising components, tokens, pages, " +
  "and any open questions. Start the dev server with --host 0.0.0.0 (e.g. " +
  "`vite --host`) so the Live preview iframe can reach it. Tell me when the " +
  "mockup is reviewable.";

function DesignPane({
  project,
  initialDesign,
  onUpdated,
  onRefresh,
}: {
  project: VibeProjectMarker;
  initialDesign: string;
  onUpdated: (m: VibeProjectMarker) => void;
  onRefresh: () => void;
}) {
  const [designContent, setDesignContent] = useState(initialDesign);
  const [devServers, setDevServers] = useState<
    { port: number; url: string }[]
  >([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [advancing, setAdvancing] = useState<"approve" | "reject" | null>(null);

  // Poll for DESIGN.md updates as the agent writes it.
  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      api
        .getVibeProject(project.name)
        .then((r) => {
          if (!cancelled) setDesignContent(r.design_md ?? "");
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

  const currentServer = devServers[0];
  const previewSrc = useMemo(
    () => (currentServer ? `${currentServer.url}#${reloadKey}` : null),
    [currentServer, reloadKey],
  );

  // Resizable split — same wiring as BuildingPane. Shares SPLIT_STORAGE_KEY
  // so the user's preferred ratio carries from Design through Building.
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
      window.localStorage.setItem(
        SPLIT_STORAGE_KEY,
        String(Math.round(chatPct)),
      );
    } catch {
      /* localStorage unavailable — ignore. */
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
  const chatStyle = isStacked || !previewSrc
    ? undefined
    : { flexGrow: chatPct, flexBasis: 0 };
  const previewStyle = isStacked
    ? undefined
    : { flexGrow: 100 - chatPct, flexBasis: 0 };

  const onApprove = useCallback(async () => {
    setAdvancing("approve");
    setErr(null);
    try {
      const res = await api.patchVibeProject(project.name, {
        phase: "backend",
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

  const hasDesign = designContent.trim().length > 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
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
            header="Design"
            kickoff={DESIGN_KICKOFF_PROMPT}
            onDevServersChange={setDevServers}
          />
        </div>

        {previewSrc ? (
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

      <div className="shrink-0 flex flex-col gap-2 rounded-lg border border-border/60 bg-background-base/40 px-4 py-3">
        {err && (
          <div className="flex items-start gap-2 text-xs text-destructive">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="break-words">{err}</span>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={hasDesign ? "success" : "secondary"}>
            DESIGN.md {hasDesign ? "drafted" : "not yet"}
          </Badge>
          <Button
            onClick={onApprove}
            disabled={advancing !== null}
            className="gap-2"
          >
            {advancing === "approve" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Check className="h-4 w-4" />
            )}
            <span>Approve → Backend</span>
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
            Click through the preview iframe. Approve when the mockup feels right.
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Backend ─────────────────────────────────────────────────────────────────

/**
 * Backend is the schema + API + frontend-wiring phase. The pane mirrors
 * DesignPane's chat + split layout, but the right side hosts three tabs
 * (DATABASE.md / API.md / Preview) instead of a bare iframe — the user
 * needs to read what the agent designed before the schema lands, then
 * see API.md once it's written, then verify the wired app in the iframe.
 *
 * Both markdown files are polled every 4 s and a tab's badge flips to
 * "drafted" the moment the agent writes the file.
 */
const BACKEND_KICKOFF_PROMPT =
  "DESIGN.md is approved. We're now in the BACKEND phase.\n\n" +
  "Step 1 — DATA SHAPE REVIEW (before doing anything destructive): write " +
  "DATABASE.md at the project root with a table list, a mermaid ER diagram, " +
  "per-table column lists (name / type / nullable / default), RLS posture, " +
  "and the open questions you need me to decide. Surface trade-offs in chat " +
  "(naming, denormalisation, soft vs hard delete, who owns which relation). " +
  "Do NOT run the supabase CLI or write SQL files yet.\n\n" +
  "Step 2 — STAND UP THE DATA LAYER (after I signal the schema looks right): " +
  "write migrations under supabase/migrations/, apply them via `supabase db " +
  "push`, generate TS types, add a supabase client, wire the service layer, " +
  "and replace placeholder data in the frontend with real fetches. Keep the " +
  "design 1:1 with what was approved. Write API.md summarising endpoints + " +
  "auth posture + error contract.\n\n" +
  "Bind any dev server to --host 0.0.0.0 so the Live preview iframe can reach " +
  "it. Tell me when DATABASE.md is reviewable, and again when the app is " +
  "wired end-to-end so I can approve to Improvement.";

type BackendTab = "database" | "api" | "preview";

function BackendPane({
  project,
  initialDatabase,
  initialApi,
  onUpdated,
  onRefresh,
}: {
  project: VibeProjectMarker;
  initialDatabase: string;
  initialApi: string;
  onUpdated: (m: VibeProjectMarker) => void;
  onRefresh: () => void;
}) {
  const [databaseContent, setDatabaseContent] = useState(initialDatabase);
  const [apiContent, setApiContent] = useState(initialApi);
  const [devServers, setDevServers] = useState<
    { port: number; url: string }[]
  >([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [activeTab, setActiveTab] = useState<BackendTab>("database");
  const [err, setErr] = useState<string | null>(null);
  const [advancing, setAdvancing] = useState<"approve" | "reject" | null>(null);

  // Poll for DATABASE.md + API.md updates.
  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      api
        .getVibeProject(project.name)
        .then((r) => {
          if (cancelled) return;
          setDatabaseContent(r.database_md ?? "");
          setApiContent(r.api_md ?? "");
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

  const currentServer = devServers[0];
  const previewSrc = useMemo(
    () => (currentServer ? `${currentServer.url}#${reloadKey}` : null),
    [currentServer, reloadKey],
  );

  // Resizable split — same wiring as DesignPane / BuildingPane.
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
      window.localStorage.setItem(
        SPLIT_STORAGE_KEY,
        String(Math.round(chatPct)),
      );
    } catch {
      /* localStorage unavailable — ignore. */
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
  const chatStyle = isStacked
    ? undefined
    : { flexGrow: chatPct, flexBasis: 0 };
  const sideStyle = isStacked
    ? undefined
    : { flexGrow: 100 - chatPct, flexBasis: 0 };

  const onApprove = useCallback(async () => {
    setAdvancing("approve");
    setErr(null);
    try {
      const res = await api.patchVibeProject(project.name, {
        phase: "improvement",
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
        phase: "design",
      });
      onUpdated(res.project);
      onRefresh();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setAdvancing(null);
    }
  }, [project.name, onUpdated, onRefresh]);

  const hasDatabase = databaseContent.trim().length > 0;
  const hasApi = apiContent.trim().length > 0;

  const tabs: { key: BackendTab; label: string; ready: boolean }[] = [
    { key: "database", label: "DATABASE.md", ready: hasDatabase },
    { key: "api", label: "API.md", ready: hasApi },
    { key: "preview", label: "Preview", ready: Boolean(previewSrc) },
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
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
            header="Backend"
            kickoff={BACKEND_KICKOFF_PROMPT}
            onDevServersChange={setDevServers}
          />
        </div>

        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize chat and artifact panes"
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

        <aside
          style={sideStyle}
          className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-border/60 bg-background-base/40 lg:flex-1"
          aria-label="Backend artifacts"
        >
          <header className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-border/60 px-3">
            <div
              role="tablist"
              aria-label="Backend artifact tabs"
              className="flex items-center gap-1"
            >
              {tabs.map((t) => (
                <button
                  key={t.key}
                  role="tab"
                  aria-selected={activeTab === t.key}
                  onClick={() => setActiveTab(t.key)}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[0.7rem] font-semibold uppercase tracking-wider transition-colors",
                    activeTab === t.key
                      ? "bg-midground/10 text-midground"
                      : "text-muted-foreground/70 hover:text-midground",
                  )}
                >
                  <span>{t.label}</span>
                  <span
                    aria-hidden
                    className={cn(
                      "inline-block h-1.5 w-1.5 rounded-full",
                      t.ready ? "bg-emerald-500" : "bg-muted-foreground/30",
                    )}
                  />
                </button>
              ))}
            </div>
            {activeTab === "preview" && previewSrc && (
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
            )}
          </header>

          {activeTab === "database" && (
            <pre className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap break-words px-4 py-3 font-mono text-xs leading-relaxed text-midground">
              {hasDatabase
                ? databaseContent
                : "(empty — the agent will write DATABASE.md once it has reviewed the design and decided on the schema.)"}
            </pre>
          )}
          {activeTab === "api" && (
            <pre className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap break-words px-4 py-3 font-mono text-xs leading-relaxed text-midground">
              {hasApi
                ? apiContent
                : "(empty — the agent will write API.md once the schema is approved and endpoints are wired.)"}
            </pre>
          )}
          {activeTab === "preview" &&
            (previewSrc ? (
              <iframe
                key={previewSrc}
                src={previewSrc}
                title={`${project.name} preview`}
                className="min-h-0 flex-1 border-0"
                sandbox="allow-scripts allow-forms allow-popups allow-modals allow-same-origin"
              />
            ) : (
              <div className="flex min-h-0 flex-1 items-center justify-center px-6 py-12 text-center text-xs text-muted-foreground/70">
                No dev server detected yet. Once the agent runs the dev
                server with <code>--host 0.0.0.0</code>, it will appear here.
              </div>
            ))}
        </aside>
      </div>

      <div className="shrink-0 flex flex-col gap-2 rounded-lg border border-border/60 bg-background-base/40 px-4 py-3">
        {err && (
          <div className="flex items-start gap-2 text-xs text-destructive">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="break-words">{err}</span>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={hasDatabase && hasApi ? "success" : "secondary"}>
            {hasDatabase && hasApi
              ? "DATABASE.md + API.md drafted"
              : hasDatabase
                ? "DATABASE.md drafted, API.md pending"
                : "awaiting agent"}
          </Badge>
          <Button
            onClick={onApprove}
            disabled={advancing !== null}
            className="gap-2"
          >
            {advancing === "approve" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Check className="h-4 w-4" />
            )}
            <span>Approve → Improvement</span>
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
            <span>Back to Design</span>
          </Button>
          <span className="text-[0.7rem] text-muted-foreground/60">
            Approve when the schema, API, and frontend wiring all look right.
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

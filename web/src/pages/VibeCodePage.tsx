import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Folder,
  Loader2,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Switch } from "@nous-research/ui/ui/components/switch";
import { Typography } from "@/components/NouiTypography";
import { ProjectView } from "@/components/vibe/ProjectView";
import { ThemeCard, type ThemeOption } from "@/components/vibe/ThemeCard";
import { VIBE_STEPS, VerticalStepper } from "@/components/vibe/VerticalStepper";
import { api } from "@/lib/api";
import type {
  VibeProjectGetResponse,
  VibeProjectMarker,
  VibeProjectSummary,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// Thumbnails for the four built-in starting examples. Imported directly so
// Vite bundles them at build time — no /api round-trip and no session-token
// query string juggling for <img src>. Source lives in sopify-harness/example/,
// kept in sync with the backend's `_VIBE_EXAMPLE_LABELS` allowlist.
import dashboardImg from "../../../example/dashboard/image.png";
import formRegistrationImg from "../../../example/form-registration/image.png";
import landingPageImg from "../../../example/landing-page/image.png";
import webAppImg from "../../../example/web-app/image.png";

const VIBE_THEMES: ThemeOption[] = [
  {
    name: "dashboard",
    label: "Dashboard",
    description: "Admin panels, analytics, charts and tables.",
    imageUrl: dashboardImg,
  },
  {
    name: "form-registration",
    label: "Form / Registration",
    description: "Sign-up, onboarding and data-collection flows.",
    imageUrl: formRegistrationImg,
  },
  {
    name: "landing-page",
    label: "Landing Page",
    description: "Marketing pages, hero sections, calls to action.",
    imageUrl: landingPageImg,
  },
  {
    name: "web-app",
    label: "Web App",
    description: "Interactive multi-screen products with state.",
    imageUrl: webAppImg,
  },
];

const ACTIVE_PROJECT_KEY = "sopify:vibeCurrentProject";

type View =
  | { kind: "list" }
  | { kind: "create" }
  | { kind: "project"; data: VibeProjectGetResponse }
  | { kind: "loading-project"; name: string };

export default function VibeCodePage() {
  const [view, setView] = useState<View>(() => {
    if (typeof window === "undefined") return { kind: "list" };
    const name = window.localStorage.getItem(ACTIVE_PROJECT_KEY);
    return name ? { kind: "loading-project", name } : { kind: "list" };
  });

  const persistActive = useCallback((name: string | null) => {
    try {
      if (name) window.localStorage.setItem(ACTIVE_PROJECT_KEY, name);
      else window.localStorage.removeItem(ACTIVE_PROJECT_KEY);
    } catch {
      // localStorage may be unavailable — non-fatal, page works without persistence.
    }
  }, []);

  useEffect(() => {
    if (view.kind !== "loading-project") return;
    let cancelled = false;
    api
      .getVibeProject(view.name)
      .then((data) => {
        if (cancelled) return;
        setView({ kind: "project", data });
      })
      .catch(() => {
        if (cancelled) return;
        persistActive(null);
        setView({ kind: "list" });
      });
    return () => {
      cancelled = true;
    };
  }, [view, persistActive]);

  const openProject = useCallback(
    async (name: string) => {
      setView({ kind: "loading-project", name });
      try {
        const data = await api.getVibeProject(name);
        persistActive(name);
        setView({ kind: "project", data });
      } catch {
        persistActive(null);
        setView({ kind: "list" });
      }
    },
    [persistActive],
  );

  const onCreated = useCallback(
    async (name: string) => {
      await openProject(name);
    },
    [openProject],
  );

  const onProjectUpdated = useCallback((updated: VibeProjectMarker) => {
    setView((cur) =>
      cur.kind === "project"
        ? { kind: "project", data: { ...cur.data, project: updated } }
        : cur,
    );
  }, []);

  const onRefresh = useCallback(() => {
    setView((cur) => {
      if (cur.kind !== "project") return cur;
      const projectName = cur.data.project.name;
      api
        .getVibeProject(projectName)
        .then((data) =>
          setView((c) => (c.kind === "project" ? { kind: "project", data } : c)),
        )
        .catch(() => {
          // Quiet failure — the user can navigate away and reopen if needed.
        });
      return cur;
    });
  }, []);

  const onBack = useCallback(() => {
    persistActive(null);
    setView({ kind: "list" });
  }, [persistActive]);

  if (view.kind === "loading-project") {
    return (
      <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span>Loading {view.name}…</span>
      </div>
    );
  }
  if (view.kind === "project") {
    return (
      <ProjectView
        data={view.data}
        onBack={onBack}
        onUpdated={onProjectUpdated}
        onRefresh={onRefresh}
      />
    );
  }
  if (view.kind === "create") {
    return (
      <CreateForm
        onCancel={() => setView({ kind: "list" })}
        onCreated={onCreated}
      />
    );
  }
  return (
    <ProjectsList
      onOpen={openProject}
      onNew={() => setView({ kind: "create" })}
    />
  );
}

// ── Projects list ────────────────────────────────────────────────────────────

function ProjectsList({
  onOpen,
  onNew,
}: {
  onOpen: (name: string) => void;
  onNew: () => void;
}) {
  const [projects, setProjects] = useState<VibeProjectSummary[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .listVibeProjects()
      .then((r) => {
        setProjects(r.projects);
        setErr(null);
      })
      .catch((e: unknown) =>
        setErr(e instanceof Error ? e.message : String(e)),
      );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onDelete = useCallback(
    async (name: string) => {
      if (!window.confirm(`Delete project "${name}"? This cannot be undone.`))
        return;
      setPending(name);
      try {
        await api.deleteVibeProject(name);
        load();
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        setPending(null);
      }
    },
    [load],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pb-8 normal-case">
      <header className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="rounded-lg border border-border/60 bg-background-base/40 p-2 text-midground">
            <Sparkles className="h-5 w-5" />
          </div>
          <div>
            <Typography
              mondwest
              className="font-bold text-[1.1rem] tracking-[0.05em] uppercase text-midground"
            >
              Vibe Code
            </Typography>
            <p className="mt-1 text-xs text-muted-foreground">
              Guided AI-DLC flow. Pick a project to continue, or start a new one.
            </p>
          </div>
        </div>
        <Button onClick={onNew} className="gap-2">
          <Plus className="h-4 w-4" />
          <span>New project</span>
        </Button>
      </header>

      {err && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 break-words">{err}</span>
        </div>
      )}

      {projects === null && !err && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-20 animate-pulse rounded-lg border border-border/40 bg-background-base/40"
            />
          ))}
        </div>
      )}

      {projects !== null && projects.length === 0 && (
        <div className="rounded-lg border border-dashed border-border/60 bg-background-base/40 px-4 py-8 text-center">
          <Folder className="mx-auto h-6 w-6 text-muted-foreground/50" />
          <p className="mt-2 text-sm text-muted-foreground">
            No projects yet. Hit <strong>New project</strong> to get started.
          </p>
        </div>
      )}

      {projects !== null && projects.length > 0 && (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {projects.map((p) => (
            <li key={p.name}>
              <button
                type="button"
                onClick={() => onOpen(p.name)}
                disabled={pending === p.name}
                className={cn(
                  "group relative flex w-full flex-col gap-1 rounded-lg border border-border/60 bg-background-base/40 px-3 py-3 text-left",
                  "transition-colors hover:border-midground/40",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-midground/30",
                  "disabled:cursor-not-allowed disabled:opacity-50",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <Typography
                    mondwest
                    className="text-[0.9rem] font-bold uppercase tracking-[0.05em] text-midground"
                  >
                    {p.name}
                  </Typography>
                  <span className="font-mono text-[0.6rem] uppercase tracking-wider text-muted-foreground/60">
                    {p.phase}
                  </span>
                </div>
                <p className="font-mono text-[0.7rem] text-muted-foreground/70">
                  {p.mode}
                  {p.add_ons.length > 0 ? ` · ${p.add_ons.length} add-ons` : ""}
                </p>
                <button
                  type="button"
                  aria-label={`Delete ${p.name}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    void onDelete(p.name);
                  }}
                  className={cn(
                    "absolute right-2 top-2 rounded p-1",
                    "text-muted-foreground/40 opacity-0 transition-opacity",
                    "hover:bg-destructive/10 hover:text-destructive",
                    "group-hover:opacity-100 focus-visible:opacity-100",
                    "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-destructive/40",
                  )}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Create form ──────────────────────────────────────────────────────────────

interface AddOn {
  key: string;
  label: string;
  description: string;
}

const ADD_ONS: AddOn[] = [
  {
    key: "auth-jwt",
    label: "Authentication (JWT)",
    description: "Sign in with email/password, JWT-based sessions.",
  },
  {
    key: "database-supabase",
    label: "Database (Supabase Local)",
    description: "Postgres + auth + storage running locally.",
  },
  {
    key: "file-upload",
    label: "File Upload",
    description: "Drag-and-drop uploads with progress and validation.",
  },
  {
    key: "schedule-job",
    label: "Schedule Job",
    description: "Cron-style background jobs.",
  },
  {
    key: "qr-scan",
    label: "QR Scan",
    description: "Browser camera QR code scanning.",
  },
  {
    key: "dark-mode",
    label: "Dark Mode",
    description: "System-preference theme toggle.",
  },
];

const NAME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;

type CreateStatus =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "error"; message: string };

function CreateForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: (name: string) => void;
}) {
  const [name, setName] = useState("");
  const [mode, setMode] = useState<string | null>(null);
  const [addOns, setAddOns] = useState<Set<string>>(() => new Set());
  const [status, setStatus] = useState<CreateStatus>({ kind: "idle" });

  const toggleAddOn = useCallback((key: string) => {
    setAddOns((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const nameValid = NAME_RE.test(name);
  const canSubmit =
    nameValid && mode !== null && status.kind !== "submitting";

  const onSubmit = useCallback(async () => {
    if (!canSubmit || mode === null) return;
    setStatus({ kind: "submitting" });
    try {
      const res = await api.createVibeProject({
        name,
        mode,
        add_ons: [...addOns],
      });
      onCreated(res.project.name);
    } catch (e: unknown) {
      setStatus({
        kind: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  }, [canSubmit, mode, name, addOns, onCreated]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto pb-8 normal-case lg:flex-row lg:gap-8">
      <div className="flex min-w-0 flex-1 flex-col gap-8">
        <header className="flex items-start gap-3">
          <Button ghost size="icon" onClick={onCancel} aria-label="Back">
            ←
          </Button>
          <div className="min-w-0">
            <Typography
              mondwest
              className="font-bold text-[1.1rem] tracking-[0.05em] uppercase text-midground"
            >
              New Vibe Code project
            </Typography>
            <p className="mt-1 text-xs text-muted-foreground">
              Name the project, choose a theme, toggle any add-ons.
            </p>
          </div>
        </header>

        <section id="step-name" className="flex flex-col gap-2">
          <SectionLabel index={1} title="Project name" />
          <input
            type="text"
            autoComplete="off"
            spellCheck={false}
            placeholder="e.g. battery-dashboard"
            value={name}
            onChange={(e) => setName(e.target.value.toLowerCase())}
            className={cn(
              "w-full max-w-md rounded-md border bg-background-base/60 px-3 py-2",
              "font-mono text-sm text-midground placeholder:text-muted-foreground/50",
              "focus-visible:outline-none focus-visible:ring-2",
              nameValid || name === ""
                ? "border-border/60 focus-visible:ring-midground/30"
                : "border-destructive/60 focus-visible:ring-destructive/40",
            )}
          />
          <p
            className={cn(
              "text-[0.7rem]",
              nameValid || name === ""
                ? "text-muted-foreground/70"
                : "text-destructive",
            )}
          >
            {name === "" || nameValid
              ? "Lowercase letters, digits, _ or - (max 64 chars). This becomes the folder name."
              : "Invalid name — use lowercase letters/digits/_/- and start with a letter or digit."}
          </p>
        </section>

        <section id="step-theme" className="flex flex-col gap-3">
          <SectionLabel index={2} title="Theme" />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {VIBE_THEMES.map((t) => (
              <ThemeCard
                key={t.name}
                theme={t}
                selected={mode === t.name}
                onSelect={() => setMode(t.name)}
              />
            ))}
          </div>
        </section>

        <section id="step-addons" className="flex flex-col gap-3">
          <SectionLabel index={3} title="Add-ons (optional)" />
          <ul className="flex flex-col divide-y divide-border/40 rounded-lg border border-border/60 bg-background-base/40">
            {ADD_ONS.map((a) => (
              <AddOnRow
                key={a.key}
                addOn={a}
                checked={addOns.has(a.key)}
                onToggle={() => toggleAddOn(a.key)}
              />
            ))}
          </ul>
        </section>

        <SubmitBar canSubmit={canSubmit} status={status} onSubmit={onSubmit} />
      </div>

      <aside
        aria-label="Setup progress"
        className="hidden shrink-0 lg:block lg:w-[240px] xl:w-[260px]"
      >
        <div className="sticky top-4 rounded-lg border border-border/60 bg-transparent px-5 py-5">
          <VerticalStepper
            steps={VIBE_STEPS}
            currentKey="setup"
            doneKeys={[]}
          />
        </div>
      </aside>
    </div>
  );
}

function SectionLabel({ index, title }: { index: number; title: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <Typography
        mondwest
        className="text-[0.6rem] tracking-[0.18em] uppercase text-muted-foreground/60"
      >
        Step {index}
      </Typography>
      <Typography
        mondwest
        className="text-[0.85rem] tracking-[0.05em] uppercase text-midground"
      >
        {title}
      </Typography>
    </div>
  );
}

function AddOnRow({
  addOn,
  checked,
  onToggle,
}: {
  addOn: AddOn;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <li className="flex items-center gap-4 px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-midground">{addOn.label}</p>
        <p className="mt-0.5 text-xs text-muted-foreground/70">
          {addOn.description}
        </p>
      </div>
      <Switch
        checked={checked}
        onCheckedChange={onToggle}
        aria-label={addOn.label}
      />
    </li>
  );
}

function SubmitBar({
  canSubmit,
  status,
  onSubmit,
}: {
  canSubmit: boolean;
  status: CreateStatus;
  onSubmit: () => void;
}) {
  const errMsg = useMemo(
    () => (status.kind === "error" ? status.message : null),
    [status],
  );
  return (
    <div className="mt-2 flex flex-col gap-2">
      {errMsg && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 break-words">{errMsg}</span>
        </div>
      )}
      <div className="flex items-center gap-3">
        <Button onClick={onSubmit} disabled={!canSubmit} className="gap-2">
          {status.kind === "submitting" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          <span>Start project</span>
        </Button>
        <span className="text-[0.7rem] text-muted-foreground/60">
          Creates the folder, then continues to Brainstorm.
        </span>
      </div>
    </div>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  Check,
  FileSpreadsheet,
  FileText,
  Folder,
  ImageIcon,
  Loader2,
  Plus,
  Sparkles,
  Trash2,
  X,
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

// Mirror of `_VIBE_UPLOADS_MAX_BYTES` on the backend (hermes_cli/web_server.py).
// Filtering client-side avoids the round-trip + 413 toast for an obvious reject.
const UPLOAD_MAX_BYTES = 50 * 1024 * 1024;

// Q3 (Inputs & Outputs) drives Theme + half the add-ons. These maps are the
// single source of truth for that auto-selection logic.
type InputChoice = "manual" | "spreadsheet" | "qr-scan";
type OutputChoice = "dashboard" | "form";
type AccessMode = "solo" | "team-shared" | "team-isolated";

const INPUT_OPTIONS: { id: InputChoice; label: string; hint: string }[] = [
  { id: "manual", label: "Type it manually", hint: "Forms, text fields, dropdowns" },
  { id: "spreadsheet", label: "Upload a spreadsheet", hint: "CSV / Excel bulk import" },
  { id: "qr-scan", label: "Scan a code", hint: "QR / barcode via camera" },
];

const OUTPUT_OPTIONS: { id: OutputChoice; label: string; hint: string }[] = [
  { id: "dashboard", label: "Charts & tables to monitor", hint: "Dashboards, KPIs, reports" },
  { id: "form", label: "A form to fill in and submit", hint: "Data-entry, registration, request" },
];

// Q4 — predefined "nice to have but NOT v1" items. Selected items get written
// into the project's brief.md as explicit non-goals so the brainstorm agent
// won't scope-creep them in.
const SCOPE_EXCLUSIONS: { id: string; label: string }[] = [
  { id: "notifications-email", label: "Email / Line notifications" },
  { id: "export-pdf-excel", label: "Export to PDF or Excel" },
  { id: "multi-language", label: "Multi-language support" },
  { id: "advanced-search", label: "Advanced search & filters" },
  { id: "audit-log", label: "Audit log / activity history" },
  { id: "real-time-updates", label: "Real-time updates (vs manual refresh)" },
  { id: "bulk-operations", label: "Bulk edit / delete many at once" },
  { id: "mobile-polish", label: "Mobile-optimised layout" },
];

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
  const [purpose, setPurpose] = useState("");
  const [accessMode, setAccessMode] = useState<AccessMode | null>(null);
  const [inputs, setInputs] = useState<Set<InputChoice>>(() => new Set());
  const [outputs, setOutputs] = useState<Set<OutputChoice>>(() => new Set());
  const [exclusions, setExclusions] = useState<Set<string>>(() => new Set());
  const [uploads, setUploads] = useState<{
    csv: File[];
    spec: File[];
    image: File[];
  }>({ csv: [], spec: [], image: [] });
  const [status, setStatus] = useState<CreateStatus>({ kind: "idle" });

  // Q3 (outputs) → Theme. Dashboard wins ties because "monitor" is the more
  // common case for our users; Form-Registration is picked only when the user
  // explicitly wants data-entry without a dashboard view.
  useEffect(() => {
    if (outputs.has("dashboard")) setMode("dashboard");
    else if (outputs.has("form")) setMode("form-registration");
  }, [outputs]);

  // Q2 (access) + Q3 (inputs) → add-on toggles. Driven from the answers so the
  // user doesn't have to know which add-on backs which capability — but they
  // can still flip toggles by hand below, since this is a one-way "answers →
  // add-ons" projection (we don't reverse-update answers if they tweak toggles).
  useEffect(() => {
    setAddOns((prev) => {
      const next = new Set(prev);
      // Q3 input mapping
      if (inputs.has("spreadsheet")) next.add("file-upload");
      else next.delete("file-upload");
      if (inputs.has("qr-scan")) next.add("qr-scan");
      else next.delete("qr-scan");
      // Q2 access mapping — any team mode needs auth; per-user isolation also
      // needs Supabase so RLS can enforce the boundary at the DB layer.
      if (accessMode === "team-shared" || accessMode === "team-isolated") {
        next.add("auth-jwt");
      } else if (accessMode === "solo") {
        next.delete("auth-jwt");
      }
      if (accessMode === "team-isolated") next.add("database-supabase");
      return next;
    });
  }, [inputs, accessMode]);

  const toggleAddOn = useCallback((key: string) => {
    setAddOns((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const addFiles = useCallback(
    (slot: "csv" | "spec" | "image", files: File[]) => {
      setUploads((prev) => ({ ...prev, [slot]: [...prev[slot], ...files] }));
    },
    [],
  );
  const removeFile = useCallback(
    (slot: "csv" | "spec" | "image", index: number) => {
      setUploads((prev) => ({
        ...prev,
        [slot]: prev[slot].filter((_, i) => i !== index),
      }));
    },
    [],
  );

  const nameValid = NAME_RE.test(name);
  const purposeValid = purpose.trim().length > 0;
  const questionsValid =
    purposeValid &&
    accessMode !== null &&
    inputs.size > 0 &&
    outputs.size > 0;
  const canSubmit =
    nameValid &&
    questionsValid &&
    mode !== null &&
    status.kind !== "submitting";

  const toggleSetItem = <T,>(
    setter: React.Dispatch<React.SetStateAction<Set<T>>>,
    key: T,
  ) => {
    setter((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const onSubmit = useCallback(async () => {
    if (!canSubmit || mode === null) return;
    setStatus({ kind: "submitting" });
    try {
      const res = await api.createVibeProject({
        name,
        mode,
        add_ons: [...addOns],
      });
      const projectName = res.project.name;
      const allFiles = [...uploads.csv, ...uploads.spec, ...uploads.image];
      if (allFiles.length > 0) {
        try {
          await api.uploadVibeFiles(projectName, allFiles);
        } catch (e: unknown) {
          // Project was created — surface the upload failure but let the user
          // proceed; they can re-upload from BrainstormPane (Slice ≥ 4) or
          // delete the project and retry.
          setStatus({
            kind: "error",
            message:
              "Project created but uploads failed: " +
              (e instanceof Error ? e.message : String(e)) +
              ". You can continue without them or delete and retry.",
          });
          return;
        }
      }
      onCreated(projectName);
    } catch (e: unknown) {
      setStatus({
        kind: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  }, [canSubmit, mode, name, addOns, uploads, onCreated]);

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
              Answer a few scoping questions — theme + add-ons + uploads follow.
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

        <section id="step-purpose" className="flex flex-col gap-2">
          <SectionLabel index={2} title="Purpose" />
          <p className="text-xs text-muted-foreground/80">
            In one sentence: who uses this, and what does it help them get done?
          </p>
          <textarea
            rows={3}
            placeholder="e.g. Production-line operators log battery test runs so QA can spot failing cells before they ship."
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
            className={cn(
              "w-full max-w-2xl rounded-md border bg-background-base/60 px-3 py-2",
              "text-sm text-midground placeholder:text-muted-foreground/50",
              "focus-visible:outline-none focus-visible:ring-2",
              purposeValid || purpose === ""
                ? "border-border/60 focus-visible:ring-midground/30"
                : "border-destructive/60 focus-visible:ring-destructive/40",
            )}
          />
          <p className="text-[0.7rem] text-muted-foreground/60">
            If you can't answer this, the project isn't ready to start — pause here and figure it out first.
          </p>
        </section>

        <section id="step-access" className="flex flex-col gap-3">
          <SectionLabel index={3} title="Users & Access" />
          <p className="text-xs text-muted-foreground/80">
            Is this just for you, or for a team?
          </p>
          <div className="flex flex-col gap-2">
            <RadioRow
              label="Just for me"
              hint="Single user — no login, no per-user isolation."
              checked={accessMode === "solo"}
              onSelect={() => setAccessMode("solo")}
            />
            <RadioRow
              label="A team — everyone sees the same data"
              hint="Shared dataset behind a login. Auth (JWT) gets toggled below."
              checked={accessMode === "team-shared"}
              onSelect={() => setAccessMode("team-shared")}
            />
            <RadioRow
              label="A team — each person sees only their own data"
              hint="Per-user data isolation. Pulls in Auth + Supabase (row-level security)."
              checked={accessMode === "team-isolated"}
              onSelect={() => setAccessMode("team-isolated")}
            />
          </div>
          <p className="text-[0.7rem] text-muted-foreground/60">
            Retrofitting auth or per-user data later usually means rewriting half the schema — easier to decide now.
          </p>
        </section>

        <section id="step-io" className="flex flex-col gap-3">
          <SectionLabel index={4} title="Inputs & Outputs" />
          <p className="text-xs text-muted-foreground/80">
            How does information get in — and how do you want to see it come back out?
          </p>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="flex flex-col gap-2">
              <Typography
                mondwest
                className="text-[0.65rem] tracking-[0.12em] uppercase text-muted-foreground/70"
              >
                In
              </Typography>
              {INPUT_OPTIONS.map((o) => (
                <CheckRow
                  key={o.id}
                  label={o.label}
                  hint={o.hint}
                  checked={inputs.has(o.id)}
                  onToggle={() => toggleSetItem(setInputs, o.id)}
                />
              ))}
            </div>
            <div className="flex flex-col gap-2">
              <Typography
                mondwest
                className="text-[0.65rem] tracking-[0.12em] uppercase text-muted-foreground/70"
              >
                Out
              </Typography>
              {OUTPUT_OPTIONS.map((o) => (
                <CheckRow
                  key={o.id}
                  label={o.label}
                  hint={o.hint}
                  checked={outputs.has(o.id)}
                  onToggle={() => toggleSetItem(setOutputs, o.id)}
                />
              ))}
            </div>
          </div>
          <p className="text-[0.7rem] text-muted-foreground/60">
            Your answers auto-pick the theme + relevant add-ons below — adjust them by hand if needed.
          </p>
        </section>

        <section id="step-scope" className="flex flex-col gap-3">
          <SectionLabel
            index={5}
            title="Scope boundary (optional)"
          />
          <p className="text-xs text-muted-foreground/80">
            What would be nice to have, but is <strong>NOT</strong> needed for the first version?
            Tick items to mark them as explicit non-goals so the agent won't scope-creep them in.
          </p>
          <ul className="grid grid-cols-1 gap-1 sm:grid-cols-2">
            {SCOPE_EXCLUSIONS.map((s) => (
              <li key={s.id}>
                <CheckRow
                  label={s.label}
                  checked={exclusions.has(s.id)}
                  onToggle={() => toggleSetItem(setExclusions, s.id)}
                />
              </li>
            ))}
          </ul>
        </section>

        <section id="step-theme" className="flex flex-col gap-3">
          <SectionLabel index={6} title="Theme" />
          <p className="text-xs text-muted-foreground/80">
            Pre-selected from your Inputs & Outputs answer — override if you have a different shape in mind.
          </p>
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
          <SectionLabel index={7} title="Add-ons" />
          <p className="text-xs text-muted-foreground/80">
            Auth / Supabase / File-upload / QR-scan are auto-toggled from your answers above. Flip any of them by hand if you disagree.
          </p>
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

        <section id="step-csv" className="flex flex-col gap-3">
          <SectionLabel index={8} title="Data files — CSV / Excel (optional)" />
          <FileDropZone
            icon={FileSpreadsheet}
            accept=".csv,.xlsx,.xls"
            extensions={[".csv", ".xlsx", ".xls"]}
            maxBytes={UPLOAD_MAX_BYTES}
            files={uploads.csv}
            description="Tabular data the agent will read as context — e.g. existing reports, historical metrics."
            onAdd={(fs) => addFiles("csv", fs)}
            onRemove={(i) => removeFile("csv", i)}
          />
        </section>

        <section id="step-spec" className="flex flex-col gap-3">
          <SectionLabel index={9} title="Spec markdown (optional)" />
          <FileDropZone
            icon={FileText}
            accept=".md,.markdown"
            extensions={[".md", ".markdown"]}
            maxBytes={UPLOAD_MAX_BYTES}
            files={uploads.spec}
            description="A pre-written spec / brief in Markdown. Stored under uploads/ alongside other context — does not replace REQUIREMENTS.md."
            onAdd={(fs) => addFiles("spec", fs)}
            onRemove={(i) => removeFile("spec", i)}
          />
        </section>

        <section id="step-images" className="flex flex-col gap-3">
          <SectionLabel index={10} title="Images (optional)" />
          <FileDropZone
            icon={ImageIcon}
            accept=".png,.jpg,.jpeg,.webp,.gif"
            extensions={[".png", ".jpg", ".jpeg", ".webp", ".gif"]}
            maxBytes={UPLOAD_MAX_BYTES}
            files={uploads.image}
            description="UX/UI references, screenshots, equipment photos, or work-process diagrams the agent should understand."
            onAdd={(fs) => addFiles("image", fs)}
            onRemove={(i) => removeFile("image", i)}
          />
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

function RadioRow({
  label,
  hint,
  checked,
  onSelect,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={checked}
      className={cn(
        "flex items-start gap-3 rounded-md border px-3 py-2 text-left transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/30",
        checked
          ? "border-[var(--primary)] bg-[var(--primary)]/5"
          : "border-border/60 bg-background-base/40 hover:border-midground/40",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2",
          checked ? "border-[var(--primary)]" : "border-border/70",
        )}
      >
        {checked && <span className="h-2 w-2 rounded-full bg-[var(--primary)]" />}
      </span>
      <span className="min-w-0 flex-1">
        <p className="text-sm font-medium text-midground">{label}</p>
        {hint && (
          <p className="mt-0.5 text-xs text-muted-foreground/70">{hint}</p>
        )}
      </span>
    </button>
  );
}

function CheckRow({
  label,
  hint,
  checked,
  onToggle,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={onToggle}
      className={cn(
        "flex w-full items-start gap-3 rounded-md border px-3 py-2 text-left transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/30",
        checked
          ? "border-[var(--primary)] bg-[var(--primary)]/5"
          : "border-border/60 bg-background-base/40 hover:border-midground/40",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded border-2",
          checked
            ? "border-[var(--primary)] bg-[var(--primary)] text-white"
            : "border-border/70 bg-transparent",
        )}
      >
        {checked && <Check className="h-3 w-3" strokeWidth={3} />}
      </span>
      <span className="min-w-0 flex-1">
        <p className="text-sm font-medium text-midground">{label}</p>
        {hint && (
          <p className="mt-0.5 text-xs text-muted-foreground/70">{hint}</p>
        )}
      </span>
    </button>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

interface FileDropZoneProps {
  icon: React.ComponentType<{ className?: string }>;
  accept: string;
  extensions: string[];
  maxBytes: number;
  files: File[];
  description: string;
  onAdd: (files: File[]) => void;
  onRemove: (index: number) => void;
}

function FileDropZone({
  icon: Icon,
  accept,
  extensions,
  maxBytes,
  files,
  description,
  onAdd,
  onRemove,
}: FileDropZoneProps) {
  const [dragOver, setDragOver] = useState(false);
  const [hint, setHint] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Lower-case the user-supplied extension once so case mismatches don't
  // silently drop files (Foo.CSV should still count as .csv).
  const allowed = useMemo(
    () => new Set(extensions.map((e) => e.toLowerCase())),
    [extensions],
  );

  const validate = useCallback(
    (incoming: FileList | File[]): File[] => {
      const accepted: File[] = [];
      const rejected: string[] = [];
      for (const f of Array.from(incoming)) {
        const dot = f.name.lastIndexOf(".");
        const ext = dot >= 0 ? f.name.slice(dot).toLowerCase() : "";
        if (!allowed.has(ext)) {
          rejected.push(`${f.name} (unsupported type)`);
          continue;
        }
        if (f.size > maxBytes) {
          rejected.push(
            `${f.name} (${formatBytes(f.size)} exceeds ${formatBytes(maxBytes)})`,
          );
          continue;
        }
        accepted.push(f);
      }
      setHint(rejected.length ? `Skipped: ${rejected.join(", ")}` : null);
      return accepted;
    },
    [allowed, maxBytes],
  );

  return (
    <div className="flex flex-col gap-2">
      <div
        role="button"
        tabIndex={0}
        aria-label="Add files"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragEnter={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          setDragOver(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          onAdd(validate(e.dataTransfer.files));
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center gap-1 rounded-md border border-dashed px-4 py-6 text-center transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/30",
          dragOver
            ? "border-[var(--primary)] bg-[var(--primary)]/5"
            : "border-border/60 bg-background-base/40 hover:border-midground/40",
        )}
      >
        <Icon className="h-5 w-5 text-muted-foreground" />
        <p className="text-sm text-midground">
          Drop files here or click to browse
        </p>
        <p className="text-xs text-muted-foreground/70">{description}</p>
        <p className="font-mono text-[0.65rem] uppercase tracking-wider text-muted-foreground/50">
          {extensions.join(" · ")} · max {formatBytes(maxBytes)}
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={accept}
          className="hidden"
          onChange={(e) => {
            if (e.target.files) onAdd(validate(e.target.files));
            // Reset so picking the same file twice still fires onChange.
            e.target.value = "";
          }}
        />
      </div>
      {hint && (
        <p className="text-[0.7rem] text-destructive">{hint}</p>
      )}
      {files.length > 0 && (
        <ul className="flex flex-col gap-1">
          {files.map((f, i) => (
            <li
              key={`${f.name}-${i}`}
              className="flex items-center gap-2 rounded-md border border-border/40 bg-background-base/40 px-3 py-2 text-xs"
            >
              <span className="min-w-0 flex-1 truncate font-mono text-midground">
                {f.name}
              </span>
              <span className="shrink-0 font-mono text-muted-foreground/70">
                {formatBytes(f.size)}
              </span>
              <button
                type="button"
                onClick={() => onRemove(i)}
                aria-label={`Remove ${f.name}`}
                className="shrink-0 rounded p-1 text-muted-foreground/60 hover:bg-destructive/10 hover:text-destructive"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
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

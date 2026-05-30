import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { VibeAvailableModel } from "@/lib/api";

export interface StepperItem {
  key: string;
  title: string;
  description?: string;
}

interface Props {
  steps: readonly StepperItem[];
  currentKey: string;
  doneKeys: readonly string[];
  /** Optional active model per UI step key (omit step → no badge rendered). */
  phaseModels?: Record<string, string>;
  /** Dropdown options. Must be supplied if `onModelChange` is provided. */
  availableModels?: VibeAvailableModel[];
  /** Fires with the UI step key + the picked "provider/model" id. */
  onModelChange?: (uiStepKey: string, modelId: string) => void;
}

export function VerticalStepper({
  steps,
  currentKey,
  doneKeys,
  phaseModels,
  availableModels,
  onModelChange,
}: Props) {
  const doneSet = new Set(doneKeys);
  return (
    <ol
      aria-label="Vibe Code progress"
      className="flex flex-col gap-0 normal-case"
    >
      {steps.map((step, i) => {
        const isDone = doneSet.has(step.key);
        const isActive = step.key === currentKey;
        const isLast = i === steps.length - 1;
        const isReached = isDone || isActive;
        const modelId = phaseModels?.[step.key];
        return (
          <li
            key={step.key}
            aria-current={isActive ? "step" : undefined}
            className="relative grid grid-cols-[28px_1fr] gap-x-3"
          >
            <div className="relative flex flex-col items-center">
              <span
                className={cn(
                  "relative z-10 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
                  isDone &&
                    "border-[var(--primary)] bg-[var(--primary)] text-white",
                  isActive &&
                    "border-[var(--primary)] bg-background ring-4 ring-[var(--primary)]/15",
                  !isDone &&
                    !isActive &&
                    "border-border/70 bg-background",
                )}
              >
                {/* Ping pulse — only on the currently-active step. Sits
                 * behind the dot/check via source order; respects
                 * prefers-reduced-motion by hiding the animation outright
                 * (the static ring-4 above still marks the active state). */}
                {isActive && (
                  <span
                    aria-hidden
                    className="absolute -inset-px rounded-full bg-[var(--primary)] opacity-40 animate-ping motion-reduce:hidden"
                  />
                )}
                {isDone ? (
                  <Check className="relative h-3 w-3" strokeWidth={3} />
                ) : isActive ? (
                  <span className="relative h-2 w-2 rounded-full bg-[var(--primary)]" />
                ) : null}
              </span>
              {!isLast && (
                <span
                  aria-hidden
                  className={cn(
                    "w-0.5 flex-1 transition-colors",
                    isReached ? "bg-[var(--primary)]/60" : "bg-border/50",
                  )}
                />
              )}
            </div>
            <div className={cn("pb-6", isLast && "pb-0")}>
              <p
                className={cn(
                  "text-sm font-semibold leading-tight transition-colors",
                  isActive && "text-midground",
                  isDone && "text-midground/80",
                  !isDone && !isActive && "text-muted-foreground/60",
                )}
              >
                {step.title}
              </p>
              {step.description && (
                <p
                  className={cn(
                    "mt-0.5 text-xs leading-snug",
                    isActive
                      ? "text-muted-foreground"
                      : "text-muted-foreground/50",
                  )}
                >
                  {step.description}
                </p>
              )}
              {modelId && (
                <ModelBadge
                  modelId={modelId}
                  available={availableModels}
                  onChange={
                    onModelChange
                      ? (m) => onModelChange(step.key, m)
                      : undefined
                  }
                  dim={!isReached}
                />
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Inline pill that shows the active model for a phase. Click → dropdown with
 * the available models grouped by provider. Read-only when no `onChange`
 * handler is wired in (e.g. the setup wizard's stepper doesn't allow picking
 * because the project doesn't exist yet).
 */
function ModelBadge({
  modelId,
  available,
  onChange,
  dim,
}: {
  modelId: string;
  available?: VibeAvailableModel[];
  onChange?: (modelId: string) => void;
  dim?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Close on outside click — the dropdown isn't modal so this is the lightest
  // dismissal pattern.
  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const label = labelFor(modelId, available);
  const readOnly = !onChange;

  return (
    <div ref={wrapRef} className="mt-1 relative inline-block">
      <button
        type="button"
        onClick={readOnly ? undefined : () => setOpen((o) => !o)}
        disabled={readOnly}
        className={cn(
          "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[0.65rem] font-mono leading-tight",
          "border transition-colors",
          dim
            ? "border-border/40 bg-background-base/40 text-muted-foreground/60"
            : "border-border/60 bg-background-base/60 text-midground/80",
          !readOnly && "hover:border-[var(--primary)]/60 hover:text-midground cursor-pointer",
        )}
        aria-haspopup={readOnly ? undefined : "listbox"}
        aria-expanded={readOnly ? undefined : open}
        title={modelId}
      >
        <span className="truncate max-w-[140px]">{label}</span>
        {!readOnly && <ChevronDown className="h-3 w-3 shrink-0" />}
      </button>
      {open && available && available.length > 0 && (
        <ul
          role="listbox"
          className={cn(
            "absolute left-0 top-full z-50 mt-1 min-w-[220px] max-w-[280px]",
            "rounded-md border border-border/70 bg-background-base shadow-lg",
            "py-1 max-h-[280px] overflow-y-auto",
          )}
        >
          {available.map((m) => {
            const selected = m.id === modelId;
            return (
              <li key={m.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={selected}
                  onClick={() => {
                    if (onChange && m.id !== modelId) onChange(m.id);
                    setOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-start gap-2 px-3 py-1.5 text-left text-xs",
                    "hover:bg-[var(--primary)]/8",
                    selected && "bg-[var(--primary)]/10 text-midground font-medium",
                    !selected && "text-muted-foreground",
                  )}
                >
                  <span
                    aria-hidden
                    className={cn(
                      "mt-0.5 inline-flex h-3 w-3 shrink-0 items-center justify-center rounded-full border",
                      selected
                        ? "border-[var(--primary)] bg-[var(--primary)]"
                        : "border-border/70 bg-background",
                    )}
                  >
                    {selected && (
                      <span className="h-1.5 w-1.5 rounded-full bg-white" />
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <p className="font-medium text-midground">{m.label}</p>
                    <p className="font-mono text-[0.6rem] text-muted-foreground/70 truncate">
                      {m.id}
                    </p>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function labelFor(modelId: string, available?: VibeAvailableModel[]): string {
  const hit = available?.find((m) => m.id === modelId);
  if (hit) return hit.label;
  // Unknown SKU (e.g. set via API to a non-curated value) — show the model
  // part of "provider/model" so the badge still reads.
  const slash = modelId.indexOf("/");
  return slash >= 0 ? modelId.slice(slash + 1) : modelId;
}

export const VIBE_STEP_KEYS = [
  "setup",
  "brainstorm",
  "design",
  "backend",
  "improvement",
  "security",
  "done",
] as const;

export type VibeStepKey = (typeof VIBE_STEP_KEYS)[number];

export const VIBE_STEPS: readonly StepperItem[] = [
  {
    key: "setup",
    title: "Create project",
    description: "Name, theme, add-ons, and optional context uploads.",
  },
  { key: "brainstorm", title: "Brainstorm", description: "Define requirements with the agent." },
  { key: "design", title: "Design", description: "Frontend mockup with frontend-design skill." },
  { key: "backend", title: "Backend & Database", description: "Schema, API, and frontend wiring." },
  { key: "improvement", title: "Improvement", description: "Polish, tweaks, free iteration." },
  { key: "security", title: "Security", description: "Automated security review." },
  { key: "done", title: "Done", description: "All artifacts approved." },
];

/**
 * UI step key ↔ backend phase key mapping. The Vibe Code stepper has 7 UI
 * steps; the backend phase machine only knows 6 (no `setup` — pre-create;
 * UI `done` maps to backend `approve`). Used by callers to translate between
 * the stepper's keys and the backend's `/api/vibe/projects/{name}/models`
 * `phase` field.
 */
export const UI_STEP_TO_BACKEND_PHASE: Record<VibeStepKey, string | null> = {
  setup: null,
  brainstorm: "brainstorm",
  design: "design",
  backend: "backend",
  improvement: "improvement",
  security: "security",
  done: "approve",
};

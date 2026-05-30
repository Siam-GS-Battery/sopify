import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export interface StepperItem {
  key: string;
  title: string;
  description?: string;
}

interface Props {
  steps: readonly StepperItem[];
  currentKey: string;
  doneKeys: readonly string[];
}

export function VerticalStepper({ steps, currentKey, doneKeys }: Props) {
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
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export const VIBE_STEP_KEYS = [
  "name",
  "theme",
  "addons",
  "brainstorm",
  "design",
  "backend",
  "improvement",
  "security",
  "done",
] as const;

export type VibeStepKey = (typeof VIBE_STEP_KEYS)[number];

export const VIBE_STEPS: readonly StepperItem[] = [
  { key: "name", title: "Create project", description: "Pick a folder name." },
  { key: "theme", title: "Theme", description: "Choose a starting example." },
  { key: "addons", title: "Add-ons", description: "Toggle optional features." },
  { key: "brainstorm", title: "Brainstorm", description: "Define requirements with the agent." },
  { key: "design", title: "Design", description: "Frontend mockup with frontend-design skill." },
  { key: "backend", title: "Backend & Database", description: "Schema, API, and frontend wiring." },
  { key: "improvement", title: "Improvement", description: "Polish, tweaks, free iteration." },
  { key: "security", title: "Security", description: "Automated security review." },
  { key: "done", title: "Done", description: "All artifacts approved." },
];

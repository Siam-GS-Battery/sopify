import type { ReactNode } from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import type { VibeAvailableModel } from "@/lib/api";
import { ModelBadge } from "@/components/vibe/ModelBadge";
import type { StepperItem } from "@/components/vibe/VerticalStepper";

/**
 * Horizontal variant of the Vibe Code progress stepper.
 *
 * Replaces the project page's old header + right rail combo. Sits on a
 * single row across the top of ProjectView so the phase panes (and the
 * Live preview iframe inside them) get the full page width.
 *
 * Each step shows a dot/check + truncated title + an optional model
 * badge. Descriptions live in the `title` attribute (tooltip) since
 * the row can't afford a second line at narrow widths. Below ~lg the
 * row scrolls horizontally rather than wrapping — wrapping the dots
 * across multiple lines makes the "where am I in the flow" read
 * harder than just letting the user scroll.
 */
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
  /** Optional content rendered on the left of the row (e.g. back button). */
  leftSlot?: ReactNode;
  /** Optional content rendered on the right (e.g. phase badge / actions). */
  rightSlot?: ReactNode;
}

export function HorizontalStepper({
  steps,
  currentKey,
  doneKeys,
  phaseModels,
  availableModels,
  onModelChange,
  leftSlot,
  rightSlot,
}: Props) {
  const doneSet = new Set(doneKeys);
  return (
    <div
      className={cn(
        "flex min-w-0 items-center gap-2 rounded-lg border border-border/60",
        "bg-background-base/40 px-3 py-2 normal-case",
      )}
      aria-label="Vibe Code progress"
    >
      {leftSlot && (
        <div className="flex shrink-0 items-center gap-1 pr-1">{leftSlot}</div>
      )}

      <ol className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
        {steps.map((step, i) => {
          const isDone = doneSet.has(step.key);
          const isActive = step.key === currentKey;
          const isLast = i === steps.length - 1;
          const isReached = isDone || isActive;
          const modelId = phaseModels?.[step.key];
          const tooltip = step.description
            ? `${step.title} — ${step.description}`
            : step.title;
          return (
            <li
              key={step.key}
              aria-current={isActive ? "step" : undefined}
              className="flex min-w-0 shrink-0 items-center gap-1.5"
              title={tooltip}
            >
              {/* Dot / check */}
              <span
                className={cn(
                  "relative inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
                  isDone &&
                    "border-[var(--primary)] bg-[var(--primary)] text-white",
                  isActive &&
                    "border-[var(--primary)] bg-background ring-2 ring-[var(--primary)]/20",
                  !isDone &&
                    !isActive &&
                    "border-border/70 bg-background",
                )}
              >
                {isDone ? (
                  <Check className="h-2.5 w-2.5" strokeWidth={3} />
                ) : isActive ? (
                  <span className="h-1.5 w-1.5 rounded-full bg-[var(--primary)]" />
                ) : null}
              </span>

              {/* Label + badge stacked. min-w-0 so siblings can shrink. */}
              <div className="flex min-w-0 flex-col leading-tight">
                <span
                  className={cn(
                    "max-w-[120px] truncate text-[0.7rem] font-semibold transition-colors",
                    isActive && "text-midground",
                    isDone && "text-midground/80",
                    !isDone && !isActive && "text-muted-foreground/60",
                  )}
                >
                  {step.title}
                </span>
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
                    compact
                  />
                )}
              </div>

              {/* Connector to next step */}
              {!isLast && (
                <span
                  aria-hidden
                  className={cn(
                    "mx-1 h-0.5 w-4 shrink-0 transition-colors",
                    isReached ? "bg-[var(--primary)]/60" : "bg-border/50",
                  )}
                />
              )}
            </li>
          );
        })}
      </ol>

      {rightSlot && (
        <div className="flex shrink-0 items-center gap-2 pl-1">{rightSlot}</div>
      )}
    </div>
  );
}

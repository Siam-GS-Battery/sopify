import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { VibeAvailableModel } from "@/lib/api";

/**
 * Inline pill that shows the active model for a phase. Click → dropdown with
 * the available models grouped by provider. Read-only when no `onChange`
 * handler is wired in (e.g. the setup wizard's stepper doesn't allow picking
 * because the project doesn't exist yet).
 *
 * Lives outside the stepper components so the horizontal + vertical
 * variants share one implementation. Layout density is controlled via
 * the `compact` prop — compact = horizontal-stepper inline pill;
 * default = vertical-stepper full-size pill with its own top margin.
 */
export function ModelBadge({
  modelId,
  available,
  onChange,
  dim,
  compact,
}: {
  modelId: string;
  available?: VibeAvailableModel[];
  onChange?: (modelId: string) => void;
  dim?: boolean;
  /** Horizontal-stepper layout: no extra top margin, narrower text cap. */
  compact?: boolean;
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
    <div
      ref={wrapRef}
      className={cn("relative inline-block", !compact && "mt-1")}
    >
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
        <span className={cn("truncate", compact ? "max-w-[110px]" : "max-w-[140px]")}>
          {label}
        </span>
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

export function labelFor(modelId: string, available?: VibeAvailableModel[]): string {
  const hit = available?.find((m) => m.id === modelId);
  if (hit) return hit.label;
  // Unknown SKU (e.g. set via API to a non-curated value) — show the model
  // part of "provider/model" so the badge still reads.
  const slash = modelId.indexOf("/");
  return slash >= 0 ? modelId.slice(slash + 1) : modelId;
}

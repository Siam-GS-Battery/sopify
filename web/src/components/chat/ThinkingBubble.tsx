import { Brain, ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Collapsible "Thinking…" disclosure shown inside an assistant turn.
 *
 * While `active` (reasoning streaming, answer not yet started) the header
 * pulses and the body auto-expands so the user sees the model reason in
 * real time. Once the answer begins, it collapses to a quiet one-liner the
 * user can re-open.
 */
export function ThinkingBubble({
  text,
  active,
}: {
  text: string;
  active: boolean;
}) {
  const [override, setOverride] = useState<boolean | null>(null);
  const open = override ?? active;
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div className="rounded-lg border border-border/60 bg-muted/20 overflow-hidden">
      <button
        type="button"
        onClick={() => setOverride(!open)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-muted-foreground hover:bg-foreground/5"
      >
        <Chevron className="h-3 w-3 shrink-0" />
        <Brain
          className={cn("h-3.5 w-3.5 shrink-0", active && "animate-pulse text-primary")}
        />
        <span className={cn("tracking-wide", active && "text-primary")}>
          {active ? "Thinking…" : "Thought process"}
        </span>
      </button>

      {open && text && (
        <div className="border-t border-border/50 px-3 py-2">
          <pre className="whitespace-pre-wrap break-words font-mono text-[0.72rem] leading-relaxed text-muted-foreground">
            {text}
            {active && (
              <span className="inline-block w-1.5 h-3 align-middle bg-foreground/40 ml-0.5 animate-pulse" />
            )}
          </pre>
        </div>
      )}
    </div>
  );
}

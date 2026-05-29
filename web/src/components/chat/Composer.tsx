import { Button } from "@nous-research/ui/ui/components/button";
import { ArrowUp, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Bottom input row for the Panel. Auto-grows up to a few lines, submits on
 * Enter (Shift+Enter for newline), and swaps the send button for a stop
 * button while a turn is running.
 *
 * `prefill` lets the canvas inject a "selected component" context block the
 * user can edit before sending. `prefillKey` bumps on each new selection so
 * selecting the same element twice re-injects the block.
 */
export function Composer({
  busy,
  disabled,
  onSend,
  onStop,
  prefill,
  prefillKey,
}: {
  busy: boolean;
  disabled: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  prefill?: string;
  prefillKey?: number;
}) {
  const [value, setValue] = useState("");
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  const autosize = useCallback(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }, []);

  useEffect(() => {
    if (prefill) {
      setValue((v) => (v ? `${v}\n${prefill}` : prefill));
      taRef.current?.focus();
    }
    // Re-run when a new selection arrives (prefillKey changes), even if the
    // prefill text is identical to the previous selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillKey]);

  useEffect(autosize, [value, autosize]);

  const submit = () => {
    const text = value.trim();
    if (!text || busy || disabled) return;
    onSend(text);
    setValue("");
  };

  return (
    <div className="shrink-0 border-t border-border/60 bg-background-base/60 px-3 py-3 normal-case">
      <div className="mx-auto flex w-full max-w-3xl items-end gap-2">
        <textarea
          ref={taRef}
          rows={1}
          value={value}
          disabled={disabled}
          placeholder={disabled ? "Connecting…" : "Message Claude…"}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          className={cn(
            "min-h-[2.5rem] flex-1 resize-none rounded-xl border border-border bg-background px-3 py-2",
            "text-sm leading-relaxed text-foreground placeholder:text-muted-foreground",
            "focus:outline-none focus:ring-1 focus:ring-primary/50 disabled:opacity-60",
          )}
        />

        {busy ? (
          <Button
            outlined
            size="icon"
            onClick={onStop}
            aria-label="Stop generating"
            className="h-10 w-10 shrink-0 rounded-xl"
          >
            <Square className="h-4 w-4" />
          </Button>
        ) : (
          <Button
            size="icon"
            onClick={submit}
            disabled={disabled || value.trim().length === 0}
            aria-label="Send message"
            className="h-10 w-10 shrink-0 rounded-xl"
          >
            <ArrowUp className="h-4 w-4" />
          </Button>
        )}
      </div>
    </div>
  );
}

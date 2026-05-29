import { AlertCircle } from "lucide-react";

import { Markdown } from "@/components/Markdown";
import { ToolCall } from "@/components/ToolCall";
import { ThinkingBubble } from "@/components/chat/ThinkingBubble";
import { cn } from "@/lib/utils";
import type { AssistantTurn, UserTurn } from "@/hooks/useChatStream";

/** Right-aligned user bubble. */
export function UserBubble({ turn }: { turn: UserTurn }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary/10 border border-primary/20 px-3.5 py-2 text-sm whitespace-pre-wrap break-words text-foreground">
        {turn.text}
      </div>
    </div>
  );
}

/**
 * Left-aligned assistant turn: thinking disclosure, tool calls, then the
 * answer markdown — a stable order independent of wire interleaving.
 */
export function AssistantBubble({ turn }: { turn: AssistantTurn }) {
  const showThinking = turn.thinking.length > 0;
  const showAnswer = turn.text.length > 0 || (!showThinking && turn.tools.length === 0);

  return (
    <div className="flex justify-start">
      <div className="flex w-full max-w-[92%] flex-col gap-2">
        {showThinking && (
          <ThinkingBubble text={turn.thinking} active={turn.thinkingActive} />
        )}

        {turn.tools.length > 0 && (
          <div className="flex flex-col gap-1.5">
            {turn.tools.map((tl) => (
              <ToolCall key={tl.id} tool={tl} />
            ))}
          </div>
        )}

        {showAnswer && (
          <div
            className={cn(
              "rounded-2xl rounded-bl-sm border px-3.5 py-2",
              turn.status === "error"
                ? "border-destructive/40 bg-destructive/5"
                : "border-border bg-muted/20",
            )}
          >
            <Markdown content={turn.text} streaming={turn.streaming} />
          </div>
        )}

        {turn.error && (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="min-w-0 break-words">{turn.error}</span>
          </div>
        )}
      </div>
    </div>
  );
}

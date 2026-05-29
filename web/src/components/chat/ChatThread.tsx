import { useEffect, useRef } from "react";

import { AssistantBubble, UserBubble } from "@/components/chat/MessageBubble";
import type { Turn } from "@/hooks/useChatStream";

/**
 * Scrollable transcript. Auto-sticks to the bottom while the user hasn't
 * scrolled up — new content during streaming keeps the latest line in view,
 * but reading back through history isn't yanked away.
 */
export function ChatThread({ turns }: { turns: Turn[] }) {
  const endRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stick = useRef(true);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
      stick.current = dist < 80;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (stick.current) {
      endRef.current?.scrollIntoView({ block: "end" });
    }
  }, [turns]);

  return (
    <div
      ref={scrollRef}
      className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden"
    >
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-3 py-4 normal-case">
        {turns.length === 0 ? (
          <div className="py-16 text-center text-sm text-muted-foreground">
            Start a conversation — ask Sopify to build a website and it will
            appear on the canvas.
          </div>
        ) : (
          turns.map((turn) =>
            turn.kind === "user" ? (
              <UserBubble key={turn.id} turn={turn} />
            ) : (
              <AssistantBubble key={turn.id} turn={turn} />
            ),
          )
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}

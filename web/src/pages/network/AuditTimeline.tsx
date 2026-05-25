import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Filter,
  Pause,
  Play,
} from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { encmApi, type AuditEvent } from "@/lib/encmApi";

const POLL_INTERVAL_MS = 5000;
const DEFAULT_LIMIT = 100;
const SINCE_OPTIONS = [
  { value: "15m", label: "15m" },
  { value: "1h", label: "1h" },
  { value: "6h", label: "6h" },
  { value: "24h", label: "24h" },
];
const DECISION_OPTIONS = [
  { value: "", label: "all" },
  { value: "allow", label: "allow" },
  { value: "deny", label: "deny" },
];

function sinceToIso(value: string): string {
  const now = new Date();
  const match = value.match(/^(\d+)([mh])$/);
  if (!match) return now.toISOString();
  const n = parseInt(match[1], 10);
  const ms = match[2] === "h" ? n * 3600_000 : n * 60_000;
  return new Date(now.getTime() - ms).toISOString();
}

function fmtTime(iso: string | undefined | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}

function fmtRelative(iso: string | undefined | null): string {
  if (!iso) return "—";
  try {
    const then = new Date(iso).getTime();
    const diff = (Date.now() - then) / 1000;
    if (diff < 5) return "just now";
    if (diff < 60) return `${Math.round(diff)}s ago`;
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    return `${Math.round(diff / 3600)}h ago`;
  } catch {
    return "—";
  }
}

export function AuditTimeline() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(true);
  const [filtersOpen, setFiltersOpen] = useState(false);

  const [since, setSince] = useState<string>("1h");
  const [decision, setDecision] = useState<string>("");
  const [src, setSrc] = useState<string>("");
  const [hostFilter, setHostFilter] = useState<string>(""); // client-side

  const lastEventTs = useRef<string | null>(null);

  const fetchEvents = useCallback(async () => {
    setError(null);
    try {
      const resp = await encmApi.queryAudit({
        limit: DEFAULT_LIMIT,
        since: sinceToIso(since),
        decision: decision || undefined,
        src: src || undefined,
      });
      setEvents(resp.events);
      lastEventTs.current = resp.events[0]?.ts ?? null;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [since, decision, src]);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  useEffect(() => {
    if (!live) return;
    const id = setInterval(fetchEvents, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [live, fetchEvents]);

  // Host filter is client-side so users can narrow without re-querying.
  const visibleEvents = useMemo(() => {
    const q = hostFilter.trim().toLowerCase();
    if (!q) return events;
    return events.filter((ev) => {
      const host = String(ev.host ?? "").toLowerCase();
      return host.includes(q);
    });
  }, [events, hostFilter]);

  const stats = useMemo(() => {
    let allow = 0;
    let deny = 0;
    for (const ev of visibleEvents) {
      if (ev.decision === "allow") allow++;
      else if (ev.decision === "deny") deny++;
    }
    return { allow, deny, total: visibleEvents.length };
  }, [visibleEvents]);

  return (
    <Card className="min-w-0 max-w-full overflow-hidden">
      <CardHeader className="py-3 px-4 flex flex-row items-center justify-between gap-2">
        <CardTitle className="text-sm flex items-center gap-2 flex-wrap">
          Audit timeline
          {live ? (
            <Badge tone="success" className="text-[10px]">
              <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
              live
            </Badge>
          ) : (
            <Badge tone="secondary" className="text-[10px]">paused</Badge>
          )}
          <span className="text-muted-foreground text-xs font-normal">
            {stats.total} events · {stats.allow} allow · {stats.deny} deny
          </span>
        </CardTitle>
        <div className="flex items-center gap-1">
          <Button
            ghost
            size="icon"
            onClick={() => setFiltersOpen((s) => !s)}
            title="Toggle filters"
            aria-label="Toggle filters"
          >
            <Filter className="h-3.5 w-3.5" />
          </Button>
          <Button
            ghost
            size="icon"
            onClick={() => setLive((s) => !s)}
            title={live ? "Pause live polling" : "Resume live polling"}
            aria-label={live ? "Pause live polling" : "Resume live polling"}
          >
            {live ? (
              <Pause className="h-3.5 w-3.5" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>
      </CardHeader>

      {filtersOpen && (
        <div className="border-t border-current/10 px-4 py-3 grid grid-cols-1 sm:grid-cols-4 gap-3 text-xs">
          <FilterBlock label="Since">
            <Segmented
              value={since}
              options={SINCE_OPTIONS}
              onChange={setSince}
            />
          </FilterBlock>
          <FilterBlock label="Decision">
            <Segmented
              value={decision}
              options={DECISION_OPTIONS}
              onChange={setDecision}
            />
          </FilterBlock>
          <FilterBlock label="Sandbox">
            <Input
              value={src}
              onChange={(e) => setSrc(e.target.value)}
              placeholder="sopify-…"
              className="h-7 text-xs"
            />
          </FilterBlock>
          <FilterBlock label="Host contains">
            <Input
              value={hostFilter}
              onChange={(e) => setHostFilter(e.target.value)}
              placeholder="anthropic, github, …"
              className="h-7 text-xs"
            />
          </FilterBlock>
        </div>
      )}

      <CardContent className="p-0">
        {error && (
          <div className="bg-destructive/10 border-b border-destructive/20 px-4 py-2 text-xs text-destructive">
            {error}
          </div>
        )}

        {loading && events.length === 0 && (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        )}

        {!loading && visibleEvents.length === 0 && (
          <div className="py-8 text-center text-xs text-muted-foreground">
            No audit events in window. Live polling every {POLL_INTERVAL_MS / 1000}s.
          </div>
        )}

        {visibleEvents.length > 0 && (
          <ul className="max-h-[60vh] overflow-y-auto">
            {visibleEvents.map((ev, i) => (
              <EventRow
                key={`${ev.ts}-${i}`}
                ev={ev}
                isNewest={i === 0 && lastEventTs.current === ev.ts}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function FilterBlock({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  );
}

function Segmented({
  value,
  options,
  onChange,
}: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex border border-border bg-background/40">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={cn(
            "flex-1 px-2 py-1 text-[11px] transition-colors",
            "hover:bg-secondary/30",
            value === opt.value
              ? "bg-secondary/50 text-foreground"
              : "text-muted-foreground",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function EventRow({ ev, isNewest }: { ev: AuditEvent; isNewest: boolean }) {
  const [open, setOpen] = useState(false);
  const decision = String(ev.decision ?? "unknown");
  const host = String(ev.host ?? "—");
  const ruleName = ev.rule_name ? String(ev.rule_name) : null;
  // sbx defaults to deny when no rule matches — surface that distinctly
  // from explicit deny rules so users know it's a default-deny.
  const isDefaultDeny = decision === "deny" && !ruleName;

  const ChevronIcon = open ? ChevronDown : ChevronRight;

  return (
    <li
      className={cn(
        "border-b border-current/5 hover:bg-secondary/10 transition-colors",
        isNewest && "animate-[fade-in_200ms_ease-out]",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((s) => !s)}
        className="flex w-full items-center gap-3 px-4 py-2 text-left text-xs"
      >
        <ChevronIcon className="h-3 w-3 shrink-0 text-muted-foreground" />
        <span
          className="text-muted-foreground tabular-nums shrink-0"
          title={ev.ts}
        >
          {fmtTime(ev.ts)}
        </span>
        <DecisionBadge decision={decision} defaultDeny={isDefaultDeny} />
        <span className="font-courier truncate flex-1 min-w-0">{host}</span>
        {ruleName && (
          <Badge tone="outline" className="text-[10px] shrink-0">
            {ruleName}
          </Badge>
        )}
      </button>

      {open && (
        <div className="px-12 py-3 text-[11px] bg-background/30 border-t border-current/5">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            <Detail
              label="Timestamp"
              value={`${fmtTime(ev.ts)} (${fmtRelative(ev.ts)})`}
            />
            <Detail label="Sandbox" value={String(ev.src ?? "—")} mono />
            <Detail label="Host" value={host} mono />
            <Detail label="Decision" value={decision} />
            <Detail
              label="Rule"
              value={ruleName ?? (isDefaultDeny ? "(default-deny — no rule matched)" : "—")}
              mono={!!ruleName}
            />
            <Detail
              label="Proxy mode"
              value={String(ev.proxy_mode ?? "—")}
              mono
            />
          </div>

          {Object.keys(ev).some(
            (k) =>
              !["ts", "src", "host", "decision", "rule_name", "proxy_mode"].includes(k),
          ) && (
            <details className="mt-2">
              <summary className="cursor-pointer text-muted-foreground text-[10px]">
                Raw event
              </summary>
              <pre className="mt-1 font-courier text-[10px] leading-4 overflow-x-auto">
                {JSON.stringify(ev, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}
    </li>
  );
}

function DecisionBadge({
  decision,
  defaultDeny,
}: {
  decision: string;
  defaultDeny: boolean;
}) {
  if (defaultDeny) {
    return (
      <Badge tone="warning" className="text-[10px] shrink-0">
        deny ·
        default
      </Badge>
    );
  }
  if (decision === "allow") {
    return (
      <Badge tone="success" className="text-[10px] shrink-0">
        allow
      </Badge>
    );
  }
  if (decision === "deny") {
    return (
      <Badge tone="destructive" className="text-[10px] shrink-0">
        deny
      </Badge>
    );
  }
  return (
    <Badge tone="secondary" className="text-[10px] shrink-0">
      {decision}
    </Badge>
  );
}

function Detail({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex gap-2">
      <span className="text-muted-foreground text-[10px] uppercase tracking-wide w-20 shrink-0">
        {label}
      </span>
      <span className={cn("min-w-0 truncate", mono && "font-courier")}>
        {value}
      </span>
    </div>
  );
}

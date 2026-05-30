import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  BarChart3,
  Briefcase,
  Cpu,
  Hash,
  RefreshCw,
  Users,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AnalyticsDailyEntry,
  AnalyticsModelEntry,
  AnalyticsResponse,
  SessionInfo,
} from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { usePageHeader } from "@/contexts/usePageHeader";

// ---------------------------------------------------------------------------
// Constants & helpers
// ---------------------------------------------------------------------------

const PERIODS = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
] as const;

const CHART_HEIGHT_PX = 180;

// Active-session lookback. Sessions touched within this many seconds are
// rendered as agents currently "on the floor". 30 minutes covers a typical
// chat turn but excludes long-idle history.
const ACTIVE_WINDOW_SECONDS = 30 * 60;

// Pool of pixel-bot tints reused for each spawned agent. Hues match the
// reference store.js so multi-agent scenes stay visually varied without
// clashing with the GS Battery brand palette.
const AGENT_COLORS = [
  "#1D63ED",
  "#0DB7ED",
  "#7C6BE8",
  "#10B981",
  "#F59E0B",
  "#E0497B",
];

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatNumber(n: number): string {
  return n.toLocaleString();
}

function formatDate(day: string): string {
  try {
    const d = new Date(day + "T00:00:00");
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return day;
  }
}

// API only returns days that had usage. Pad to the full requested window so
// the bar chart always reads as a continuous time series instead of one
// fat bar over today.
function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function emptyDay(day: string): AnalyticsDailyEntry {
  return {
    day,
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    reasoning_tokens: 0,
    estimated_cost: 0,
    actual_cost: 0,
    sessions: 0,
    api_calls: 0,
  };
}

function padDaily(
  daily: AnalyticsDailyEntry[],
  days: number,
): AnalyticsDailyEntry[] {
  const byDay = new Map(daily.map((d) => [d.day, d]));
  const out: AnalyticsDailyEntry[] = [];
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    const key = isoDay(d);
    out.push(byDay.get(key) ?? emptyDay(key));
  }
  return out;
}

function shortModelLabel(model: string): string {
  // Strip provider prefix (e.g. "anthropic/claude-opus-4-7" → "claude-opus-4-7").
  const slash = model.lastIndexOf("/");
  return slash >= 0 ? model.slice(slash + 1) : model;
}

// ---------------------------------------------------------------------------
// Pixel-art mascot for each agent. Sized to overlay the office-building
// scene. The user requested: when a new agent spawns, its pixel-bot icon
// appears on top of the office-building photo. We accomplish that by
// absolutely-positioning the mascot inside the scene container.
// ---------------------------------------------------------------------------

function AgentMascot({
  size = 56,
  color = "#1D63ED",
  working = false,
}: {
  size?: number;
  color?: string;
  working?: boolean;
}) {
  return (
    <div
      className={cn(
        "relative flex flex-col items-center select-none pointer-events-none",
        working && "animate-[mascot-bob_1.2s_ease-in-out_infinite]",
      )}
      style={{ width: size }}
      aria-hidden="true"
    >
      <img
        src="/sopify-mascot.png"
        alt=""
        width={size}
        height={size}
        draggable={false}
        style={{
          imageRendering: "pixelated",
          filter: working
            ? `drop-shadow(0 2px 0 rgba(0,0,0,0.35)) drop-shadow(0 0 8px ${color})`
            : "drop-shadow(0 2px 0 rgba(0,0,0,0.35))",
        }}
      />
      <div
        className="-mt-1 rounded-full"
        style={{
          width: size * 0.55,
          height: 5,
          background: "radial-gradient(closest-side, rgba(0,0,0,0.45), transparent)",
          filter: "blur(0.5px)",
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// "Virtual Office" hero — pasted-1780118606978-0.png as background, each
// active session drawn as a pixel-bot positioned across the foreground.
// ---------------------------------------------------------------------------

interface Agent {
  id: string;
  name: string;
  role: string;
  status: "working" | "waiting" | "idle";
  model: string | null;
  task: string;
  color: string;
  lastActive: number;
}

function statusLabel(s: Agent["status"]): string {
  if (s === "working") return "Working";
  if (s === "waiting") return "Needs approval";
  return "Idle";
}

function statusDotClass(s: Agent["status"]): string {
  if (s === "working") return "bg-[#1D63ED] animate-pulse";
  if (s === "waiting") return "bg-[#F59E0B]";
  return "bg-[#8A97A0]";
}

function sessionToAgent(s: SessionInfo, idx: number): Agent {
  const ageSeconds = Math.max(0, Date.now() / 1000 - s.last_active);
  const status: Agent["status"] =
    s.is_active && ageSeconds < ACTIVE_WINDOW_SECONDS
      ? "working"
      : ageSeconds < ACTIVE_WINDOW_SECONDS * 2
        ? "waiting"
        : "idle";
  // Session IDs in the harness are time-prefixed (YYYYMM…), so the first
  // few chars collide across most of a month. The trailing chars are the
  // entropy-bearing portion — use them so each agent gets a unique label.
  const tail = s.id.replace(/[^a-zA-Z0-9]/g, "").slice(-6).toUpperCase();
  return {
    id: s.id,
    name: `Agent ${tail || String(idx + 1).padStart(2, "0")}`,
    role: s.source ?? "Worker",
    status,
    model: s.model,
    task: s.title ?? s.preview ?? "Standing by",
    color: AGENT_COLORS[idx % AGENT_COLORS.length],
    lastActive: s.last_active,
  };
}

function VirtualOfficeScene({ agents }: { agents: Agent[] }) {
  const visible = agents.slice(0, 6);
  const n = visible.length;
  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between gap-4 normal-case">
        <div className="flex items-center gap-2">
          <Briefcase className="h-4 w-4 text-muted-foreground" />
          <CardTitle className="text-base">Virtual Office</CardTitle>
          <span className="text-xs text-muted-foreground">
            · GS Battery — Thailand Plant
          </span>
        </div>
        <div className="hidden sm:flex items-center gap-3 text-[11px] text-muted-foreground normal-case">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-[#1D63ED]" /> Working
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-[#F59E0B]" /> Waiting
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-[#8A97A0]" /> Idle
          </span>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div
          className="relative h-72 w-full overflow-hidden"
          style={{
            backgroundImage: "url(/office-building.png)",
            backgroundSize: "cover",
            backgroundPosition: "center 55%",
          }}
        >
          <div
            aria-hidden
            className="absolute inset-0 pointer-events-none"
            style={{
              background:
                "radial-gradient(120% 80% at 50% 120%, rgba(0,0,0,0.30), transparent 60%)",
            }}
          />

          {n === 0 ? (
            <div className="absolute inset-x-0 bottom-3 text-center text-xs text-white/90 normal-case">
              No active agents — start a session to see them appear on the
              floor.
            </div>
          ) : (
            visible.map((a, i) => {
              const x = n === 1 ? 50 : 10 + i * (80 / (n - 1));
              const y = i % 2 === 1 ? 78 : 86;
              return (
                <div
                  key={a.id}
                  className="absolute flex flex-col items-center"
                  style={{
                    left: `${x}%`,
                    top: `${y}%`,
                    transform: "translate(-50%, -100%)",
                  }}
                >
                  <div className="mb-1 inline-flex items-center gap-1.5 rounded-full border border-border bg-card/95 px-2 py-0.5 text-[10px] font-bold text-foreground shadow-md normal-case">
                    <span
                      className={cn(
                        "h-1.5 w-1.5 rounded-full",
                        statusDotClass(a.status),
                      )}
                    />
                    {a.name}
                  </div>
                  <AgentMascot
                    size={i % 2 === 1 ? 48 : 56}
                    color={a.color}
                    working={a.status === "working"}
                  />
                </div>
              );
            })
          )}

          <div className="absolute right-3 top-3 inline-flex items-center gap-1.5 rounded-full bg-black/60 px-2.5 py-1 text-[10px] font-bold tracking-wider text-white backdrop-blur-sm normal-case">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
            LIVE · {agents.length} on site
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Agent information panel — list view of every detected session-agent.
// ---------------------------------------------------------------------------

function AgentInfoPanel({ agents }: { agents: Agent[] }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 normal-case">
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4 text-muted-foreground" />
          <CardTitle className="text-base">Agent Information</CardTitle>
        </div>
        <Badge tone="secondary" className="text-[10px]">
          {agents.length}
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        {agents.length === 0 ? (
          <div className="px-4 py-8 text-center text-xs text-muted-foreground normal-case">
            No agents yet. Sessions started in the harness will appear here.
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {agents.map((a) => (
              <li
                key={a.id}
                className="flex items-center gap-3 px-4 py-2.5 hover:bg-secondary/30 transition-colors normal-case"
              >
                <div
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md"
                  style={{ background: `${a.color}1f` }}
                >
                  <AgentMascot
                    size={32}
                    color={a.color}
                    working={a.status === "working"}
                  />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-foreground">
                      {a.name}
                    </span>
                    <span
                      className="rounded-full px-1.5 py-0.5 text-[10px] font-bold tracking-wide uppercase"
                      style={{ color: a.color, background: `${a.color}1f` }}
                    >
                      {a.role}
                    </span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    <span
                      className={cn(
                        "h-1.5 w-1.5 rounded-full",
                        statusDotClass(a.status),
                      )}
                    />
                    <span className="truncate" title={a.task}>
                      {a.task}
                    </span>
                  </div>
                  {a.model && (
                    <div className="mt-0.5 truncate text-[10px] text-muted-foreground/80 font-mono-ui">
                      {shortModelLabel(a.model)}
                    </div>
                  )}
                </div>
                <div className="shrink-0 text-right text-[10px] text-muted-foreground tabular-nums">
                  <div>{statusLabel(a.status)}</div>
                  <div className="opacity-70">{timeAgo(a.lastActive)}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// KPI tiles (4-up).
// ---------------------------------------------------------------------------

function KpiTile({
  label,
  value,
  sub,
  icon: Icon,
  accent,
  arrow,
}: {
  label: string;
  value: string;
  sub: string;
  icon: typeof BarChart3;
  accent: string;
  arrow?: "in" | "out";
}) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-1 p-4 normal-case">
        <div className="flex items-center justify-between text-[10px] font-bold tracking-[0.12em] uppercase text-muted-foreground">
          <span>{label}</span>
          <Icon className="h-3.5 w-3.5" />
        </div>
        <div
          className="mt-1 flex items-baseline gap-1.5 text-2xl font-bold tabular-nums leading-none"
          style={{ color: accent }}
        >
          {arrow === "in" && <ArrowDown className="h-4 w-4 shrink-0" />}
          {arrow === "out" && <ArrowUp className="h-4 w-4 shrink-0" />}
          {value}
        </div>
        <div className="text-[11px] text-muted-foreground">{sub}</div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Stacked bar charts — token-in stacks regular input + cache-read, and
// token-out stacks regular output + reasoning. Bars are one per day so the
// "based on time" axis reads naturally.
// ---------------------------------------------------------------------------

interface StackBarChartProps {
  title: string;
  icon: typeof BarChart3;
  daily: AnalyticsDailyEntry[];
  legend: { label: string; color: string; key: "primary" | "secondary" }[];
  picker: (d: AnalyticsDailyEntry) => { primary: number; secondary: number };
  accent: string;
}

function StackedTokenBarChart({
  title,
  icon: Icon,
  daily,
  legend,
  picker,
  accent,
}: StackBarChartProps) {
  if (daily.length === 0) {
    return (
      <Card>
        <CardHeader className="normal-case">
          <div className="flex items-center gap-2">
            <Icon className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-base">{title}</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <div className="py-8 text-center text-xs text-muted-foreground normal-case">
            No usage in this window.
          </div>
        </CardContent>
      </Card>
    );
  }

  const maxTotal = Math.max(
    ...daily.map((d) => {
      const v = picker(d);
      return v.primary + v.secondary;
    }),
    1,
  );

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-4 normal-case">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-muted-foreground" />
          <CardTitle className="text-base">{title}</CardTitle>
        </div>
        <div className="flex items-center gap-3 text-[10px] text-muted-foreground normal-case">
          {legend.map((l) => (
            <span key={l.label} className="inline-flex items-center gap-1.5">
              <span
                className="h-2.5 w-2.5 rounded-sm"
                style={{ background: l.color }}
              />
              {l.label}
            </span>
          ))}
        </div>
      </CardHeader>
      <CardContent>
        <div
          className="flex items-end gap-[3px]"
          style={{ height: CHART_HEIGHT_PX }}
        >
          {daily.map((d) => {
            const v = picker(d);
            const total = v.primary + v.secondary;
            const primaryH = Math.round((v.primary / maxTotal) * CHART_HEIGHT_PX);
            const secondaryH = Math.round((v.secondary / maxTotal) * CHART_HEIGHT_PX);
            return (
              <div
                key={d.day}
                className="group relative flex min-w-0 flex-1 flex-col justify-end"
                style={{ height: CHART_HEIGHT_PX }}
              >
                <div className="absolute bottom-full left-1/2 z-10 mb-2 hidden -translate-x-1/2 group-hover:block pointer-events-none">
                  <div className="whitespace-nowrap rounded-md border border-border bg-card px-2.5 py-1.5 text-[10px] text-foreground shadow-lg normal-case">
                    <div className="font-medium">{formatDate(d.day)}</div>
                    <div>
                      {legend[0].label}: {formatTokens(v.primary)}
                    </div>
                    <div>
                      {legend[1].label}: {formatTokens(v.secondary)}
                    </div>
                    <div className="mt-0.5 border-t border-border/40 pt-0.5">
                      Total: {formatTokens(total)}
                    </div>
                  </div>
                </div>
                <div
                  className="w-full"
                  style={{
                    background: legend[1].color,
                    height: Math.max(secondaryH, v.secondary > 0 ? 1 : 0),
                    opacity: 0.85,
                  }}
                />
                <div
                  className="w-full"
                  style={{
                    background: legend[0].color,
                    height: Math.max(primaryH, v.primary > 0 ? 1 : 0),
                  }}
                />
              </div>
            );
          })}
        </div>
        <div className="mt-2 flex justify-between text-[10px] text-muted-foreground normal-case">
          <span>{formatDate(daily[0].day)}</span>
          {daily.length > 2 && (
            <span>{formatDate(daily[Math.floor(daily.length / 2)].day)}</span>
          )}
          <span>{formatDate(daily[daily.length - 1].day)}</span>
        </div>
        <div className="mt-2 text-[10px] text-muted-foreground/70 normal-case">
          Total in window:{" "}
          <span className="font-bold tabular-nums" style={{ color: accent }}>
            {formatTokens(daily.reduce((s, d) => s + picker(d).primary + picker(d).secondary, 0))}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Models-used summary table.
// ---------------------------------------------------------------------------

function ModelsUsedPanel({ models }: { models: AnalyticsModelEntry[] }) {
  if (models.length === 0) return null;
  const total = models.reduce(
    (s, m) => s + m.input_tokens + m.output_tokens,
    0,
  );
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-4 normal-case">
        <div className="flex items-center gap-2">
          <Cpu className="h-4 w-4 text-muted-foreground" />
          <CardTitle className="text-base">Models Used</CardTitle>
        </div>
        <Badge tone="secondary" className="text-[10px]">
          {models.length} distinct
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        <ul className="divide-y divide-border">
          {models.slice(0, 8).map((m) => {
            const sum = m.input_tokens + m.output_tokens;
            const pct = total > 0 ? Math.round((sum / total) * 100) : 0;
            return (
              <li
                key={m.model}
                className="flex items-center gap-3 px-4 py-2.5 normal-case"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate font-mono-ui text-xs">
                    {shortModelLabel(m.model)}
                  </div>
                  <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-secondary/40">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${pct}%`,
                        background: "#1D63ED",
                      }}
                    />
                  </div>
                </div>
                <div className="shrink-0 text-right text-[10px] text-muted-foreground tabular-nums">
                  <div>
                    <span style={{ color: "#1D63ED" }}>
                      {formatTokens(m.input_tokens)}
                    </span>
                    {" / "}
                    <span style={{ color: "#0DB7ED" }}>
                      {formatTokens(m.output_tokens)}
                    </span>
                  </div>
                  <div className="opacity-70">{m.sessions} sess · {pct}%</div>
                </div>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page.
// ---------------------------------------------------------------------------

export default function VirtualOfficePage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { setAfterTitle, setEnd } = usePageHeader();

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      api.getAnalytics(days).catch((err) => {
        // Analytics is gated by dashboard.show_token_analytics. When the
        // backend rejects (404/403) the rest of the page should still
        // render — agents and office scene don't depend on it.
        // eslint-disable-next-line no-console
        console.warn("[VirtualOffice] analytics fetch failed:", err);
        return null;
      }),
      api
        .getSessions(20, 0)
        .then((r) => r.sessions)
        .catch(() => [] as SessionInfo[]),
    ])
      .then(([analytics, recentSessions]) => {
        setData(analytics);
        setSessions(recentSessions);
      })
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  }, [days]);

  useEffect(() => {
    load();
  }, [load]);

  // Keep "agents" fresh — sessions tick over time so a stale list slowly
  // drops out of the active window. Re-derive every 30s without re-fetching.
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  const agents = useMemo<Agent[]>(() => {
    void tick;
    return sessions.map(sessionToAgent);
  }, [sessions, tick]);

  const activeAgents = agents.filter((a) => a.status === "working").length;

  useLayoutEffect(() => {
    const periodLabel =
      PERIODS.find((p) => p.days === days)?.label ?? `${days}d`;
    setAfterTitle(
      <span className="flex items-center gap-2">
        {loading && <Spinner className="shrink-0 text-base text-primary" />}
        <Badge tone="secondary" className="text-[10px]">
          {periodLabel}
        </Badge>
      </span>,
    );
    setEnd(
      <div className="flex w-full min-w-0 flex-wrap items-center justify-start gap-2 sm:justify-end sm:gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {PERIODS.map((p) => (
            <Button
              key={p.label}
              type="button"
              size="sm"
              outlined={days !== p.days}
              onClick={() => setDays(p.days)}
            >
              {p.label}
            </Button>
          ))}
        </div>
        <Button
          type="button"
          size="sm"
          outlined
          onClick={load}
          disabled={loading}
          prefix={loading ? <Spinner /> : <RefreshCw />}
        >
          Refresh
        </Button>
      </div>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [days, loading, load, setAfterTitle, setEnd]);

  const totals = data?.totals;
  const daily = useMemo(
    () => padDaily(data?.daily ?? [], days),
    [data?.daily, days],
  );
  const models = data?.by_model ?? [];

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 pb-8 normal-case">
      {error && (
        <Card>
          <CardContent className="py-6 normal-case">
            <p className="text-center text-sm text-destructive">{error}</p>
          </CardContent>
        </Card>
      )}

      {/* 4-up KPI row: token in, token out, requests, models available. */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <KpiTile
          label="Token Input"
          value={formatTokens(totals?.total_input ?? 0)}
          sub={`${formatNumber(totals?.total_input ?? 0)} tokens in window`}
          icon={ArrowDown}
          accent="#1D63ED"
          arrow="in"
        />
        <KpiTile
          label="Token Output"
          value={formatTokens(totals?.total_output ?? 0)}
          sub={`${formatNumber(totals?.total_output ?? 0)} tokens in window`}
          icon={ArrowUp}
          accent="#0DB7ED"
          arrow="out"
        />
        <KpiTile
          label="Requests"
          value={formatNumber(
            totals?.total_api_calls ??
              daily.reduce((s, d) => s + d.sessions, 0),
          )}
          sub={`${totals?.total_sessions ?? 0} sessions · ${activeAgents} active now`}
          icon={Hash}
          accent="var(--midground-base)"
        />
        <KpiTile
          label="Models Available"
          value={String(models.length)}
          sub={
            models.length > 0
              ? `Top: ${shortModelLabel(models[0].model)}`
              : "No usage yet"
          }
          icon={Cpu}
          accent="#7C6BE8"
        />
      </div>

      {/* Two stacked bar charts: token-in and token-out over time. */}
      <div className="grid gap-3 lg:grid-cols-2">
        <StackedTokenBarChart
          title="Token Input · Stacked Daily"
          icon={BarChart3}
          daily={daily}
          legend={[
            { label: "Input", color: "#1D63ED", key: "primary" },
            { label: "Cache read", color: "#7C6BE8", key: "secondary" },
          ]}
          picker={(d) => ({
            primary: d.input_tokens,
            secondary: d.cache_read_tokens,
          })}
          accent="#1D63ED"
        />
        <StackedTokenBarChart
          title="Token Output · Stacked Daily"
          icon={BarChart3}
          daily={daily}
          legend={[
            { label: "Output", color: "#0DB7ED", key: "primary" },
            { label: "Reasoning", color: "#10B981", key: "secondary" },
          ]}
          picker={(d) => ({
            primary: d.output_tokens,
            secondary: d.reasoning_tokens,
          })}
          accent="#0DB7ED"
        />
      </div>

      {/* Two-up: virtual office hero + agent information. */}
      <div className="grid gap-3 lg:grid-cols-2">
        <VirtualOfficeScene agents={agents} />
        <AgentInfoPanel agents={agents} />
      </div>

      {/* Models used summary spans full width below. */}
      <ModelsUsedPanel models={models} />

      {/* Keyframe used by AgentMascot when an agent is "working". */}
      <style>
        {`
        @keyframes mascot-bob {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-5px); }
        }
        `}
      </style>
    </div>
  );
}

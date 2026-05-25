import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { AlertTriangle, Download, Plug, Plus, RefreshCw, Shield, ShieldOff, Trash2 } from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { usePageHeader } from "@/contexts/usePageHeader";
import { PluginSlot } from "@/plugins";
import {
  encmApi,
  isDaemonUnreachableError,
  type DaemonStatusResponse,
  type DriftListResponse,
  type NetworkRule,
} from "@/lib/encmApi";
import { AddRuleWizard } from "@/pages/network/AddRuleWizard";
import { AuditTimeline } from "@/pages/network/AuditTimeline";

type LoadState = "idle" | "loading" | "ready" | "daemon-down" | "error";

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "never";
  try {
    const then = new Date(iso).getTime();
    const diff = (Date.now() - then) / 1000;
    if (diff < 5) return "just now";
    if (diff < 60) return `${Math.round(diff)}s ago`;
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
    return `${Math.round(diff / 86400)}d ago`;
  } catch {
    return "—";
  }
}

export default function NetworkPage() {
  const { setAfterTitle, setEnd } = usePageHeader();
  const [state, setState] = useState<LoadState>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [rules, setRules] = useState<NetworkRule[]>([]);
  const [status, setStatus] = useState<DaemonStatusResponse | null>(null);
  const [drift, setDrift] = useState<DriftListResponse | null>(null);
  const [reconciling, setReconciling] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);

  const load = useCallback(async () => {
    setState((cur) => (cur === "idle" ? "loading" : cur));
    setErrorMsg(null);
    try {
      const [statusResp, rulesResp, driftResp] = await Promise.all([
        encmApi.getStatus(),
        encmApi.listRules(),
        encmApi.listDrift(),
      ]);
      setStatus(statusResp);
      setRules(rulesResp.rules);
      setDrift(driftResp);
      setState("ready");
    } catch (err) {
      if (isDaemonUnreachableError(err)) {
        setState("daemon-down");
      } else {
        setState("error");
        setErrorMsg(err instanceof Error ? err.message : String(err));
      }
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Poll status every 10s so the badges stay live without hammering the
  // daemon. Rules + drift refresh on user action.
  useEffect(() => {
    if (state !== "ready") return;
    const id = setInterval(() => {
      encmApi
        .getStatus()
        .then(setStatus)
        .catch(() => {
          // soft failure — leave existing status, don't tear down the UI
        });
    }, 10000);
    return () => clearInterval(id);
  }, [state]);

  const handleReconcile = useCallback(async () => {
    setReconciling(true);
    try {
      await encmApi.reconcileNow();
      await load();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setReconciling(false);
    }
  }, [load]);

  const handleDelete = useCallback(
    async (rule: NetworkRule) => {
      const confirmed = window.confirm(
        `Delete rule "${rule.metadata.name}"? This removes the YAML file and the next reconcile tick will remove it from sbx.`,
      );
      if (!confirmed) return;
      try {
        await encmApi.deleteRule(
          rule.metadata.name,
          rule.metadata.scope,
          rule.metadata.sandbox_id ?? undefined,
        );
        await load();
      } catch (err) {
        setErrorMsg(err instanceof Error ? err.message : String(err));
      }
    },
    [load],
  );

  const handleDisable = useCallback(
    async (rule: NetworkRule) => {
      try {
        await encmApi.disableRule(
          rule.metadata.name,
          rule.metadata.scope,
          rule.metadata.sandbox_id ?? undefined,
        );
        await load();
      } catch (err) {
        setErrorMsg(err instanceof Error ? err.message : String(err));
      }
    },
    [load],
  );

  const reachable = status?.sandboxd?.reachable ?? false;
  const ruleCount = rules.length;
  const driftCount = drift?.count ?? 0;

  useLayoutEffect(() => {
    setAfterTitle(
      <span className="flex items-center gap-2">
        {state === "loading" && <Spinner className="shrink-0 text-base text-primary" />}
        {state === "ready" && (
          <>
            <Badge tone={reachable ? "success" : "warning"} className="text-[10px]">
              {reachable ? "sandboxd ok" : "sandboxd down"}
            </Badge>
            <Badge tone="secondary" className="text-[10px]">
              {ruleCount} rules
            </Badge>
            {driftCount > 0 && (
              <Badge tone="warning" className="text-[10px]">
                {driftCount} drift
              </Badge>
            )}
          </>
        )}
        {state === "daemon-down" && (
          <Badge tone="destructive" className="text-[10px]">
            daemon offline
          </Badge>
        )}
      </span>,
    );
    setEnd(
      <div className="flex w-full min-w-0 flex-wrap items-center justify-start gap-2 sm:justify-end sm:gap-3">
        <Button
          type="button"
          size="sm"
          onClick={() => setWizardOpen(true)}
          disabled={state !== "ready"}
          prefix={<Plus />}
        >
          Add Rule
        </Button>
        <Button
          type="button"
          size="sm"
          outlined
          onClick={handleReconcile}
          disabled={reconciling || state !== "ready"}
          prefix={reconciling ? <Spinner /> : <RefreshCw />}
        >
          Reconcile
        </Button>
        <Button
          type="button"
          size="sm"
          outlined
          onClick={() => load()}
          disabled={state === "loading"}
          prefix={<RefreshCw />}
        >
          Refresh
        </Button>
      </div>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [
    state,
    reachable,
    ruleCount,
    driftCount,
    reconciling,
    handleReconcile,
    load,
    setAfterTitle,
    setEnd,
  ]);

  if (state === "daemon-down") {
    return <DaemonDownEmptyState onRetry={load} />;
  }

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-4">
      <PluginSlot name="network:top" />

      {errorMsg && (
        <Card className="border-destructive/40 bg-destructive/10">
          <CardContent className="py-3 text-sm text-destructive">
            {errorMsg}
          </CardContent>
        </Card>
      )}

      <StatusCard status={status} loading={state === "loading"} />

      <RulesCard
        rules={rules}
        loading={state === "loading"}
        onDelete={handleDelete}
        onDisable={handleDisable}
      />

      {driftCount > 0 && drift && (
        <DriftCard drift={drift} onImported={() => void load()} />
      )}

      <AuditTimeline />

      <PluginSlot name="network:bottom" />

      <AddRuleWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        onCreated={() => {
          setWizardOpen(false);
          void load();
        }}
      />
    </div>
  );
}

function DaemonDownEmptyState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
      <Plug className="h-10 w-10 text-muted-foreground" />
      <div>
        <h2 className="text-base font-semibold">Sopify daemon is not running</h2>
        <p className="mt-1 max-w-md text-sm text-muted-foreground">
          Start it from a terminal with{" "}
          <code className="rounded bg-secondary/40 px-1.5 py-0.5 text-xs">sopify start</code>{" "}
          and the page will pick up automatically.
        </p>
      </div>
      <Button size="sm" outlined prefix={<RefreshCw />} onClick={onRetry}>
        Check again
      </Button>
    </div>
  );
}

function StatusCard({
  status,
  loading,
}: {
  status: DaemonStatusResponse | null;
  loading: boolean;
}) {
  if (loading && !status) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-6">
          <Spinner />
        </CardContent>
      </Card>
    );
  }
  if (!status) return null;
  const sandboxd = status.sandboxd;
  const reconciler = status.reconciler;
  const ingester = status.audit_ingester;

  return (
    <Card>
      <CardHeader className="py-3 px-4">
        <CardTitle className="text-sm flex items-center gap-2">
          <Shield className="h-4 w-4" />
          Control plane status
        </CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-3 px-4 pb-4 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <StatusCell
          label="sandboxd"
          value={sandboxd?.reachable ? "reachable" : "unreachable"}
          tone={sandboxd?.reachable ? "success" : "warning"}
          detail={sandboxd?.version ? `v${sandboxd.version}` : sandboxd?.error ?? null}
        />
        <StatusCell
          label="reconciler"
          value={reconciler.last_tick_at ? `last tick ${fmtRelative(reconciler.last_tick_at)}` : "no tick yet"}
          tone={reconciler.last_error ? "warning" : "success"}
          detail={reconciler.last_error ?? null}
        />
        <StatusCell
          label="audit ingester"
          value={`${ingester.events_seen} events`}
          tone={ingester.last_error ? "warning" : "success"}
          detail={
            ingester.last_event_at
              ? `last ${fmtRelative(ingester.last_event_at)}`
              : ingester.last_error
          }
        />
        <StatusCell
          label="rules / drift"
          value={`${status.rules.count} / ${status.rules.drift_count}`}
          tone={status.rules.drift_count > 0 ? "warning" : "secondary"}
          detail={`encm_root: ${status.daemon.encm_root}`}
        />
      </CardContent>
    </Card>
  );
}

type Tone = "success" | "warning" | "secondary" | "destructive";

function StatusCell({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail?: string | null;
  tone: Tone;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-muted-foreground text-[10px] uppercase tracking-wide">
        {label}
      </span>
      <Badge tone={tone} className="w-fit text-[10px]">
        {value}
      </Badge>
      {detail && (
        <span className="text-muted-foreground text-[10px] truncate" title={detail}>
          {detail}
        </span>
      )}
    </div>
  );
}

function RulesCard({
  rules,
  loading,
  onDelete,
  onDisable,
}: {
  rules: NetworkRule[];
  loading: boolean;
  onDelete: (r: NetworkRule) => void;
  onDisable: (r: NetworkRule) => void;
}) {
  const sortedRules = useMemo(
    () =>
      [...rules].sort((a, b) => {
        if (a.metadata.scope !== b.metadata.scope) {
          return a.metadata.scope === "global" ? -1 : 1;
        }
        return a.metadata.name.localeCompare(b.metadata.name);
      }),
    [rules],
  );

  return (
    <Card className="min-w-0 max-w-full overflow-hidden">
      <CardHeader className="py-3 px-4">
        <CardTitle className="text-sm flex items-center gap-2">
          <Shield className="h-4 w-4" />
          Network rules
          <span className="text-muted-foreground text-xs font-normal">
            ({rules.length})
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {loading && rules.length === 0 && (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        )}
        {!loading && rules.length === 0 && (
          <div className="py-10 text-center text-sm text-muted-foreground">
            No rules yet. Click{" "}
            <span className="font-medium text-foreground">Add Rule</span>{" "}
            to pick from a template or build a custom one — or use{" "}
            <code className="rounded bg-secondary/40 px-1.5 py-0.5 text-xs">
              sopify rules add
            </code>{" "}
            from the terminal.
          </div>
        )}
        {rules.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[600px] text-xs">
              <thead className="border-b border-current/10">
                <tr className="text-left text-muted-foreground">
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Scope</th>
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium">Decision</th>
                  <th className="px-4 py-2 font-medium">Patterns</th>
                  <th className="px-4 py-2 font-medium">Created</th>
                  <th className="px-4 py-2 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {sortedRules.map((rule) => (
                  <RuleRow
                    key={`${rule.metadata.scope}:${rule.metadata.sandbox_id ?? ""}:${rule.metadata.name}`}
                    rule={rule}
                    onDelete={() => onDelete(rule)}
                    onDisable={() => onDisable(rule)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function RuleRow({
  rule,
  onDelete,
  onDisable,
}: {
  rule: NetworkRule;
  onDelete: () => void;
  onDisable: () => void;
}) {
  const m = rule.metadata;
  const s = rule.spec;
  return (
    <tr className="border-b border-current/5 hover:bg-secondary/10">
      <td className="px-4 py-2 font-mono">{m.name}</td>
      <td className="px-4 py-2">
        <Badge tone={m.scope === "global" ? "secondary" : "outline"} className="text-[10px]">
          {m.scope}
          {m.sandbox_id ? ` · ${m.sandbox_id.slice(0, 8)}` : ""}
        </Badge>
      </td>
      <td className="px-4 py-2">{s.type}</td>
      <td className="px-4 py-2">
        <Badge tone={s.decision === "allow" ? "success" : "destructive"} className="text-[10px]">
          {s.decision}
        </Badge>
      </td>
      <td className="px-4 py-2 max-w-xs">
        <div className="flex flex-wrap gap-1">
          {s.patterns.slice(0, 3).map((p) => (
            <code key={p} className="rounded bg-secondary/30 px-1.5 py-0.5 text-[10px]">
              {p}
            </code>
          ))}
          {s.patterns.length > 3 && (
            <span className="text-muted-foreground text-[10px]">
              +{s.patterns.length - 3} more
            </span>
          )}
        </div>
      </td>
      <td className="px-4 py-2 text-muted-foreground">
        <span title={fmtTime(m.created_at)}>{fmtRelative(m.created_at)}</span>
        {m.created_by && (
          <span className="ml-1 text-muted-foreground/70">by {m.created_by}</span>
        )}
      </td>
      <td className="px-4 py-2">
        <div className="flex justify-end gap-1">
          {s.decision === "allow" && (
            <Button
              type="button"
              size="sm"
              ghost
              onClick={onDisable}
              title="Flip decision to deny (keeps the rule, blocks the traffic)"
            >
              <ShieldOff className="h-3.5 w-3.5" />
            </Button>
          )}
          <Button
            type="button"
            size="sm"
            ghost
            onClick={onDelete}
            title="Delete rule"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </td>
    </tr>
  );
}

function DriftCard({
  drift,
  onImported,
}: {
  drift: DriftListResponse;
  onImported: () => void;
}) {
  const [importingId, setImportingId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleImport = useCallback(
    async (sbxRuleId: string) => {
      setImportingId(sbxRuleId);
      setErrorMsg(null);
      try {
        await encmApi.importDrift(sbxRuleId);
        onImported();
      } catch (err) {
        setErrorMsg(err instanceof Error ? err.message : String(err));
      } finally {
        setImportingId(null);
      }
    },
    [onImported],
  );

  return (
    <Card className="border-warning/40">
      <CardHeader className="py-3 px-4">
        <CardTitle className="text-sm flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-warning" />
          Drift — rules in sbx that ENCM doesn&apos;t track
          <span className="text-muted-foreground text-xs font-normal">
            ({drift.count})
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {errorMsg && (
          <div className="bg-destructive/10 border-b border-destructive/20 px-4 py-2 text-xs text-destructive">
            {errorMsg}
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[500px] text-xs">
            <thead className="border-b border-current/10">
              <tr className="text-left text-muted-foreground">
                <th className="px-4 py-2 font-medium">sbx rule</th>
                <th className="px-4 py-2 font-medium">Detected</th>
                <th className="px-4 py-2 font-medium">Reason</th>
                <th className="px-4 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {drift.drift.map((d) => (
                <tr key={d.sbx_rule_id} className="border-b border-current/5">
                  <td className="px-4 py-2 font-mono">{d.sbx_rule_id}</td>
                  <td className="px-4 py-2 text-muted-foreground">
                    <span title={fmtTime(d.detected_at)}>
                      {fmtRelative(d.detected_at)}
                    </span>
                  </td>
                  <td className="px-4 py-2">{d.reason}</td>
                  <td className="px-4 py-2 text-right">
                    <Button
                      type="button"
                      size="sm"
                      outlined
                      onClick={() => handleImport(d.sbx_rule_id)}
                      disabled={importingId === d.sbx_rule_id}
                      prefix={
                        importingId === d.sbx_rule_id ? <Spinner /> : <Download />
                      }
                      title="Adopt this sbx rule as an ENCM-managed YAML"
                    >
                      Import
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

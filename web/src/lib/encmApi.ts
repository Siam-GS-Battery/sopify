// ENCM (Egress Network Control Module) dashboard API.
//
// Routes hit /api/encm/<path>, which the Hermes web server proxies to the
// local Sopify daemon at 127.0.0.1:7777/api/v1/<path> with a bearer token
// attached server-side (see hermes_cli/encm_client.py). The browser only
// ever sees the dashboard session token.

import { fetchJSON } from "./api";

export interface NetworkRuleMetadata {
  name: string;
  scope: "global" | "sandbox";
  sandbox_id: string | null;
  created_by: string;
  created_at: string;
  labels: Record<string, string>;
}

export interface NetworkRuleSpec {
  type: "domain" | "cidr" | "port";
  patterns: string[];
  decision: "allow" | "deny";
  ttl_seconds: number | null;
}

export interface NetworkRule {
  apiVersion: string;
  kind: "NetworkRule";
  metadata: NetworkRuleMetadata;
  spec: NetworkRuleSpec;
}

export interface RulesListResponse {
  count: number;
  rules: NetworkRule[];
}

export interface CreateRuleRequest {
  name: string;
  patterns: string[];
  decision?: "allow" | "deny";
  rule_type?: "domain" | "cidr" | "port";
  scope?: "global" | "sandbox";
  sandbox_id?: string | null;
  created_by?: string;
  ttl_seconds?: number | null;
  labels?: Record<string, string>;
}

export interface SandboxdHealth {
  reachable: boolean;
  version: string | null;
  socket_path: string | null;
  error: string | null;
}

export interface DaemonStatusResponse {
  daemon: { encm_root: string };
  sandboxd: SandboxdHealth | null;
  reconciler: {
    last_tick_at: string | null;
    last_error: string | null;
  };
  audit_ingester: {
    events_seen: number;
    last_event_at: string | null;
    last_error: string | null;
  };
  rules: {
    count: number;
    drift_count: number;
  };
}

export interface ReconcileResponse {
  applied: number;
  drift_count: number;
  last_reconcile_at: string | null;
}

export interface DriftObservation {
  sbx_rule_id: string;
  detected_at: string;
  reason: string;
}

export interface DriftListResponse {
  count: number;
  drift: DriftObservation[];
}

export interface AuditEvent {
  ts: string;
  src?: string | null;
  host?: string | null;
  decision?: string | null;
  rule_name?: string | null;
  proxy_mode?: string | null;
  // The daemon's payload is open-ended — pass through unknown fields.
  [extra: string]: unknown;
}

export interface AuditQueryResponse {
  count: number;
  events: AuditEvent[];
}

// The proxy returns 503 with this shape when the daemon is not running.
export interface DaemonUnreachable {
  detail: string;
  reachable: false;
}

export const encmApi = {
  listRules: () => fetchJSON<RulesListResponse>("/api/encm/rules"),

  createRule: (body: CreateRuleRequest) =>
    fetchJSON<{ path: string; rule: NetworkRule }>("/api/encm/rules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  getRule: (name: string, scope: "global" | "sandbox" = "global", sandboxId?: string) => {
    const qs = new URLSearchParams({ scope });
    if (sandboxId) qs.set("sandbox_id", sandboxId);
    return fetchJSON<NetworkRule>(`/api/encm/rules/${encodeURIComponent(name)}?${qs}`);
  },

  deleteRule: (name: string, scope: "global" | "sandbox" = "global", sandboxId?: string) => {
    const qs = new URLSearchParams({ scope });
    if (sandboxId) qs.set("sandbox_id", sandboxId);
    return fetchJSON<void>(`/api/encm/rules/${encodeURIComponent(name)}?${qs}`, {
      method: "DELETE",
    });
  },

  disableRule: (name: string, scope: "global" | "sandbox" = "global", sandboxId?: string) => {
    const qs = new URLSearchParams({ scope });
    if (sandboxId) qs.set("sandbox_id", sandboxId);
    return fetchJSON<{ path: string; decision: "deny" }>(
      `/api/encm/rules/${encodeURIComponent(name)}/disable?${qs}`,
      { method: "POST" },
    );
  },

  getStatus: () => fetchJSON<DaemonStatusResponse>("/api/encm/status"),

  reconcileNow: () =>
    fetchJSON<ReconcileResponse>("/api/encm/reconcile", { method: "POST" }),

  listDrift: () => fetchJSON<DriftListResponse>("/api/encm/drift"),

  importDrift: (sbxRuleId: string) =>
    fetchJSON<{ path: string; rule: NetworkRule; imported_from: string }>(
      `/api/encm/drift/${encodeURIComponent(sbxRuleId)}/import`,
      { method: "POST" },
    ),

  queryAudit: (opts?: {
    limit?: number;
    since?: string;
    decision?: string;
    src?: string;
  }) => {
    const qs = new URLSearchParams();
    if (opts?.limit) qs.set("limit", String(opts.limit));
    if (opts?.since) qs.set("since", opts.since);
    if (opts?.decision) qs.set("decision", opts.decision);
    if (opts?.src) qs.set("src", opts.src);
    const q = qs.toString();
    return fetchJSON<AuditQueryResponse>(`/api/encm/audit${q ? "?" + q : ""}`);
  },
};

// Helper for "daemon unreachable" UX. The proxy returns 503 with reachable=false
// when the Sopify daemon isn't running; that's a normal user state, not a bug —
// the dashboard should render a "start the daemon" CTA instead of an error.
export function isDaemonUnreachableError(err: unknown): boolean {
  if (err instanceof Error) {
    return /^503:/.test(err.message);
  }
  return false;
}

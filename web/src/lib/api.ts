// The dashboard can be served either at the root of its host (e.g.
// https://kanban.tilos.com/) or under a URL prefix when reverse-proxied
// (e.g. https://mission-control.tilos.com/hermes/). The Python backend
// injects ``window.__HERMES_BASE_PATH__`` into index.html based on the
// incoming ``X-Forwarded-Prefix`` header so the SPA can address its own
// ``/api/...`` and ``/dashboard-plugins/...`` URLs correctly without a
// rebuild. Empty string means "served at root".
function readBasePath(): string {
  if (typeof window === "undefined") return "";
  const raw = window.__HERMES_BASE_PATH__ ?? "";
  if (!raw) return "";
  // Normalise: ensure leading slash, strip trailing slash.
  const withLead = raw.startsWith("/") ? raw : `/${raw}`;
  return withLead.replace(/\/+$/, "");
}

export const HERMES_BASE_PATH = readBasePath();
const BASE = HERMES_BASE_PATH;


// Ephemeral session token for protected endpoints.
// Injected into index.html by the server — never fetched via API.
declare global {
  interface Window {
    __HERMES_SESSION_TOKEN__?: string;
    __HERMES_BASE_PATH__?: string;
  }
}
let _sessionToken: string | null = null;
const SESSION_HEADER = "X-Hermes-Session-Token";

function setSessionHeader(headers: Headers, token: string): void {
  if (!headers.has(SESSION_HEADER)) {
    headers.set(SESSION_HEADER, token);
  }
}

export async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  // Inject the session token into all /api/ requests.
  const headers = new Headers(init?.headers);
  const token = window.__HERMES_SESSION_TOKEN__;
  if (token) {
    setSessionHeader(headers, token);
  }
  const res = await fetch(`${BASE}${url}`, { ...init, headers });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

async function getSessionToken(): Promise<string> {
  if (_sessionToken) return _sessionToken;
  const injected = window.__HERMES_SESSION_TOKEN__;
  if (injected) {
    _sessionToken = injected;
    return _sessionToken;
  }
  throw new Error("Session token not available — page must be served by the Hermes dashboard server");
}

export const api = {
  getStatus: () => fetchJSON<StatusResponse>("/api/status"),
  getSessions: (limit = 20, offset = 0) =>
    fetchJSON<PaginatedSessions>(`/api/sessions?limit=${limit}&offset=${offset}`),
  getSessionMessages: (id: string) =>
    fetchJSON<SessionMessagesResponse>(`/api/sessions/${encodeURIComponent(id)}/messages`),
  getSessionLatestDescendant: (id: string) =>
    fetchJSON<SessionLatestDescendantResponse>(
      `/api/sessions/${encodeURIComponent(id)}/latest-descendant`,
    ),
  deleteSession: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/sessions/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  getLogs: (params: { file?: string; lines?: number; level?: string; component?: string }) => {
    const qs = new URLSearchParams();
    if (params.file) qs.set("file", params.file);
    if (params.lines) qs.set("lines", String(params.lines));
    if (params.level && params.level !== "ALL") qs.set("level", params.level);
    if (params.component && params.component !== "all") qs.set("component", params.component);
    return fetchJSON<LogsResponse>(`/api/logs?${qs.toString()}`);
  },
  getAnalytics: (days: number) =>
    fetchJSON<AnalyticsResponse>(`/api/analytics/usage?days=${days}`),
  getModelsAnalytics: (days: number) =>
    fetchJSON<ModelsAnalyticsResponse>(`/api/analytics/models?days=${days}`),
  getConfig: () => fetchJSON<Record<string, unknown>>("/api/config"),
  getDefaults: () => fetchJSON<Record<string, unknown>>("/api/config/defaults"),
  getSchema: () => fetchJSON<{ fields: Record<string, unknown>; category_order: string[] }>("/api/config/schema"),
  getModelInfo: () => fetchJSON<ModelInfoResponse>("/api/model/info"),
  getModelOptions: () => fetchJSON<ModelOptionsResponse>("/api/model/options"),
  getAuxiliaryModels: () => fetchJSON<AuxiliaryModelsResponse>("/api/model/auxiliary"),
  setModelAssignment: (body: ModelAssignmentRequest) =>
    fetchJSON<ModelAssignmentResponse>("/api/model/set", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  saveConfig: (config: Record<string, unknown>) =>
    fetchJSON<{ ok: boolean }>("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config }),
    }),
  getConfigRaw: () => fetchJSON<{ yaml: string }>("/api/config/raw"),
  saveConfigRaw: (yaml_text: string) =>
    fetchJSON<{ ok: boolean }>("/api/config/raw", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml_text }),
    }),
  getEnvVars: () => fetchJSON<Record<string, EnvVarInfo>>("/api/env"),
  setEnvVar: (key: string, value: string) =>
    fetchJSON<{ ok: boolean }>("/api/env", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, value }),
    }),
  deleteEnvVar: (key: string) =>
    fetchJSON<{ ok: boolean }>("/api/env", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    }),
  revealEnvVar: async (key: string) => {
    const token = await getSessionToken();
    return fetchJSON<{ key: string; value: string }>("/api/env/reveal", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        [SESSION_HEADER]: token,
      },
      body: JSON.stringify({ key }),
    });
  },

  // Sopify API key upload (per-provider) — see hermes_cli/web_server.py
  // `/api/providers/api-key` endpoints + plugins/sopify_providers/providers_registry.py
  getApiKeyProviders: () =>
    fetchJSON<{ providers: ApiKeyProvider[] }>("/api/providers/api-key"),
  setApiKey: (
    provider_id: string,
    api_key: string,
    sync_to_sbx_secret = true,
  ) =>
    fetchJSON<ApiKeySaveResult>("/api/providers/api-key", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider_id, api_key, sync_to_sbx_secret }),
    }),
  deleteApiKey: (provider_id: string) =>
    fetchJSON<ApiKeyDeleteResult>(
      `/api/providers/api-key/${encodeURIComponent(provider_id)}`,
      { method: "DELETE" },
    ),
  testApiKey: (provider_id: string) =>
    fetchJSON<ApiKeyTestResult>(
      `/api/providers/api-key/test/${encodeURIComponent(provider_id)}`,
      { method: "POST" },
    ),

  // Cron jobs
  getCronJobs: (profile = "all") =>
    fetchJSON<CronJob[]>(`/api/cron/jobs?profile=${encodeURIComponent(profile)}`),
  createCronJob: (job: { prompt: string; schedule: string; name?: string; deliver?: string }, profile = "default") =>
    fetchJSON<CronJob>(`/api/cron/jobs?profile=${encodeURIComponent(profile)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(job),
    }),
  pauseCronJob: (id: string, profile = "default") =>
    fetchJSON<CronJob>(`/api/cron/jobs/${encodeURIComponent(id)}/pause?profile=${encodeURIComponent(profile)}`, { method: "POST" }),
  resumeCronJob: (id: string, profile = "default") =>
    fetchJSON<CronJob>(`/api/cron/jobs/${encodeURIComponent(id)}/resume?profile=${encodeURIComponent(profile)}`, { method: "POST" }),
  triggerCronJob: (id: string, profile = "default") =>
    fetchJSON<CronJob>(`/api/cron/jobs/${encodeURIComponent(id)}/trigger?profile=${encodeURIComponent(profile)}`, { method: "POST" }),
  deleteCronJob: (id: string, profile = "default") =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${encodeURIComponent(id)}?profile=${encodeURIComponent(profile)}`, { method: "DELETE" }),

  // Profiles (minimal)
  getProfiles: () =>
    fetchJSON<{ profiles: ProfileInfo[] }>("/api/profiles"),
  createProfile: (body: { name: string; clone_from_default: boolean }) =>
    fetchJSON<{ ok: boolean; name: string; path: string }>("/api/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  renameProfile: (name: string, newName: string) =>
    fetchJSON<{ ok: boolean; name: string; path: string }>(
      `/api/profiles/${encodeURIComponent(name)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_name: newName }),
      },
    ),
  deleteProfile: (name: string) =>
    fetchJSON<{ ok: boolean }>(
      `/api/profiles/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    ),
  getProfileSetupCommand: (name: string) =>
    fetchJSON<{ command: string }>(
      `/api/profiles/${encodeURIComponent(name)}/setup-command`,
    ),
  getProfileSoul: (name: string) =>
    fetchJSON<{ content: string; exists: boolean }>(
      `/api/profiles/${encodeURIComponent(name)}/soul`,
    ),
  updateProfileSoul: (name: string, content: string) =>
    fetchJSON<{ ok: boolean }>(
      `/api/profiles/${encodeURIComponent(name)}/soul`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      },
    ),

  // Skills & Toolsets
  getSkills: () => fetchJSON<SkillInfo[]>("/api/skills"),
  toggleSkill: (name: string, enabled: boolean) =>
    fetchJSON<{ ok: boolean }>("/api/skills/toggle", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, enabled }),
    }),
  getToolsets: () => fetchJSON<ToolsetInfo[]>("/api/tools/toolsets"),

  // Session search (FTS5)
  searchSessions: (q: string) =>
    fetchJSON<SessionSearchResponse>(`/api/sessions/search?q=${encodeURIComponent(q)}`),

  // OAuth provider management
  getOAuthProviders: () =>
    fetchJSON<OAuthProvidersResponse>("/api/providers/oauth"),
  disconnectOAuthProvider: async (providerId: string) => {
    const token = await getSessionToken();
    return fetchJSON<{ ok: boolean; provider: string }>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}`,
      {
        method: "DELETE",
        headers: { [SESSION_HEADER]: token },
      },
    );
  },
  startOAuthLogin: async (providerId: string) => {
    const token = await getSessionToken();
    return fetchJSON<OAuthStartResponse>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}/start`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          [SESSION_HEADER]: token,
        },
        body: "{}",
      },
    );
  },
  submitOAuthCode: async (providerId: string, sessionId: string, code: string) => {
    const token = await getSessionToken();
    return fetchJSON<OAuthSubmitResponse>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}/submit`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          [SESSION_HEADER]: token,
        },
        body: JSON.stringify({ session_id: sessionId, code }),
      },
    );
  },
  pollOAuthSession: (providerId: string, sessionId: string) =>
    fetchJSON<OAuthPollResponse>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}/poll/${encodeURIComponent(sessionId)}`,
    ),
  cancelOAuthSession: async (sessionId: string) => {
    const token = await getSessionToken();
    return fetchJSON<{ ok: boolean }>(
      `/api/providers/oauth/sessions/${encodeURIComponent(sessionId)}`,
      {
        method: "DELETE",
        headers: { [SESSION_HEADER]: token },
      },
    );
  },

  // Gateway / update actions
  restartGateway: () =>
    fetchJSON<ActionResponse>("/api/gateway/restart", { method: "POST" }),
  updateHermes: () =>
    fetchJSON<ActionResponse>("/api/hermes/update", { method: "POST" }),
  getActionStatus: (name: string, lines = 200) =>
    fetchJSON<ActionStatusResponse>(
      `/api/actions/${encodeURIComponent(name)}/status?lines=${lines}`,
    ),

  // Dashboard plugins
  getPlugins: () =>
    fetchJSON<PluginManifestResponse[]>("/api/dashboard/plugins"),
  rescanPlugins: () =>
    fetchJSON<{ ok: boolean; count: number }>("/api/dashboard/plugins/rescan"),

  getPluginsHub: () => fetchJSON<PluginsHubResponse>("/api/dashboard/plugins/hub"),

  installAgentPlugin: (body: AgentPluginInstallRequest) =>
    fetchJSON<AgentPluginInstallResponse>("/api/dashboard/agent-plugins/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body }),
    }),

  enableAgentPlugin: (name: string) =>
    fetchJSON<{ ok: boolean; name: string; unchanged?: boolean }>(
      `/api/dashboard/agent-plugins/${encodeURIComponent(name)}/enable`,
      { method: "POST" },
    ),

  disableAgentPlugin: (name: string) =>
    fetchJSON<{ ok: boolean; name: string; unchanged?: boolean }>(
      `/api/dashboard/agent-plugins/${encodeURIComponent(name)}/disable`,
      { method: "POST" },
    ),

  updateAgentPlugin: (name: string) =>
    fetchJSON<AgentPluginUpdateResponse>(
      `/api/dashboard/agent-plugins/${encodeURIComponent(name)}/update`,
      { method: "POST" },
    ),

  removeAgentPlugin: (name: string) =>
    fetchJSON<{ ok: boolean; name: string }>(
      `/api/dashboard/agent-plugins/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    ),

  savePluginProviders: (body: PluginProvidersPutRequest) =>
    fetchJSON<{ ok: boolean }>("/api/dashboard/plugin-providers", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  setPluginVisibility: (name: string, hidden: boolean) =>
    fetchJSON<{ ok: boolean; name: string; hidden: boolean }>(
      `/api/dashboard/plugins/${encodeURIComponent(name)}/visibility`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hidden }),
      },
    ),

  // File browser — two roots are exposed by the backend:
  //   "workspace" — the cwd of `sopify dashboard` (= bind-mounted /workspace
  //                 inside the sandbox; what the agent's shell sees).
  //   "hermes"    — HERMES_HOME (~/.hermes inside the sandbox =
  //                 /home/sopify/.hermes/), holding vibe-projects/, state.db,
  //                 dashboard-themes/, plugins/, logs/. Container-local —
  //                 only visible through this API, not on the host disk.
  // All file ops accept ``root`` (default "workspace") so the FilesPage can
  // switch between sections without a separate set of endpoints.
  listFiles: (path: string = "", root: string = "workspace") =>
    fetchJSON<FilesListResponse>(
      `/api/files?path=${encodeURIComponent(path)}&root=${encodeURIComponent(root)}`,
    ),
  readFile: (path: string, root: string = "workspace") =>
    fetchJSON<FilesReadResponse>(
      `/api/files/read?path=${encodeURIComponent(path)}&root=${encodeURIComponent(root)}`,
    ),
  downloadFileUrl: (path: string, root: string = "workspace") => {
    // Subresource loads (<a>, <img>) can't send the X-Hermes-Session-Token
    // header — append the token as ?_token=… so the auth middleware lets
    // the request through. The backend accepts the same token via either
    // transport.
    const token = window.__HERMES_SESSION_TOKEN__ ?? "";
    const qs = new URLSearchParams({ path, root });
    if (token) qs.set("_token", token);
    return `${BASE}/api/files/download?${qs.toString()}`;
  },
  /**
   * URL that renders a workspace file inline (for the Canvas iframe preview).
   * Lives under /preview (outside /api) so the previewed HTML's relative
   * subresources resolve and load without the session token — the backend
   * authenticates this top-level load via ?_token= and sets a scoped cookie
   * for the nested requests. `bust` forces a reload after the agent edits.
   */
  previewUrl: (path: string, bust?: number, inspect?: boolean) => {
    const token = window.__HERMES_SESSION_TOKEN__ ?? "";
    const clean = path.replace(/^\/+/, "");
    const qs = new URLSearchParams();
    if (token) qs.set("_token", token);
    if (bust !== undefined) qs.set("_v", String(bust));
    if (inspect) qs.set("_inspect", "1");
    const query = qs.toString();
    return `${BASE}/preview/${clean.split("/").map(encodeURIComponent).join("/")}${query ? `?${query}` : ""}`;
  },
  // Dev-server manager — lets Live mode start `npm run dev` for the user.
  // Servers are tracked per chat session: switching sessions does NOT kill
  // a running server. The only cross-session interaction is port collision —
  // when a newer session's server claims a port an older session was using,
  // the backend stops the older one so the newer keeps the port.
  startPreviewServer: (sessionId: string, command?: string, cwd?: string) =>
    fetchJSON<{ ok: boolean; pid: number; command: string; session_id: string }>(
      "/api/preview-server/start",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, command, cwd }),
      },
    ),
  previewServerStatus: (sessionId: string) =>
    fetchJSON<{
      running: boolean;
      pid: number | null;
      command: string | null;
      cwd: string | null;
      url: string | null;
      logs: string[];
    }>(`/api/preview-server/status?session_id=${encodeURIComponent(sessionId)}`),
  stopPreviewServer: (sessionId: string) =>
    fetchJSON<{ ok: boolean }>("/api/preview-server/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    }),
  uploadFiles: async (
    path: string,
    files: File[],
    root: string = "workspace",
  ) => {
    const fd = new FormData();
    fd.append("path", path);
    fd.append("root", root);
    for (const f of files) fd.append("files", f, f.name);
    const headers = new Headers();
    const token = window.__HERMES_SESSION_TOKEN__;
    if (token) headers.set(SESSION_HEADER, token);
    const res = await fetch(`${BASE}/api/files/upload`, {
      method: "POST",
      headers,
      body: fd,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText);
      throw new Error(`${res.status}: ${text}`);
    }
    return (await res.json()) as FilesUploadResponse;
  },
  deleteFile: (path: string, root: string = "workspace") =>
    fetchJSON<{ ok: boolean }>(
      `/api/files?path=${encodeURIComponent(path)}&root=${encodeURIComponent(root)}`,
      { method: "DELETE" },
    ),
  renameFile: (src: string, dst: string, root: string = "workspace") =>
    fetchJSON<{ ok: boolean }>("/api/files/rename", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ src, dst, root }),
    }),
  mkdir: (path: string, root: string = "workspace") =>
    fetchJSON<{ ok: boolean; path: string }>("/api/files/mkdir", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, root }),
    }),

  // ── Vibe Code (AI-DLC project scaffolding) ────────────────────────────────
  // Backed by `/api/vibe/*` in web_server.py. `vibeExampleImageUrl` returns
  // a URL string the dashboard can render directly in <img src=...>; the
  // image endpoint enforces the same session-token check as JSON routes.
  listVibeExamples: () =>
    fetchJSON<{ examples: VibeExample[] }>("/api/vibe/examples"),
  vibeExampleImageUrl: (name: string) => {
    // <img src> can't carry the X-Hermes-Session-Token header — the auth
    // middleware accepts ?_token=<token> as a fallback for embeddable URLs.
    const token = window.__HERMES_SESSION_TOKEN__ ?? "";
    const tokenQs = token ? `?_token=${encodeURIComponent(token)}` : "";
    return `${HERMES_BASE_PATH}/api/vibe/examples/${encodeURIComponent(name)}/image.png${tokenQs}`;
  },
  vibePreviewUrl: (name: string) => {
    // iframe src for the Building-phase live preview. Same token-query
    // dance as the image endpoint — the top-level navigation carries the
    // token, the server then sets a /preview-scoped cookie so nested
    // subresource loads (CSS/JS/images) authenticate transparently.
    const token = window.__HERMES_SESSION_TOKEN__ ?? "";
    const tokenQs = token ? `?_token=${encodeURIComponent(token)}` : "";
    return `${HERMES_BASE_PATH}/preview/vibe/${encodeURIComponent(name)}/${tokenQs}`;
  },
  createVibeProject: (body: VibeProjectCreateRequest) =>
    fetchJSON<VibeProjectCreateResponse>("/api/vibe/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  listVibeProjects: () =>
    fetchJSON<{ projects: VibeProjectSummary[] }>("/api/vibe/projects"),
  getVibeProject: (name: string) =>
    fetchJSON<VibeProjectGetResponse>(
      `/api/vibe/projects/${encodeURIComponent(name)}`,
    ),
  patchVibeProject: (
    name: string,
    body: { summary?: string; session_id?: string; phase?: string; engine?: string },
  ) =>
    fetchJSON<{ ok: boolean; project: VibeProjectMarker }>(
      `/api/vibe/projects/${encodeURIComponent(name)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  acceptVibeRequirements: (name: string, content: string) =>
    fetchJSON<{ ok: boolean; project: VibeProjectMarker }>(
      `/api/vibe/projects/${encodeURIComponent(name)}/requirements`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      },
    ),
  acceptVibePlanning: (name: string, content: string) =>
    fetchJSON<{ ok: boolean; project: VibeProjectMarker }>(
      `/api/vibe/projects/${encodeURIComponent(name)}/planning`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      },
    ),
  runVibeSecurityReview: (name: string) =>
    fetchJSON<{ ok: boolean; project: VibeProjectMarker; report: string }>(
      `/api/vibe/projects/${encodeURIComponent(name)}/security-review`,
      { method: "POST" },
    ),
  getVibeSystemPrompt: (name: string) =>
    fetchJSON<{ prompt: string }>(
      `/api/vibe/projects/${encodeURIComponent(name)}/system-prompt`,
    ),
  deleteVibeProject: (name: string) =>
    fetchJSON<{ ok: boolean }>(
      `/api/vibe/projects/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    ),
  uploadVibeFiles: (name: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f, i) => fd.append(`file-${i}`, f, f.name));
    return fetchJSON<VibeUploadResponse>(
      `/api/vibe/projects/${encodeURIComponent(name)}/uploads`,
      { method: "POST", body: fd },
    );
  },
  listVibeUploads: (name: string) =>
    fetchJSON<VibeUploadListResponse>(
      `/api/vibe/projects/${encodeURIComponent(name)}/uploads`,
    ),
  getVibeModels: (name: string) =>
    fetchJSON<VibeModelsResponse>(
      `/api/vibe/projects/${encodeURIComponent(name)}/models`,
    ),
  setVibeModel: (name: string, phase: string, model: string) =>
    fetchJSON<VibeModelUpdateResponse>(
      `/api/vibe/projects/${encodeURIComponent(name)}/models`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phase, model }),
      },
    ),
  /**
   * PR-008 — kill every registered dev-server spec on a given port
   * (across all sessions) + best-effort SIGTERM of an orphan listener.
   * Used by Panel on Static→Live transition so the fixed port 5173
   * doesn't bleed stale state into a freshly-opened preview.
   */
  killDevServerPort: (port: number) =>
    fetchJSON<KillPortResponse>("/api/dev-server/kill-port", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ port }),
    }),
  /**
   * PR-010 — toggle the "addressed" flag for a single security-review
   * finding. The vuln_id is the stable parser-derived ID
   * (category + location slug) so re-runs of the review keep prior
   * acks attached to the same finding text.
   */
  setVibeSecurityFindingAck: (name: string, vulnId: string, addressed: boolean) =>
    fetchJSON<SecurityFindingAckResponse>(
      `/api/vibe/projects/${encodeURIComponent(name)}/security-findings/${encodeURIComponent(vulnId)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ addressed }),
      },
    ),
};

export interface SecurityFindingAckResponse {
  ok: boolean;
  vuln_id: string;
  addressed: boolean;
  addressed_security_findings: string[];
}

export interface KillPortResponse {
  port: number;
  stopped: Array<{ port: number; session_key: string; status: string }>;
  orphan_killed: boolean;
  still_listening: boolean;
}

export interface VibeExample {
  name: string;
  label: string;
  has_image: boolean;
  image_url: string | null;
}

export interface VibeQuestions {
  purpose: string;
  /** "solo" | "team-shared" | "team-isolated" */
  access_mode: string;
  /** Human-readable labels, e.g. "Type it manually". */
  inputs: string[];
  outputs: string[];
  exclusions: string[];
}

export interface VibeProjectCreateRequest {
  name: string;
  mode: string;
  add_ons: string[];
  questions?: VibeQuestions;
}

export type VibePhase =
  | "brainstorm"
  | "design"
  | "backend"
  | "improvement"
  | "security"
  | "approve";

export interface VibeProjectMarker {
  name: string;
  mode: string;
  add_ons: string[];
  created_at: string;
  updated_at?: string;
  phase: VibePhase;
  session_id?: string | null;
  summary?: string;
  /** PR-010 — stable IDs of security-review findings the user has
   * marked as addressed. Persisted on the marker so checks survive
   * reloads and re-runs of the review. */
  addressed_security_findings?: string[];
  /** Chat engine for this project. "claude_code" routes Vibe Code chat to
   * the Claude Code CLI (Surface A); absent/anything else = the Hermes agent. */
  engine?: string | null;
}

export interface VibeProjectSummary {
  name: string;
  mode: string;
  add_ons: string[];
  phase: VibePhase;
  created_at: string | null;
  updated_at: string | null;
}

export interface VibeProjectGetResponse {
  project: VibeProjectMarker;
  path: string;
  requirements_md: string | null;
  design_md: string | null;
  database_md: string | null;
  api_md: string | null;
  /** Legacy field — null for new 6-phase projects. */
  planning_md: string | null;
  security_review_md: string | null;
}

export interface VibeProjectCreateResponse {
  ok: boolean;
  name: string;
  path: string;
  project: VibeProjectMarker;
}

export interface VibeUploadEntry {
  name: string;
  size: number;
}

export interface VibeUploadResponse {
  ok: boolean;
  uploaded: VibeUploadEntry[];
}

export interface VibeUploadListResponse {
  files: VibeUploadEntry[];
}

export interface VibeAvailableModel {
  id: string;        // "provider/model" e.g. "anthropic/claude-sonnet-4-6"
  provider: string;
  label: string;     // human-readable
}

export interface VibeModelsResponse {
  defaults: Record<string, string>;   // phase -> "provider/model"
  overrides: Record<string, string>;  // subset of phases the user customised
  effective: Record<string, string>;  // overrides merged onto defaults
  available: VibeAvailableModel[];
}

export interface VibeModelUpdateResponse {
  ok: boolean;
  overrides: Record<string, string>;
  effective: Record<string, string>;
}

export interface FileEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size: number | null;
  mtime: number;
}

export interface FilesListResponse {
  root: string;
  path: string;
  entries: FileEntry[];
}

export type FilesReadResponse =
  | { binary: false; size: number; content: string }
  | { binary: true; size: number }
  | { too_large: true; size: number; cap: number };

export interface FilesUploadResponse {
  ok: boolean;
  saved: { name: string; path: string; size: number }[];
}

export interface ActionResponse {
  name: string;
  ok: boolean;
  pid: number;
}

export interface ActionStatusResponse {
  exit_code: number | null;
  lines: string[];
  name: string;
  pid: number | null;
  running: boolean;
}

export interface PlatformStatus {
  error_code?: string;
  error_message?: string;
  state: string;
  updated_at: string;
}

export interface StatusResponse {
  active_sessions: number;
  config_path: string;
  config_version: number;
  env_path: string;
  gateway_exit_reason: string | null;
  gateway_health_url: string | null;
  gateway_pid: number | null;
  gateway_platforms: Record<string, PlatformStatus>;
  gateway_running: boolean;
  gateway_state: string | null;
  gateway_updated_at: string | null;
  hermes_home: string;
  latest_config_version: number;
  release_date: string;
  version: string;
}

export interface SessionInfo {
  id: string;
  source: string | null;
  model: string | null;
  title: string | null;
  started_at: number;
  ended_at: number | null;
  last_active: number;
  is_active: boolean;
  message_count: number;
  tool_call_count: number;
  input_tokens: number;
  output_tokens: number;
  preview: string | null;
  parent_session_id?: string | null;
}

export interface SessionLatestDescendantResponse {
  requested_session_id: string;
  session_id: string;
  path: string[];
  changed: boolean;
}

export interface PaginatedSessions {
  sessions: SessionInfo[];
  total: number;
  limit: number;
  offset: number;
}

export interface EnvVarInfo {
  is_set: boolean;
  redacted_value: string | null;
  description: string;
  url: string | null;
  category: string;
  is_password: boolean;
  tools: string[];
  advanced: boolean;
}

/** Provider entry for the API key upload card on /models. */
export interface ApiKeyProvider {
  id: string;
  label: string;
  env_var: string;
  /** sbx secret service name, or null when sbx doesn't manage this provider. */
  sbx_service: string | null;
  key_prefix: string;
  docs_url: string | null;
  set_in_env: boolean;
  set_in_sbx_secret: boolean;
  redacted_value: string | null;
  /** True when the sbx CLI is on PATH on the host. */
  sbx_available: boolean;
  /** True when the backend can write ~/.hermes/.env (the file/dir is
   *  writable by the process).  When false the UI disables Save/Remove and
   *  shows guidance about recreating the sandbox or saving from the host. */
  env_writable: boolean;
}

export interface ApiKeySaveResult {
  ok: boolean;
  provider_id: string;
  synced_to_env: boolean;
  synced_to_sbx_secret: boolean;
  sbx_secret_error: string | null;
  redacted_value: string;
}

export interface ApiKeyDeleteResult {
  ok: boolean;
  provider_id: string;
  removed_from_env: boolean;
  removed_from_sbx_secret: boolean;
  sbx_secret_error: string | null;
}

export interface ApiKeyTestResult {
  tested: boolean;
  ok: boolean;
  http_status?: number;
  reason?: string;
}

export interface SessionMessage {
  role: "user" | "assistant" | "system" | "tool";
  content: string | null;
  tool_calls?: Array<{
    id: string;
    function: { name: string; arguments: string };
  }>;
  tool_name?: string;
  tool_call_id?: string;
  timestamp?: number;
}

export interface SessionMessagesResponse {
  session_id: string;
  messages: SessionMessage[];
}

export interface LogsResponse {
  file: string;
  lines: string[];
}

export interface AnalyticsDailyEntry {
  day: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  reasoning_tokens: number;
  estimated_cost: number;
  actual_cost: number;
  sessions: number;
  api_calls: number;
}

export interface AnalyticsModelEntry {
  model: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  sessions: number;
  api_calls: number;
}

export interface AnalyticsSkillEntry {
  skill: string;
  view_count: number;
  manage_count: number;
  total_count: number;
  percentage: number;
  last_used_at: number | null;
}

export interface AnalyticsSkillsSummary {
  total_skill_loads: number;
  total_skill_edits: number;
  total_skill_actions: number;
  distinct_skills_used: number;
}

export interface AnalyticsResponse {
  daily: AnalyticsDailyEntry[];
  by_model: AnalyticsModelEntry[];
  totals: {
    total_input: number;
    total_output: number;
    total_cache_read: number;
    total_reasoning: number;
    total_estimated_cost: number;
    total_actual_cost: number;
    total_sessions: number;
    total_api_calls: number;
  };
  skills: {
    summary: AnalyticsSkillsSummary;
    top_skills: AnalyticsSkillEntry[];
  };
}

export interface ProfileInfo {
  name: string;
  path: string;
  is_default: boolean;
  model: string | null;
  provider: string | null;
  has_env: boolean;
  skill_count: number;
}

export interface ModelsAnalyticsModelEntry {
  model: string;
  provider: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  reasoning_tokens: number;
  estimated_cost: number;
  actual_cost: number;
  sessions: number;
  api_calls: number;
  tool_calls: number;
  last_used_at: number;
  avg_tokens_per_session: number;
  capabilities: {
    supports_tools?: boolean;
    supports_vision?: boolean;
    supports_reasoning?: boolean;
    context_window?: number;
    max_output_tokens?: number;
    model_family?: string;
  };
}

export interface ModelsAnalyticsResponse {
  models: ModelsAnalyticsModelEntry[];
  totals: {
    distinct_models: number;
    total_input: number;
    total_output: number;
    total_cache_read: number;
    total_reasoning: number;
    total_estimated_cost: number;
    total_actual_cost: number;
    total_sessions: number;
    total_api_calls: number;
  };
  period_days: number;
}

export interface CronJob {
  id: string;
  profile?: string | null;
  profile_name?: string | null;
  hermes_home?: string | null;
  is_default_profile?: boolean;
  name?: string | null;
  prompt?: string | null;
  script?: string | null;
  schedule?: { kind?: string; expr?: string; display?: string };
  schedule_display?: string | null;
  enabled: boolean;
  state?: string | null;
  deliver?: string | null;
  last_run_at?: string | null;
  next_run_at?: string | null;
  last_error?: string | null;
}

export interface SkillInfo {
  name: string;
  description: string;
  category: string;
  enabled: boolean;
}

export interface ToolsetInfo {
  name: string;
  label: string;
  description: string;
  enabled: boolean;
  configured: boolean;
  tools: string[];
}

export interface SessionSearchResult {
  session_id: string;
  snippet: string;
  role: string | null;
  source: string | null;
  model: string | null;
  session_started: number | null;
}

export interface SessionSearchResponse {
  results: SessionSearchResult[];
}

// ── Model info types ──────────────────────────────────────────────────

export interface ModelInfoResponse {
  model: string;
  provider: string;
  auto_context_length: number;
  config_context_length: number;
  effective_context_length: number;
  capabilities: {
    supports_tools?: boolean;
    supports_vision?: boolean;
    supports_reasoning?: boolean;
    context_window?: number;
    max_output_tokens?: number;
    model_family?: string;
  };
}

// ── Model options / assignment types ──────────────────────────────────

export interface ModelOptionProvider {
  name: string;
  slug: string;
  models?: string[];
  total_models?: number;
  is_current?: boolean;
  is_user_defined?: boolean;
  source?: string;
  warning?: string;
}

export interface ModelOptionsResponse {
  model?: string;
  provider?: string;
  providers?: ModelOptionProvider[];
}

export interface AuxiliaryTaskAssignment {
  task: string;
  provider: string;
  model: string;
  base_url: string;
}

export interface AuxiliaryModelsResponse {
  tasks: AuxiliaryTaskAssignment[];
  main: { provider: string; model: string };
}

export interface ModelAssignmentRequest {
  scope: "main" | "auxiliary";
  provider: string;
  model: string;
  /** For auxiliary: task slot name, "" for all, "__reset__" to reset all. */
  task?: string;
}

export interface ModelAssignmentResponse {
  ok: boolean;
  scope?: string;
  provider?: string;
  model?: string;
  tasks?: string[];
  reset?: boolean;
}

// ── OAuth provider types ────────────────────────────────────────────────

export interface OAuthProviderStatus {
  logged_in: boolean;
  source?: string | null;
  source_label?: string | null;
  token_preview?: string | null;
  expires_at?: string | null;
  has_refresh_token?: boolean;
  last_refresh?: string | null;
  error?: string;
}

export interface OAuthProvider {
  id: string;
  name: string;
  /** "pkce" (browser redirect + paste code), "device_code" (show code + URL),
   *  or "external" (delegated to a separate CLI like Claude Code or Qwen). */
  flow: "pkce" | "device_code" | "external";
  cli_command: string;
  docs_url: string;
  status: OAuthProviderStatus;
}

export interface OAuthProvidersResponse {
  providers: OAuthProvider[];
}

/** Discriminated union — the shape of /start depends on the flow. */
export type OAuthStartResponse =
  | {
      session_id: string;
      flow: "pkce";
      auth_url: string;
      expires_in: number;
    }
  | {
      session_id: string;
      flow: "device_code";
      user_code: string;
      verification_url: string;
      expires_in: number;
      poll_interval: number;
    };

export interface OAuthSubmitResponse {
  ok: boolean;
  status: "approved" | "error";
  message?: string;
}

export interface OAuthPollResponse {
  session_id: string;
  status: "pending" | "approved" | "denied" | "expired" | "error";
  error_message?: string | null;
  expires_at?: number | null;
}

// ── Dashboard theme types ──────────────────────────────────────────────

// ── Dashboard plugin types ─────────────────────────────────────────────

export interface PluginManifestResponse {
  name: string;
  label: string;
  description: string;
  icon: string;
  version: string;
  tab: {
    path: string;
    position?: string;
    override?: string;
    hidden?: boolean;
  };
  slots?: string[];
  entry: string;
  css?: string | null;
  has_api: boolean;
  source: string;
}

export interface HubAgentPluginRow {
  name: string;
  version: string;
  description: string;
  source: string;
  runtime_status: "disabled" | "enabled" | "inactive";
  has_dashboard_manifest: boolean;
  dashboard_manifest: PluginManifestResponse | null;
  path: string;
  can_remove: boolean;
  can_update_git: boolean;
  auth_required: boolean;
  auth_command: string;
  user_hidden: boolean;
}

export interface PluginsHubProviders {
  memory_provider: string;
  memory_options: Array<{ name: string; description: string }>;
  context_engine: string;
  context_options: Array<{ name: string; description: string }>;
}

export interface PluginsHubResponse {
  plugins: HubAgentPluginRow[];
  orphan_dashboard_plugins: PluginManifestResponse[];
  providers: PluginsHubProviders;
}

export interface AgentPluginInstallRequest {
  identifier: string;
  force?: boolean;
  enable?: boolean;
}

export interface AgentPluginInstallResponse {
  ok: boolean;
  plugin_name?: string;
  warnings?: string[];
  missing_env?: string[];
  after_install_path?: string | null;
  enabled?: boolean;
  error?: string;
}

export interface AgentPluginUpdateResponse {
  ok: boolean;
  name?: string;
  output?: string;
  unchanged?: boolean;
  error?: string;
}

export interface PluginProvidersPutRequest {
  memory_provider?: string;
  context_engine?: string;
}

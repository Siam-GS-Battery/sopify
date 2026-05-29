import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Key,
  KeyRound,
  Eye,
  EyeOff,
  Check,
  X as XIcon,
  ExternalLink,
  RefreshCw,
  Trash2,
  ShieldCheck,
  Loader2,
} from "lucide-react";
import { api, type ApiKeyProvider } from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Badge } from "@nous-research/ui/ui/components/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

interface Props {
  onError?: (msg: string) => void;
  onSuccess?: (msg: string) => void;
}

type RowState = "idle" | "saving" | "testing";

interface PendingEdit {
  providerId: string;
  value: string;
  reveal: boolean;
}

/** True when `value` looks plausibly like the expected key shape. */
function validatePrefix(value: string, prefix: string): boolean {
  if (!prefix) return true;
  return value.trim().startsWith(prefix);
}

export function ApiKeyUploadCard({ onError, onSuccess }: Props) {
  const [providers, setProviders] = useState<ApiKeyProvider[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [edits, setEdits] = useState<Record<string, PendingEdit>>({});
  const [rowState, setRowState] = useState<Record<string, RowState>>({});
  const [testResults, setTestResults] = useState<
    Record<string, { ok: boolean; reason?: string }>
  >({});
  const [removeTarget, setRemoveTarget] = useState<ApiKeyProvider | null>(null);

  const onErrorRef = useRef(onError);
  const onSuccessRef = useRef(onSuccess);
  onErrorRef.current = onError;
  onSuccessRef.current = onSuccess;

  const refresh = useCallback(() => {
    setLoading(true);
    api
      .getApiKeyProviders()
      .then((resp) => setProviders(resp.providers))
      .catch((e) => onErrorRef.current?.(`Failed to load providers: ${e}`))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const counts = useMemo(() => {
    if (!providers) return { configured: 0, total: 0 };
    return {
      configured: providers.filter((p) => p.set_in_env).length,
      total: providers.length,
    };
  }, [providers]);

  // When ~/.hermes/.env is on a read-only mount (legacy sandbox built with
  // the old :ro flag, or a host with RO home) Save/Remove will 409 — gate
  // the controls and show guidance to recreate the sandbox or save on host.
  const envWritable = providers?.[0]?.env_writable ?? true;

  const startEdit = useCallback(
    (providerId: string) =>
      setEdits((cur) => ({
        ...cur,
        [providerId]: { providerId, value: "", reveal: false },
      })),
    [],
  );

  const cancelEdit = useCallback(
    (providerId: string) =>
      setEdits((cur) => {
        const next = { ...cur };
        delete next[providerId];
        return next;
      }),
    [],
  );

  const updateEdit = useCallback(
    (providerId: string, patch: Partial<PendingEdit>) =>
      setEdits((cur) =>
        cur[providerId]
          ? { ...cur, [providerId]: { ...cur[providerId], ...patch } }
          : cur,
      ),
    [],
  );

  const handleSave = useCallback(
    async (provider: ApiKeyProvider) => {
      const edit = edits[provider.id];
      if (!edit) return;
      const trimmed = edit.value.trim();
      if (!trimmed) {
        onErrorRef.current?.("API key is empty");
        return;
      }
      if (!validatePrefix(trimmed, provider.key_prefix)) {
        onErrorRef.current?.(
          `Key for ${provider.label} should start with "${provider.key_prefix}"`,
        );
        return;
      }

      setRowState((s) => ({ ...s, [provider.id]: "saving" }));
      try {
        const res = await api.setApiKey(provider.id, trimmed, true);
        if (!res.ok) {
          onErrorRef.current?.(`Failed to save ${provider.label} key`);
          return;
        }
        if (res.sbx_secret_error) {
          onErrorRef.current?.(
            `${provider.label} key saved to .env, but sbx secret store failed: ${res.sbx_secret_error}`,
          );
        } else {
          const where = res.synced_to_sbx_secret
            ? "saved to .env + sbx secret store"
            : "saved to .env";
          onSuccessRef.current?.(`${provider.label} key ${where}`);
        }
        cancelEdit(provider.id);
        // Auto-test if supported (anthropic/openai/alibaba).
        if (
          provider.id === "anthropic" ||
          provider.id === "openai" ||
          provider.id === "alibaba"
        ) {
          setRowState((s) => ({ ...s, [provider.id]: "testing" }));
          try {
            const t = await api.testApiKey(provider.id);
            setTestResults((tr) => ({
              ...tr,
              [provider.id]: { ok: t.ok, reason: t.reason },
            }));
            if (t.ok) {
              onSuccessRef.current?.(`${provider.label} key verified`);
            } else if (t.reason) {
              onErrorRef.current?.(
                `${provider.label} test failed: ${t.reason}`,
              );
            }
          } catch (e) {
            setTestResults((tr) => ({
              ...tr,
              [provider.id]: { ok: false, reason: String(e) },
            }));
          }
        }
        refresh();
      } catch (e) {
        onErrorRef.current?.(`Save failed: ${e}`);
      } finally {
        setRowState((s) => {
          const next = { ...s };
          delete next[provider.id];
          return next;
        });
      }
    },
    [edits, cancelEdit, refresh],
  );

  const handleTest = useCallback(async (provider: ApiKeyProvider) => {
    setRowState((s) => ({ ...s, [provider.id]: "testing" }));
    try {
      const t = await api.testApiKey(provider.id);
      setTestResults((tr) => ({
        ...tr,
        [provider.id]: { ok: t.ok, reason: t.reason },
      }));
      if (t.ok) {
        onSuccessRef.current?.(`${provider.label} key verified`);
      } else if (t.tested) {
        onErrorRef.current?.(
          `${provider.label} test failed${t.reason ? `: ${t.reason}` : ""}`,
        );
      }
    } catch (e) {
      onErrorRef.current?.(`Test failed: ${e}`);
    } finally {
      setRowState((s) => {
        const next = { ...s };
        delete next[provider.id];
        return next;
      });
    }
  }, []);

  const handleRemove = useCallback(async () => {
    if (!removeTarget) return;
    const provider = removeTarget;
    setRemoveTarget(null);
    setRowState((s) => ({ ...s, [provider.id]: "saving" }));
    try {
      await api.deleteApiKey(provider.id);
      onSuccessRef.current?.(`${provider.label} key removed`);
      setTestResults((tr) => {
        const next = { ...tr };
        delete next[provider.id];
        return next;
      });
      refresh();
    } catch (e) {
      onErrorRef.current?.(`Remove failed: ${e}`);
    } finally {
      setRowState((s) => {
        const next = { ...s };
        delete next[provider.id];
        return next;
      });
    }
  }, [removeTarget, refresh]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <KeyRound className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">API Keys</CardTitle>
          </div>
          <Button
            size="sm"
            outlined
            onClick={refresh}
            disabled={loading}
            prefix={loading ? <Spinner /> : <RefreshCw />}
          >
            Refresh
          </Button>
        </div>
        <CardDescription>
          Upload provider API keys without leaving the dashboard.
          {!envWritable ? (
            <>
              {" "}
              <span className="text-destructive">
                <code>~/.hermes/.env</code> is read-only — keys can't be
                saved from here.
              </span>{" "}
              Recreate the sandbox (<code>sbx rm &lt;sandbox-name&gt;</code>{" "}
              then restart the dashboard) so the new <code>:rw</code> mount
              takes effect, or set keys from the host with{" "}
              <code>sopify api-key set &lt;provider&gt;</code>.
            </>
          ) : providers && providers[0]?.sbx_available !== false ? (
            <>
              {" "}
              Keys sync to <code>~/.hermes/.env</code> and the sbx secret store
              automatically — no sandbox restart needed.
            </>
          ) : (
            <>
              {" "}
              Keys are saved to <code>~/.hermes/.env</code> and take effect
              immediately. To also store them in the host's sbx secret store
              (for centralized proxy auth), run{" "}
              <code>sbx secret set -g &lt;provider&gt;</code> on your host
              terminal.
            </>
          )}{" "}
          <span className="text-foreground/70">
            {counts.configured}/{counts.total} configured
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading && providers === null && (
          <div className="flex items-center justify-center py-8">
            <Spinner className="text-xl text-primary" />
          </div>
        )}
        <div className="flex flex-col divide-y divide-border">
          {providers?.map((p) => {
            const edit = edits[p.id];
            const state = rowState[p.id] ?? "idle";
            const test = testResults[p.id];
            const prefixOk = !edit || validatePrefix(edit.value, p.key_prefix);
            return (
              <div key={p.id} className="py-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <Key className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium">{p.label}</span>
                        {p.set_in_env ? (
                          <Badge tone="default" className="text-[10px]">
                            <Check className="mr-1 h-3 w-3" /> Active
                          </Badge>
                        ) : (
                          <Badge tone="outline" className="text-[10px]">
                            Not set
                          </Badge>
                        )}
                        {p.set_in_sbx_secret && (
                          <Badge
                            tone="secondary"
                            className="text-[10px]"
                            title="Synced to sbx secret store"
                          >
                            <ShieldCheck className="mr-1 h-3 w-3" /> sbx
                          </Badge>
                        )}
                        {test?.ok === true && (
                          <Badge tone="default" className="text-[10px]">
                            <Check className="mr-1 h-3 w-3" /> Verified
                          </Badge>
                        )}
                        {test?.ok === false && (
                          <Badge tone="destructive" className="text-[10px]">
                            <XIcon className="mr-1 h-3 w-3" /> Test failed
                          </Badge>
                        )}
                      </div>
                      <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                        <code className="font-mono">{p.env_var}</code>
                        {p.redacted_value && (
                          <span className="font-mono">{p.redacted_value}</span>
                        )}
                        {p.docs_url && (
                          <a
                            href={p.docs_url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-0.5 text-primary hover:underline"
                          >
                            Get key <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {!edit && (
                      <>
                        {p.set_in_env &&
                          (p.id === "anthropic" ||
                            p.id === "openai" ||
                            p.id === "alibaba") && (
                            <Button
                              size="sm"
                              outlined
                              onClick={() => handleTest(p)}
                              disabled={state !== "idle"}
                              prefix={
                                state === "testing" ? <Loader2 /> : undefined
                              }
                            >
                              Test
                            </Button>
                          )}
                        <Button
                          size="sm"
                          outlined
                          onClick={() => startEdit(p.id)}
                          disabled={state !== "idle" || !envWritable}
                          title={
                            !envWritable
                              ? "~/.hermes/.env is read-only — recreate the sandbox or save on host"
                              : undefined
                          }
                        >
                          {p.set_in_env ? "Update" : "Add key"}
                        </Button>
                        {p.set_in_env && (
                          <Button
                            size="sm"
                            outlined
                            onClick={() => setRemoveTarget(p)}
                            disabled={state !== "idle" || !envWritable}
                            prefix={<Trash2 />}
                            aria-label={`Remove ${p.label} key`}
                            title={
                              !envWritable
                                ? "~/.hermes/.env is read-only — recreate the sandbox or remove on host"
                                : undefined
                            }
                          />
                        )}
                      </>
                    )}
                  </div>
                </div>
                {edit && (
                  <div className="mt-3 flex flex-col gap-2">
                    <div className="flex items-center gap-2">
                      <Input
                        type={edit.reveal ? "text" : "password"}
                        autoComplete="off"
                        spellCheck={false}
                        placeholder={
                          p.key_prefix
                            ? `${p.key_prefix}...`
                            : "Paste API key here"
                        }
                        value={edit.value}
                        onChange={(e) =>
                          updateEdit(p.id, { value: e.target.value })
                        }
                        className="font-mono text-xs"
                        autoFocus
                      />
                      <Button
                        size="sm"
                        outlined
                        onClick={() =>
                          updateEdit(p.id, { reveal: !edit.reveal })
                        }
                        prefix={edit.reveal ? <EyeOff /> : <Eye />}
                        aria-label={edit.reveal ? "Hide key" : "Show key"}
                      />
                    </div>
                    {edit.value && !prefixOk && (
                      <p className="text-xs text-destructive">
                        Expected prefix "{p.key_prefix}" — double-check this is
                        a {p.label} key.
                      </p>
                    )}
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs text-muted-foreground">
                        Stored in <code>~/.hermes/.env</code>
                        {p.sbx_service && p.sbx_available && (
                          <> and synced to sbx secret store</>
                        )}
                        .
                      </p>
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          outlined
                          onClick={() => cancelEdit(p.id)}
                          disabled={state !== "idle"}
                        >
                          Cancel
                        </Button>
                        <Button
                          size="sm"
                          onClick={() => handleSave(p)}
                          disabled={
                            state !== "idle" || !edit.value.trim() || !prefixOk
                          }
                          prefix={
                            state === "saving" ? <Spinner /> : <Check />
                          }
                        >
                          Save
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </CardContent>
      <ConfirmDialog
        open={removeTarget !== null}
        title={`Remove ${removeTarget?.label ?? ""} key?`}
        description={`This removes ${removeTarget?.env_var ?? ""} from ~/.hermes/.env${
          removeTarget?.sbx_service ? " and the sbx secret store" : ""
        }. You can re-add it any time.`}
        confirmLabel="Remove"
        destructive
        onConfirm={handleRemove}
        onCancel={() => setRemoveTarget(null)}
      />
    </Card>
  );
}

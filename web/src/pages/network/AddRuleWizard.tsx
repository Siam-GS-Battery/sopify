import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowLeft,
  Boxes,
  Building2,
  Code2,
  Database,
  GitBranch,
  Globe,
  Lock,
  MessageCircle,
  Package,
  Pencil,
  Server,
  Sparkles,
  X,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import {
  encmApi,
  type CreateRuleRequest,
} from "@/lib/encmApi";

interface RuleTemplate {
  id: string;
  label: string;
  description: string;
  icon: LucideIcon;
  patterns: string[];
  decision: "allow" | "deny";
  rule_type: "domain" | "cidr" | "port";
  default_name: string;
}

// 10 curated templates covering the common Non-Dev use cases listed in
// SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md §4.1. Selecting one skips the
// custom form and goes straight to the preview step — true 1-click flow.
const TEMPLATES: RuleTemplate[] = [
  {
    id: "anthropic",
    label: "Anthropic API",
    description: "Claude (claude.ai, api.anthropic.com)",
    icon: Sparkles,
    patterns: ["*.anthropic.com", "api.anthropic.com"],
    decision: "allow",
    rule_type: "domain",
    default_name: "allow-anthropic",
  },
  {
    id: "openai",
    label: "OpenAI",
    description: "ChatGPT, GPT-4 API",
    icon: Sparkles,
    patterns: ["api.openai.com", "*.openai.com"],
    decision: "allow",
    rule_type: "domain",
    default_name: "allow-openai",
  },
  {
    id: "github",
    label: "GitHub",
    description: "Source + API + Actions",
    icon: GitBranch,
    patterns: ["github.com", "*.github.com", "api.github.com", "raw.githubusercontent.com"],
    decision: "allow",
    rule_type: "domain",
    default_name: "allow-github",
  },
  {
    id: "pypi-npm",
    label: "PyPI + npm",
    description: "Package registries",
    icon: Package,
    patterns: [
      "pypi.org",
      "files.pythonhosted.org",
      "registry.npmjs.org",
      "*.npmjs.org",
    ],
    decision: "allow",
    rule_type: "domain",
    default_name: "allow-pypi-npm",
  },
  {
    id: "microsoft-365",
    label: "Microsoft 365",
    description: "Office, Teams, Outlook (full suite)",
    icon: Building2,
    patterns: [
      "*.office.com",
      "*.office365.com",
      "*.microsoftonline.com",
      "*.microsoft.com",
    ],
    decision: "allow",
    rule_type: "domain",
    default_name: "allow-microsoft-365",
  },
  {
    id: "sharepoint",
    label: "SharePoint",
    description: "Document libraries only",
    icon: Building2,
    patterns: ["*.sharepoint.com", "*.sharepointonline.com"],
    decision: "allow",
    rule_type: "domain",
    default_name: "allow-sharepoint",
  },
  {
    id: "postgresql",
    label: "PostgreSQL",
    description: "Default port 5432",
    icon: Database,
    patterns: ["db.internal.gsbattery.local:5432"],
    decision: "allow",
    rule_type: "port",
    default_name: "allow-postgres",
  },
  {
    id: "mysql",
    label: "MySQL",
    description: "Default port 3306",
    icon: Database,
    patterns: ["db.internal.gsbattery.local:3306"],
    decision: "allow",
    rule_type: "port",
    default_name: "allow-mysql",
  },
  {
    id: "mqtt-broker",
    label: "MQTT Broker",
    description: "Default port 1883 (IoT)",
    icon: MessageCircle,
    patterns: ["mqtt.internal.gsbattery.local:1883"],
    decision: "allow",
    rule_type: "port",
    default_name: "allow-mqtt",
  },
  {
    id: "gs-internal",
    label: "GS Internal",
    description: "*.gsbattery.local + *.gsbattery.co.th",
    icon: Server,
    patterns: ["*.gsbattery.local", "*.gsbattery.co.th"],
    decision: "allow",
    rule_type: "domain",
    default_name: "allow-gs-internal",
  },
];

type Step = "pick" | "custom-form" | "preview";

interface AddRuleWizardProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export function AddRuleWizard({ open, onClose, onCreated }: AddRuleWizardProps) {
  const [step, setStep] = useState<Step>("pick");
  const [pendingRule, setPendingRule] = useState<CreateRuleRequest | null>(null);
  const [pendingSource, setPendingSource] = useState<"template" | "custom" | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const reset = useCallback(() => {
    setStep("pick");
    setPendingRule(null);
    setPendingSource(null);
    setSubmitting(false);
    setError(null);
  }, []);

  // Close on ESC, restore body scroll on close.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !submitting) onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose, submitting]);

  // Reset internal state every time the wizard reopens. Otherwise a user
  // who closes during preview would land on preview the next time they
  // open it, with stale data attached.
  useEffect(() => {
    if (open) reset();
  }, [open, reset]);

  const handlePickTemplate = useCallback((tpl: RuleTemplate) => {
    setPendingRule({
      name: tpl.default_name,
      patterns: tpl.patterns,
      decision: tpl.decision,
      rule_type: tpl.rule_type,
      scope: "global",
      sandbox_id: null,
      created_by: "dashboard",
      labels: { template: tpl.id },
    });
    setPendingSource("template");
    setStep("preview");
  }, []);

  const handleCustomReady = useCallback((rule: CreateRuleRequest) => {
    setPendingRule(rule);
    setPendingSource("custom");
    setStep("preview");
  }, []);

  const handleSave = useCallback(async () => {
    if (!pendingRule) return;
    setSubmitting(true);
    setError(null);
    try {
      await encmApi.createRule(pendingRule);
      onCreated();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }, [pendingRule, onCreated, onClose]);

  if (!open) return null;

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="add-rule-title"
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
      className={cn(
        "fixed inset-0 z-50 flex items-center justify-center",
        "bg-black/60 backdrop-blur-sm",
        "animate-[fade-in_150ms_ease-out]",
      )}
    >
      <div
        ref={dialogRef}
        className={cn(
          "relative w-full max-w-2xl mx-4 max-h-[90vh] flex flex-col",
          "border border-border bg-card shadow-lg",
          "animate-[dialog-in_180ms_ease-out]",
        )}
      >
        <Header
          step={step}
          onBack={step === "pick" ? null : () => setStep(step === "preview" && pendingSource === "template" ? "pick" : step === "preview" ? "custom-form" : "pick")}
          onClose={submitting ? () => {} : onClose}
        />

        <div className="flex-1 min-h-0 overflow-y-auto p-4">
          {step === "pick" && (
            <PickStep
              onPickTemplate={handlePickTemplate}
              onGoCustom={() => setStep("custom-form")}
            />
          )}
          {step === "custom-form" && (
            <CustomFormStep
              initial={pendingRule}
              onReady={handleCustomReady}
              onCancel={() => setStep("pick")}
            />
          )}
          {step === "preview" && pendingRule && (
            <PreviewStep
              rule={pendingRule}
              source={pendingSource}
              error={error}
            />
          )}
        </div>

        {step === "preview" && pendingRule && (
          <div className="flex items-center justify-end gap-2 p-3 border-t border-border">
            <Button
              type="button"
              outlined
              onClick={() => setStep(pendingSource === "template" ? "pick" : "custom-form")}
              disabled={submitting}
            >
              Back
            </Button>
            <Button
              type="button"
              onClick={handleSave}
              disabled={submitting}
              prefix={submitting ? <Spinner /> : undefined}
            >
              {submitting ? "Saving…" : "Save Rule"}
            </Button>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

function Header({
  step,
  onBack,
  onClose,
}: {
  step: Step;
  onBack: (() => void) | null;
  onClose: () => void;
}) {
  const titles: Record<Step, string> = {
    pick: "Add a network rule",
    "custom-form": "Custom rule",
    preview: "Review & save",
  };
  const stepNum = step === "pick" ? 1 : step === "custom-form" ? 2 : 3;
  return (
    <div className="flex items-center gap-3 p-4 border-b border-border">
      {onBack && (
        <Button
          ghost
          size="icon"
          onClick={onBack}
          aria-label="Back"
          className="shrink-0"
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
      )}
      <div className="flex-1 min-w-0">
        <h2
          id="add-rule-title"
          className="font-expanded text-sm font-bold tracking-[0.08em] uppercase blend-lighter"
        >
          {titles[step]}
        </h2>
        <p className="font-mondwest text-[10px] text-muted-foreground tracking-wide">
          Step {stepNum} of 3
        </p>
      </div>
      <Button
        ghost
        size="icon"
        onClick={onClose}
        aria-label="Close"
        className="shrink-0"
      >
        <X className="h-4 w-4" />
      </Button>
    </div>
  );
}

function PickStep({
  onPickTemplate,
  onGoCustom,
}: {
  onPickTemplate: (tpl: RuleTemplate) => void;
  onGoCustom: () => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-muted-foreground">
        Pick a common service to allow with one click, or set up a custom rule
        below.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {TEMPLATES.map((tpl) => (
          <TemplateCard key={tpl.id} tpl={tpl} onClick={() => onPickTemplate(tpl)} />
        ))}
      </div>

      <button
        type="button"
        onClick={onGoCustom}
        className={cn(
          "flex items-center gap-3 px-3 py-3 text-left",
          "border border-dashed border-border",
          "hover:border-foreground/40 hover:bg-secondary/20 transition-colors",
        )}
      >
        <Pencil className="h-4 w-4 shrink-0 text-muted-foreground" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium">Custom rule</div>
          <div className="text-[11px] text-muted-foreground">
            Specify hostname, decision, and scope manually
          </div>
        </div>
      </button>
    </div>
  );
}

function TemplateCard({
  tpl,
  onClick,
}: {
  tpl: RuleTemplate;
  onClick: () => void;
}) {
  const Icon = tpl.icon;
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-start gap-3 px-3 py-3 text-left",
        "border border-border bg-background/40",
        "hover:border-foreground/40 hover:bg-secondary/20 transition-colors",
      )}
    >
      <Icon className="h-4 w-4 shrink-0 text-foreground/70 mt-0.5" />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate">{tpl.label}</div>
        <div className="text-[11px] text-muted-foreground truncate">
          {tpl.description}
        </div>
      </div>
    </button>
  );
}

interface CustomFormState {
  name: string;
  patterns: string;
  decision: "allow" | "deny";
  rule_type: "domain" | "cidr" | "port";
  scope: "global" | "sandbox";
  sandbox_id: string;
}

function CustomFormStep({
  initial,
  onReady,
  onCancel,
}: {
  initial: CreateRuleRequest | null;
  onReady: (rule: CreateRuleRequest) => void;
  onCancel: () => void;
}) {
  const [state, setState] = useState<CustomFormState>(() => ({
    name: initial?.name ?? "",
    patterns: (initial?.patterns ?? []).join("\n"),
    decision: (initial?.decision as "allow" | "deny") ?? "allow",
    rule_type: (initial?.rule_type as "domain" | "cidr" | "port") ?? "domain",
    scope: (initial?.scope as "global" | "sandbox") ?? "global",
    sandbox_id: initial?.sandbox_id ?? "",
  }));
  const [touched, setTouched] = useState(false);

  const patternsParsed = useMemo(
    () =>
      state.patterns
        .split(/\r?\n/)
        .map((s) => s.trim())
        .filter(Boolean),
    [state.patterns],
  );

  const nameError = useMemo(() => {
    if (!touched) return null;
    if (!state.name) return "Name is required";
    if (!/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/.test(state.name)) {
      return "Use lowercase letters, digits, and dashes (RFC 1123)";
    }
    return null;
  }, [state.name, touched]);

  const patternsError = useMemo(() => {
    if (!touched) return null;
    if (patternsParsed.length === 0) return "At least one pattern is required";
    return null;
  }, [patternsParsed, touched]);

  const sandboxError = useMemo(() => {
    if (!touched) return null;
    if (state.scope === "sandbox" && !state.sandbox_id.trim()) {
      return "Sandbox ID is required when scope is sandbox";
    }
    return null;
  }, [state.scope, state.sandbox_id, touched]);

  const canSubmit = !nameError && !patternsError && !sandboxError;

  const handleSubmit = () => {
    setTouched(true);
    if (!canSubmit && touched) return;
    if (!state.name || patternsParsed.length === 0) return;
    if (state.scope === "sandbox" && !state.sandbox_id.trim()) return;
    onReady({
      name: state.name,
      patterns: patternsParsed,
      decision: state.decision,
      rule_type: state.rule_type,
      scope: state.scope,
      sandbox_id: state.scope === "sandbox" ? state.sandbox_id.trim() : null,
      created_by: "dashboard",
      labels: {},
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-muted-foreground">
        Build a rule from scratch. The reconciler will apply it to sbx within
        30 seconds of save.
      </p>

      <Field
        label="Name"
        hint="Unique within scope. Lowercase, digits, dashes."
        error={nameError}
      >
        <Input
          autoFocus
          value={state.name}
          onChange={(e) => setState({ ...state, name: e.target.value })}
          placeholder="allow-anthropic"
          onBlur={() => setTouched(true)}
        />
      </Field>

      <Field
        label="Patterns (one per line)"
        hint="Domain glob (`*.example.com`), CIDR (`10.0.0.0/24`), or IP:port (`10.0.0.5:5432`)."
        error={patternsError}
      >
        <textarea
          value={state.patterns}
          onChange={(e) => setState({ ...state, patterns: e.target.value })}
          onBlur={() => setTouched(true)}
          rows={4}
          placeholder={"*.anthropic.com\napi.anthropic.com"}
          className={cn(
            "flex w-full border border-border bg-background/40 px-3 py-2 font-courier text-sm transition-colors",
            "placeholder:text-muted-foreground",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-foreground/30 focus-visible:border-foreground/25",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        />
      </Field>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Field label="Type">
          <SelectRow
            value={state.rule_type}
            options={[
              { value: "domain", label: "Domain" },
              { value: "cidr", label: "CIDR" },
              { value: "port", label: "Port" },
            ]}
            onChange={(v) =>
              setState({ ...state, rule_type: v as "domain" | "cidr" | "port" })
            }
          />
        </Field>

        <Field label="Decision">
          <SelectRow
            value={state.decision}
            options={[
              { value: "allow", label: "Allow" },
              { value: "deny", label: "Deny" },
            ]}
            onChange={(v) =>
              setState({ ...state, decision: v as "allow" | "deny" })
            }
          />
        </Field>

        <Field label="Scope">
          <SelectRow
            value={state.scope}
            options={[
              { value: "global", label: "Global" },
              { value: "sandbox", label: "Sandbox" },
            ]}
            onChange={(v) =>
              setState({ ...state, scope: v as "global" | "sandbox" })
            }
          />
        </Field>
      </div>

      {state.scope === "sandbox" && (
        <Field
          label="Sandbox ID"
          hint="The sbx sandbox name this rule applies to (run `sbx ls` to list)."
          error={sandboxError}
        >
          <Input
            value={state.sandbox_id}
            onChange={(e) => setState({ ...state, sandbox_id: e.target.value })}
            onBlur={() => setTouched(true)}
            placeholder="sopify-c98a10c5f5"
          />
        </Field>
      )}

      <div className="flex items-center justify-end gap-2 pt-2">
        <Button type="button" outlined onClick={onCancel}>
          Back to templates
        </Button>
        <Button type="button" onClick={handleSubmit}>
          Continue
        </Button>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string | null;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label className="text-xs">{label}</Label>
      {children}
      {hint && !error && (
        <p className="text-[10px] text-muted-foreground">{hint}</p>
      )}
      {error && <p className="text-[10px] text-destructive">{error}</p>}
    </div>
  );
}

function SelectRow({
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
            "flex-1 px-2 py-1.5 text-xs transition-colors",
            "hover:bg-secondary/30",
            value === opt.value && "bg-secondary/50 text-foreground",
            value !== opt.value && "text-muted-foreground",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function PreviewStep({
  rule,
  source,
  error,
}: {
  rule: CreateRuleRequest;
  source: "template" | "custom" | null;
  error: string | null;
}) {
  const yaml = useMemo(() => buildYamlPreview(rule), [rule]);
  const Icon =
    source === "template" ? Sparkles : source === "custom" ? Code2 : Boxes;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        <span>
          {source === "template"
            ? "From quick-add template"
            : source === "custom"
              ? "Custom rule"
              : "Rule preview"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 text-xs">
        <KV label="Name" value={rule.name} />
        <KV
          label="Decision"
          value={rule.decision ?? "allow"}
          mono
        />
        <KV label="Type" value={rule.rule_type ?? "domain"} mono />
        <KV
          label="Scope"
          value={
            rule.scope === "sandbox"
              ? `sandbox · ${rule.sandbox_id ?? "(missing)"}`
              : "global"
          }
          mono
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label className="text-xs flex items-center gap-2">
          <Globe className="h-3 w-3" />
          Patterns ({rule.patterns.length})
        </Label>
        <div className="flex flex-wrap gap-1.5">
          {rule.patterns.map((p) => (
            <code
              key={p}
              className="rounded bg-secondary/40 px-2 py-1 text-[11px]"
            >
              {p}
            </code>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label className="text-xs flex items-center gap-2">
          <Lock className="h-3 w-3" />
          YAML preview
        </Label>
        <pre
          className={cn(
            "border border-border bg-background/40 p-3",
            "font-courier text-[11px] leading-5 overflow-x-auto",
          )}
        >
          {yaml}
        </pre>
        <p className="text-[10px] text-muted-foreground">
          Saved to{" "}
          <code className="rounded bg-secondary/30 px-1 py-0.5">
            ~/.sopify/encm/rules/
            {rule.scope === "sandbox"
              ? `sandboxes/${rule.sandbox_id ?? ""}/`
              : "global/"}
            {rule.name}.yaml
          </code>
        </p>
      </div>

      {error && (
        <div className="border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      )}
    </div>
  );
}

function KV({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className={cn(mono && "font-courier")}>{value}</span>
    </div>
  );
}

function buildYamlPreview(rule: CreateRuleRequest): string {
  const lines = [
    "apiVersion: sopify.dev/v1",
    "kind: NetworkRule",
    "metadata:",
    `  name: ${rule.name}`,
    `  scope: ${rule.scope ?? "global"}`,
  ];
  if (rule.scope === "sandbox" && rule.sandbox_id) {
    lines.push(`  sandbox_id: ${rule.sandbox_id}`);
  }
  if (rule.created_by) lines.push(`  created_by: ${rule.created_by}`);
  if (rule.labels && Object.keys(rule.labels).length > 0) {
    lines.push("  labels:");
    for (const [k, v] of Object.entries(rule.labels)) {
      lines.push(`    ${k}: ${v}`);
    }
  }
  lines.push("spec:");
  lines.push(`  type: ${rule.rule_type ?? "domain"}`);
  lines.push(`  decision: ${rule.decision ?? "allow"}`);
  if (rule.ttl_seconds != null) {
    lines.push(`  ttl_seconds: ${rule.ttl_seconds}`);
  }
  lines.push("  patterns:");
  for (const p of rule.patterns) {
    lines.push(`    - ${p}`);
  }
  return lines.join("\n");
}

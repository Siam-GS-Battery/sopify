import { useCallback, useMemo, useState } from "react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Check, ChevronDown, ChevronRight } from "lucide-react";

import { api, type VibeProjectMarker } from "@/lib/api";
import {
  parseSecurityReview,
  severityBadgeTone,
  type SecurityFinding,
  type SecuritySeverity,
} from "@/lib/security-review";
import { cn } from "@/lib/utils";

/**
 * Left-pane Security review checklist (PR-010).
 *
 * Renders SECURITY_REVIEW.md as a structured checklist instead of a wall
 * of markdown so the user can tick off each finding as they address it.
 * Each tick PUTs to the backend so the marked-as-addressed state survives
 * reloads + re-runs of the review. When the parser can't recognise the
 * report (agent went off-format) we fall back to the raw <pre> rendering
 * so no content is silently dropped.
 */
export function SecurityChecklist({
  project,
  report,
  onMarkerUpdate,
}: {
  project: VibeProjectMarker;
  /** Raw SECURITY_REVIEW.md contents. */
  report: string;
  /** Called after a successful ack toggle so the parent's local marker
   * mirror reflects the new `addressed_security_findings`. */
  onMarkerUpdate?: (next: VibeProjectMarker) => void;
}) {
  const parsed = useMemo(() => parseSecurityReview(report), [report]);

  const initialAddressed = useMemo(
    () => new Set(project.addressed_security_findings ?? []),
    [project.addressed_security_findings],
  );
  const [addressed, setAddressed] = useState<Set<string>>(initialAddressed);
  const [pending, setPending] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const onToggle = useCallback(
    async (finding: SecurityFinding) => {
      const next = !addressed.has(finding.id);
      setPending(finding.id);
      setErr(null);
      // Optimistic — flip the checkbox immediately. Roll back on error.
      setAddressed((prev) => {
        const out = new Set(prev);
        if (next) out.add(finding.id);
        else out.delete(finding.id);
        return out;
      });
      try {
        const res = await api.setVibeSecurityFindingAck(
          project.name,
          finding.id,
          next,
        );
        // Server is source of truth — adopt its set verbatim.
        setAddressed(new Set(res.addressed_security_findings));
        onMarkerUpdate?.({
          ...project,
          addressed_security_findings: res.addressed_security_findings,
        });
      } catch (e: unknown) {
        // Roll back the optimistic flip.
        setAddressed((prev) => {
          const out = new Set(prev);
          if (next) out.delete(finding.id);
          else out.add(finding.id);
          return out;
        });
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        setPending((p) => (p === finding.id ? null : p));
      }
    },
    [addressed, project, onMarkerUpdate],
  );

  // Counts by severity for the header summary.
  const counts = useMemo(() => bySeverity(parsed.findings), [parsed.findings]);
  const total = parsed.findings.length;
  const done = parsed.findings.filter((f) => addressed.has(f.id)).length;

  // Empty report → kept simple. Parent already shows "Run security review"
  // CTA elsewhere, no need to duplicate the empty-state copy here.
  if (!report.trim()) return null;

  if (parsed.findings.length === 0) {
    // Parser found nothing recognisable — show raw so content isn't lost.
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-2">
        <div className="shrink-0 rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-700 dark:text-amber-200">
          Couldn't parse the report into a checklist — showing raw markdown
          below. (Expected the skill's <code>{`# Vuln N: <category>: <file:line>`}</code>{" "}
          format.)
        </div>
        <pre className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-border/60 bg-background-base/40 px-4 py-3 font-mono text-xs leading-relaxed text-midground">
          {parsed.unparsed || report}
        </pre>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <header className="flex shrink-0 flex-wrap items-center gap-2 px-1 text-xs">
        <span className="font-semibold text-midground">
          {done} / {total} addressed
        </span>
        {counts.HIGH > 0 && (
          <Badge tone="destructive" className="text-[10px]">
            {counts.HIGH} HIGH
          </Badge>
        )}
        {counts.MEDIUM > 0 && (
          <Badge tone="warning" className="text-[10px]">
            {counts.MEDIUM} MEDIUM
          </Badge>
        )}
        {counts.LOW > 0 && (
          <Badge tone="secondary" className="text-[10px]">
            {counts.LOW} LOW
          </Badge>
        )}
      </header>

      {err && (
        <div className="shrink-0 rounded border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          {err}
        </div>
      )}

      <ol className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1">
        {parsed.findings.map((f) => (
          <FindingItem
            key={f.id}
            finding={f}
            addressed={addressed.has(f.id)}
            pending={pending === f.id}
            onToggle={() => onToggle(f)}
          />
        ))}
      </ol>

      {parsed.unparsed && (
        <details className="shrink-0 rounded border border-border/60 bg-background-base/40 text-xs">
          <summary className="cursor-pointer px-3 py-2 font-medium text-muted-foreground hover:text-midground">
            Unparsed sections (preamble / footnotes)
          </summary>
          <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap break-words border-t border-border/60 px-3 py-2 font-mono text-[0.7rem] text-muted-foreground">
            {parsed.unparsed}
          </pre>
        </details>
      )}
    </div>
  );
}

function FindingItem({
  finding,
  addressed,
  pending,
  onToggle,
}: {
  finding: SecurityFinding;
  addressed: boolean;
  pending: boolean;
  onToggle: () => void;
}) {
  const [open, setOpen] = useState(false);
  const tone = severityBadgeTone(finding.severity);

  return (
    <li
      className={cn(
        "flex flex-col gap-1 rounded-lg border bg-background-base/40 transition-colors",
        addressed
          ? "border-border/40 opacity-70"
          : "border-border/70",
      )}
    >
      <div className="flex items-start gap-2 px-3 py-2">
        <button
          type="button"
          role="checkbox"
          aria-checked={addressed}
          onClick={onToggle}
          disabled={pending}
          className={cn(
            "mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors",
            addressed
              ? "border-[var(--primary)] bg-[var(--primary)] text-white"
              : "border-border/70 bg-background hover:border-[var(--primary)]/60",
            pending && "opacity-50 cursor-wait",
          )}
          aria-label={addressed ? "Mark as not addressed" : "Mark as addressed"}
          title={addressed ? "Mark as not addressed" : "Mark as addressed"}
        >
          {addressed && <Check className="h-3 w-3" strokeWidth={3} />}
        </button>

        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 flex-col gap-0.5 text-left"
        >
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={tone} className="text-[10px]">
              {finding.severity}
            </Badge>
            <span
              className={cn(
                "text-xs font-semibold text-midground",
                addressed && "line-through text-muted-foreground",
              )}
            >
              {finding.category}
            </span>
            <code className="font-mono text-[0.7rem] text-muted-foreground truncate">
              {finding.location}
            </code>
            {open ? (
              <ChevronDown className="ml-auto h-3 w-3 text-muted-foreground" />
            ) : (
              <ChevronRight className="ml-auto h-3 w-3 text-muted-foreground" />
            )}
          </div>
          {!open && finding.description && (
            <p className="line-clamp-2 text-[0.7rem] text-muted-foreground">
              {finding.description}
            </p>
          )}
        </button>
      </div>

      {open && (
        <div className="border-t border-border/40 px-3 py-2 text-xs text-muted-foreground space-y-2">
          {finding.description && (
            <Section label="Description">{finding.description}</Section>
          )}
          {finding.exploitScenario && (
            <Section label="Exploit Scenario">{finding.exploitScenario}</Section>
          )}
          {finding.recommendation && (
            <Section label="Recommendation">{finding.recommendation}</Section>
          )}
        </div>
      )}
    </li>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[0.65rem] font-semibold uppercase tracking-wider text-muted-foreground/80">
        {label}
      </p>
      <p className="mt-0.5 whitespace-pre-wrap break-words text-midground/90">
        {children}
      </p>
    </div>
  );
}

function bySeverity(findings: SecurityFinding[]): Record<SecuritySeverity, number> {
  const out: Record<SecuritySeverity, number> = {
    HIGH: 0,
    MEDIUM: 0,
    LOW: 0,
    UNKNOWN: 0,
  };
  for (const f of findings) out[f.severity] += 1;
  return out;
}

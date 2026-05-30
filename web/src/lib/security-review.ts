/**
 * Parser for SECURITY_REVIEW.md (per `skills/red-teaming/claude-code-security-review/SKILL.md`).
 *
 * The agent writes one section per finding in this shape:
 *
 *     # Vuln 1: XSS: `foo.py:42`
 *
 *     * Severity: HIGH
 *     * Description: ...
 *     * Exploit Scenario: ...
 *     * Recommendation: ...
 *
 * We split on `# Vuln N:` headings (lenient about case + spacing) and pull
 * the four `* Field:` bullets. Anything we can't recognise falls through
 * to `unparsed` so the SecurityChecklist component can show the raw
 * markdown as a safety net rather than dropping content silently.
 */

export type SecuritySeverity = "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN";

export interface SecurityFinding {
  /** Stable ID used for ack persistence. Derived from heading content
   * so the same finding keeps the same ID across re-runs. */
  id: string;
  /** 1-based ordinal as written in the report (`Vuln N`). */
  index: number;
  /** Category from the heading: "XSS", "SQL Injection", "RLS bypass", ... */
  category: string;
  /** Location from the heading: usually `<file>:<line>`. */
  location: string;
  severity: SecuritySeverity;
  description: string;
  exploitScenario: string;
  recommendation: string;
  /** The original markdown chunk for this finding (between two
   * `# Vuln N:` headings). Useful for a "show original" fallback. */
  raw: string;
}

export interface SecurityReviewParse {
  findings: SecurityFinding[];
  /** Markdown that didn't belong to any finding (preamble, footnotes).
   * Empty when the report is well-formed. */
  unparsed: string;
}

const VULN_HEADING_RE = /^# +Vuln +(\d+) *: *([^:]+?) *: *(.+?)$/im;

/** One leading `# Vuln N:` per chunk; backtick-stripping is left to
 * helpers below so the heading capture stays simple. */
function splitOnVulnHeadings(md: string): string[] {
  const lines = md.split(/\r?\n/);
  const chunks: string[] = [];
  let current: string[] = [];
  let inFinding = false;

  for (const line of lines) {
    if (/^# +Vuln +\d+ *:/i.test(line)) {
      if (current.length > 0) chunks.push(current.join("\n"));
      current = [line];
      inFinding = true;
    } else {
      current.push(line);
    }
  }
  if (current.length > 0) chunks.push(current.join("\n"));

  // First chunk is preamble unless it opens with a Vuln heading.
  if (chunks.length > 0 && !/^# +Vuln +\d+ *:/i.test(chunks[0])) {
    // Tag preamble specially so the caller can re-extract it.
    return ["__PREAMBLE__\n" + chunks[0], ...chunks.slice(1)];
  }
  return inFinding ? chunks : ["__PREAMBLE__\n" + md];
}

const SEVERITY_RE = /^\* *Severity\s*:\s*(.+?)\s*$/im;

const FIELD_NAME_RE = /^\* *([A-Za-z][A-Za-z ]*?)\s*:\s*(.*)$/;
const BULLET_START_RE = /^\* *[A-Za-z]/;

/**
 * Pull a multi-line `* Field:` value from a chunk. Field value starts on
 * the heading line itself and continues through subsequent indented lines
 * until the next `* ` bullet or end-of-chunk. Returns "" if not found.
 */
function extractField(chunk: string, name: string): string {
  const lines = chunk.split(/\r?\n/);
  const target = name.toLowerCase();
  for (let i = 0; i < lines.length; i++) {
    const m = FIELD_NAME_RE.exec(lines[i]);
    if (!m) continue;
    if (m[1].trim().toLowerCase() !== target) continue;
    const buf: string[] = [];
    if (m[2].trim()) buf.push(m[2]);
    for (let j = i + 1; j < lines.length; j++) {
      if (BULLET_START_RE.test(lines[j])) break;
      buf.push(lines[j]);
    }
    return buf.join("\n").trim();
  }
  return "";
}

function normSeverity(raw: string): SecuritySeverity {
  const s = raw.trim().toUpperCase();
  if (s.startsWith("HIGH")) return "HIGH";
  if (s.startsWith("MEDIUM") || s.startsWith("MED")) return "MEDIUM";
  if (s.startsWith("LOW")) return "LOW";
  return "UNKNOWN";
}

function stripBackticks(s: string): string {
  return s.replace(/^`+|`+$/g, "").trim();
}

function squashWhitespace(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

/**
 * Derive a stable per-finding ID. Index alone is unstable across re-runs
 * (the agent may renumber), so we combine the category + location which
 * the skill format is supposed to make uniquely-addressable.
 */
function deriveId(category: string, location: string, index: number): string {
  const slug = (s: string) =>
    s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  const c = slug(category) || "vuln";
  const l = slug(location) || `n${index}`;
  return `${c}__${l}`;
}

function parseFindingChunk(
  chunk: string,
  fallbackIndex: number,
): SecurityFinding | null {
  const m = VULN_HEADING_RE.exec(chunk);
  if (!m) return null;
  const index = Number(m[1]) || fallbackIndex;
  const category = squashWhitespace(m[2]);
  const location = stripBackticks(squashWhitespace(m[3]));

  const sev = SEVERITY_RE.exec(chunk);

  return {
    id: deriveId(category, location, index),
    index,
    category,
    location,
    severity: sev ? normSeverity(sev[1]) : "UNKNOWN",
    description: extractField(chunk, "Description"),
    exploitScenario: extractField(chunk, "Exploit Scenario"),
    recommendation: extractField(chunk, "Recommendation"),
    raw: chunk.trim(),
  };
}

export function parseSecurityReview(md: string): SecurityReviewParse {
  const trimmed = (md ?? "").trim();
  if (!trimmed) return { findings: [], unparsed: "" };

  const chunks = splitOnVulnHeadings(trimmed);
  const findings: SecurityFinding[] = [];
  let unparsed = "";

  let i = 1;
  for (const chunk of chunks) {
    if (chunk.startsWith("__PREAMBLE__")) {
      const tail = chunk.slice("__PREAMBLE__".length).trim();
      if (tail) unparsed += (unparsed ? "\n\n" : "") + tail;
      continue;
    }
    const finding = parseFindingChunk(chunk, i);
    if (finding) {
      findings.push(finding);
      i += 1;
    } else {
      unparsed += (unparsed ? "\n\n" : "") + chunk;
    }
  }
  return { findings, unparsed };
}

export function severityBadgeTone(
  sev: SecuritySeverity,
): "destructive" | "warning" | "secondary" {
  switch (sev) {
    case "HIGH":
      return "destructive";
    case "MEDIUM":
      return "warning";
    default:
      return "secondary";
  }
}

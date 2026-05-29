## Phase: Security (claude-code-security-review)

The user clicked **Run security review**. Apply the
`claude-code-security-review` skill above to this project's source code
and produce a single markdown report.

### What you produce in this phase

1. **`SECURITY_REVIEW.md`** at the project root, formatted exactly per
   the skill's "REQUIRED OUTPUT FORMAT" section above:
   - One `# Vuln N: <category>: <file:line>` heading per finding
   - Severity (HIGH / MEDIUM only — exclude LOW per the skill)
   - Description, exploit scenario, recommendation
   - Confidence ≥ 8 only (anything lower stays out of the report)
2. **One brief summary message in chat** when the file is written —
   total count + severity breakdown. Do NOT paste the whole report
   into chat; the user reads it from the file viewer.

### Scope tweaks for the Vibe-Code context

The skill was authored for PR review, but here you are reviewing a
freshly-built app that has no PR base to diff against. Adapt as
follows:

- Treat the **entire project directory** as the review surface, not
  `git diff`. Read every `.ts`, `.tsx`, `.js`, `.py`, `.sql`, and
  config file under the project folder.
- Pay extra attention to:
  - Supabase RLS policies — every table that holds user data MUST
    have RLS enabled with `auth.uid()`-keyed policies.
  - Express endpoints — Zod validation on the request, parameterised
    SQL, auth middleware on protected routes.
  - Client-side handling of secrets — only `VITE_*` ANON keys should
    appear in `import.meta.env.*`; the service role key must not.
  - File upload endpoints (when the `file-upload` add-on is on) —
    MIME / size / path-traversal checks.
- All the skill's HARD EXCLUSIONS still apply (no DOS, no rate-limit
  findings, no theoretical issues, etc.).

### What you DO NOT do in this phase

- Do not modify any source code in this phase. The user reviews the
  report, then decides whether to loop back to `improvement` to fix
  issues, or approve through to `done`.
- Do not run any scans that require network access or external
  services.
- Do not include findings below confidence 8 even if you saw them.

### Done definition

`SECURITY_REVIEW.md` is written with the skill-mandated format. The
user reads it and either:

- Clicks **Approve → Done** — the project is finished.
- Goes back to Improvement to fix flagged issues, then re-runs this
  phase.

---
name: company-sop
description: GS Battery IT SOPs, coding standards, and company-wide do/do-not rules. Always loaded for /vibe, /living, and /code-with-you modes.
metadata:
  type: org-context
  applies_to: ["vibe", "living", "code-with-you"]
---

# GS Battery — Engineering & IT SOP

You are an assistant operating inside the GS Battery org. The following rules
are not suggestions; they are SOP. Apply them silently — only mention them
when the user is about to violate one.

## Code

1. **Stack of record:** Python 3.11, Node.js 20 LTS, PostgreSQL 15.
   Do not introduce new languages or runtimes without IT approval.
2. **Style:** ruff (Python) and prettier+eslint (JS/TS) defaults from the
   org template. No bikeshedding on formatting.
3. **Tests:** every new module ships with at least one test. Bug fixes ship
   with a regression test that fails before the fix.
4. **Secrets:** never write API keys, passwords, or DB connection strings
   into source files. Always reference env vars; if absent, ask the user.
5. **PII:** treat employee names, emails, phone numbers, ID numbers, and
   customer data as PII. Never paste any PII into logs, screenshots, or
   chat output.

## IT do-not

- Do not run `rm -rf` against any path the user did not explicitly name.
- Do not push directly to `main` / `master` / `production` branches.
- Do not bump major-version dependencies in the same PR as a bug fix.
- Do not install global npm/pip packages — always use the project venv /
  node_modules.
- Do not commit binary blobs >5 MB without git-lfs.

## Handoff to IT

When the user is finished and asks "what now?" or "how do I deploy?",
generate a short handoff note containing:

  - **What the app does** (≤ 2 sentences)
  - **Files touched** (path list)
  - **Run command** (single shell line)
  - **Risks / gotchas** (bullet list)

Keep it terse. IT reviews dozens of these per week.

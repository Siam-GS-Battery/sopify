---
name: vibe-app-builder
description: Guided app builder for /vibe mode. Structured intake, 2-3 approach proposals, IT handoff template.
metadata:
  type: workflow
  applies_to: ["vibe"]
---

# /vibe — Guided App Builder

You are helping a non-engineer build an internal app. Engineers are not in
the loop yet; they will review your handoff at the end.

## Intake (REQ-4.1.1)

Before writing any code, ask these four questions in order. Do not skip
ahead even if the user seems to have an answer in mind.

1. **อยากได้อะไร?** (What do you want it to do? Tell me as if you were
   describing it to a coworker.)
2. **ใช้ข้อมูลอะไร?** (What data does it need? File, spreadsheet, API, or
   typed in by hand?)
3. **ใครจะใช้?** (Who will use it? Just you, your team, or the whole
   department?)
4. **ต้องการ output แบบไหน?** (How will it show results? Screen, file,
   email, dashboard?)

## Sense-check (REQ-4.1.2)

After intake, restate the request in 2 sentences and propose 2–3 approaches
with a one-line tradeoff each. Wait for the user to pick *before* writing
code. If the user is unsure, recommend the simplest option and explain why.

## Build

Implement in the smallest possible scope. Prefer single-file scripts over
projects with five files. Use the org stack from `company-sop`.

## Handoff (REQ-4.3.1)

When the user says it works, generate `HANDOFF.md` at the project root:

```markdown
# <app name> — IT Handoff
- **Goal:** <one sentence>
- **Approach chosen:** <which option from sense-check>
- **Files:** path list
- **Dependencies added:** name + version
- **Run:** `<one shell command>`
- **Cautions:** <bullets — things IT should know>
```

Do not deploy. Do not push to remote. IT promotes the project from here.

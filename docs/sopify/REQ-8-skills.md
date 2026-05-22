# REQ-8 — Skills & Org Context

> Status: scaffolded. Source: [DESIGN_ARCHITECTURE.md §REQ-8](../../../DESIGN_ARCHITECTURE.md).

## What was built

- `sopify_skills/` at the repo root (mounted/copied into the sandbox image).
  Five bundles:
  - **company-sop** — IT SOPs, coding standards, do-not list, handoff template
  - **living-employee** — 24/7 persona for /living mode
  - **vibe-app-builder** — guided intake → sense-check → handoff for /vibe
  - **code-with-you** — explanation-first, sequential pair-programming persona
  - **gs-mad** — placeholder gated by `phase >= 7` (REQ-8.1.5)
- `plugins/sopify-skills/loader.py` — discovers `SKILL.md` files from three
  sources (bundled, ~/.claude/skills, .sopify/skills) and resolves
  last-writer-wins. Phase-gates `gs-mad`.
- `plugins/sopify-skills/__init__.py` — `on_mode_change` hook injects the
  rendered system-prompt block.

## Checkbox coverage

| Checkbox | Coverage                                                   |
|----------|------------------------------------------------------------|
| 8.1.1–4  | Four `SKILL.md` files under `sopify_skills/`               |
| 8.1.5    | gs-mad bundle present, phase-gated at 7                    |
| 8.1.6    | `skills_for_mode(mode)` + `on_mode_change` hook            |
| 8.1.7    | `.sopify/skills/` discovery in `_walk()`                   |
| 8.2.1    | `~/.claude/skills/` discovery in `_walk()`                 |
| 8.2.3    | Dict update order: bundled → claude → project              |

## Why

- **YAML front-matter parsing is regex-based.** PyYAML is optional in some
  Hermes environments; doing a tiny regex parse keeps sopify-skills working
  without an extra dependency. The `applies_to` list and `phase_gate` int are
  the only fields with semantics; everything else is descriptive.
- **`render_system_prompt` strips the front-matter.** What goes into the model
  is the prose; the front-matter is metadata for the loader only.
- **Sort puts `company-sop` first.** Org rules should win over personas where
  they overlap. The persona then layers behavior on top.

## Deferred

- MCP merge from `~/.claude/mcp.json` (REQ-8.2.2). Hermes-core patch needed;
  tracked under REQ-9.
- `sopify_skills/gs-mad/SKILL.md` body — placeholder only. Filled when the
  methodology is finalised.

## Verify

```bash
SOPIFY_HOME=/tmp/sopify uv run pytest plugins/sopify-skills/tests   # 6 tests
```

## Next

REQ-3/4/5 — `sopify-modes` plugin. Three Sopify slash-commands that route the
above bundles to the right behaviour.

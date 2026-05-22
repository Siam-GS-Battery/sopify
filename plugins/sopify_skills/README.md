# sopify-skills

Skill loader + bundles. Bundles live in `sopify_skills/` (one dir per skill,
each containing `SKILL.md` with YAML front-matter).

## Bundles shipped

| Bundle              | Loaded for                  | REQ        |
|---------------------|----------------------------|------------|
| company-sop         | vibe, living, code-with-you| REQ-8.1.1  |
| living-employee     | living                     | REQ-8.1.2  |
| vibe-app-builder    | vibe                       | REQ-8.1.3  |
| code-with-you       | code-with-you              | REQ-8.1.4  |
| gs-mad              | (gated by `phase >= 7`)    | REQ-8.1.5  |

## Precedence (REQ-8.2.3)

```
sopify_skills/             ← bundled (lowest)
   ↓ overridden by
~/.claude/skills/          ← Claude Code skills (REQ-8.2.1)
   ↓ overridden by
.sopify/skills/  (cwd)     ← project-local (REQ-8.1.7)
```

Same-name skills replace; phase-gated skills are filtered.

## Mode injection (REQ-8.1.6)

`on_mode_change` hook returns `{"inject_system_prompt": "<rendered>"}` where
`<rendered>` concatenates the bodies of all skills whose `applies_to` includes
the active mode (or whose `applies_to` is empty == "everywhere").

## Test plan

```bash
SOPIFY_HOME=/tmp/sopify uv run pytest plugins/sopify-skills/tests
```

Covers:
- All four bundles discovered
- gs-mad filtered when phase < 7
- Mode → skills mapping
- Project-local override
- `render_system_prompt` strips front-matter

## Deferred

- **`~/.claude/mcp.json` MCP merge** (REQ-8.2.2) — Hermes' `tools/mcp_tool.py`
  already discovers MCP from its own config. Adding a second config source
  needs a Hermes-core patch; tracked under REQ-9 (IT Management) where the
  managed-settings layer can declare additional MCP sources without touching
  core.

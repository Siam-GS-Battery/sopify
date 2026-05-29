# Vendored skill: frontend-design

Upstream source:
- repo: https://github.com/anthropics/claude-code
- path: plugins/frontend-design/skills/frontend-design/SKILL.md
- fetched: 2026-05-30

The `SKILL.md` in this directory is a verbatim copy of Anthropic's
`frontend-design` skill. License terms apply per the upstream repo
(`LICENSE.txt` at the root of `anthropics/claude-code`).

Do NOT edit `SKILL.md` directly. Re-fetch from upstream when syncing
updates so future diffs against upstream stay clean. Sopify-specific
overrides belong in the Vibe phase prompt (`prompts/vibe/phases/design.md`)
which is composed alongside this skill at runtime.

Used by: Vibe Code `design` sub-phase (see `_vibe_compose_system_prompt`
in `hermes_cli/web_server.py`).

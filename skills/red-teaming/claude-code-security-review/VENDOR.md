# Vendored skill: claude-code-security-review

Upstream source:

- repo: https://github.com/anthropics/claude-code-security-review
- commit: `0c6a49f1fa56a1d472575da86a94dbc1edb78eda` (2026-02-11)
- fetched: 2026-05-30
- license: MIT (see `LICENSE` in this directory)

The upstream repo ships a GitHub Action plus a `/security-review`
Claude Code slash command (`.claude/commands/security-review.md`). For
Sopify we vendor only the parts the agent needs at runtime:

- `SKILL.md` — adapted from the upstream slash-command body so it
  works as a Sopify-style skill. The two material adaptations are:
  1. The skill can review either a PR diff (the upstream use case) or
     a whole project directory (the Sopify Vibe-Code `security` phase
     use case).
  2. The "ANALYSIS WORKFLOW" was rephrased to map onto our sub-task
     model rather than the upstream `Task` tool wording.
- `docs/` — verbatim copies of the upstream `custom-filtering-instructions.md`
  and `custom-security-scan-instructions.md`, retained for reference
  and for users who want to extend the skill.
- `LICENSE` — verbatim copy of the upstream MIT license.

Do NOT edit `SKILL.md` casually to track upstream — when the upstream
slash command changes substantially, re-derive `SKILL.md` from the new
`.claude/commands/security-review.md` and update the commit pin above.
Sopify-specific tweaks belong in the Vibe phase prompt
(`prompts/vibe/phases/security.md`) which is composed alongside this
skill at runtime by `_vibe_compose_system_prompt` in
`hermes_cli/web_server.py`.

What's intentionally NOT vendored:

- `action.yml` and the `.github/workflows/` files — those are CI glue.
- `claudecode/` Python evaluation harness — internal to the upstream
  project's own testing.
- `examples/`, `scripts/`, `pytest.ini` — not needed at runtime.

Used by: Vibe Code `security` phase (see `prompts/vibe/phases/security.md`
and `_VIBE_PHASE_SKILLS` in `hermes_cli/web_server.py`).

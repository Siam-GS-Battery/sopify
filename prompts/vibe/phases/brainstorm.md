## Phase: Brainstorm (capture requirements)

The user just picked a theme + add-ons and wants to describe what they
want to build. Your job in this phase is to capture scope into a
`REQUIREMENTS.md` they can approve before any code is written.

### What you produce in this phase

1. **`REQUIREMENTS.md`** at the project root, maintained incrementally
   as the conversation progresses. Cover:
   - One-line elevator pitch
   - Primary users + roles
   - Core user flows (3–8 bullets, each one a complete journey)
   - Data the system stores (entities + one-line descriptions)
   - Hard constraints (deploy target, scale, integrations, deadlines)
   - Explicit non-goals (what the user does NOT want, so scope stays tight)
2. **Focused follow-up questions** during chat — short, specific,
   one-decision-at-a-time. Avoid open-ended "tell me everything about
   X" prompts that push the work back on the user.
3. **Trade-off surfacing** — when the user's brief implies a fork (e.g.
   self-hosted vs Supabase, JWT vs session cookies), name the fork
   explicitly and propose a default.

### What you DO NOT do in this phase

- Do not write any code, components, migrations, or `package.json`.
- Do not create `DESIGN.md`, `DATABASE.md`, `API.md` yet.
- Do not stand up servers or install dependencies.
- Do not invent features the user did not ask for.

### Done definition

The user clicks **Approve → Design** when `REQUIREMENTS.md` reflects
the scope they want. Whatever the file says at that moment becomes the
contract for the design phase — make every round move the file forward
by a real increment, not just a rephrase.

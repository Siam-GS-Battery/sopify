## Phase: Design (frontend mockup)

This is the **first building sub-phase**. Your output for this phase is the
visual frontend ONLY — no backend, no database wiring, no Supabase SDK
calls. The user must approve the look-and-feel before any data layer or
API integration begins.

### What you produce in this phase

1. **Static frontend pages / components** matching the mode + add-ons selected:
   - React 18 + TypeScript (strict) + Tailwind CSS v4 (per `sopify-sdlc`)
   - Layout, navigation, key screens, empty / loading / error states
   - Realistic placeholder data inlined (no fetches)
2. **`DESIGN.md`** at the project root summarising:
   - Component inventory (`Header`, `Sidebar`, `<feature>Card`, …)
   - Tailwind tokens used (colour, spacing, radius scale)
   - Pages / routes
   - Open questions the user must decide before Database phase

### What you DO NOT do in this phase

- Do not install `@supabase/supabase-js` or write SQL.
- Do not create `services/api.ts` with real fetch calls.
- Do not start an Express / backend server.
- Do not invent fields you cannot justify with the user's brief.

### Design references available

The `frontend-design` skill (Anthropic-curated, vendored at
`skills/frontend-design/SKILL.md`) is **pre-loaded** in this phase — its
aesthetic guidance is already in your system prompt above. Follow it
strictly: commit to a bold direction, avoid the generic "AI slop"
stack (no Inter / Roboto / Arial as the display font, no purple-on-white
gradients, no cookie-cutter layouts).

You may *additionally* consult these via `skill_view` when relevant —
they are NOT pre-loaded:

- `popular-web-designs` — 54 real-world design systems (Stripe, Linear, …)
- `design-md` — Google DESIGN.md token-spec format (useful for `DESIGN.md`)
- `claude-design` — one-off HTML/Tailwind artifact patterns

**Conflict resolution:** if `frontend-design` and `sopify-sdlc` seem to
disagree (e.g. font choices), `sopify-sdlc` wins on *code conventions*
(TypeScript strict, naming, layering) while `frontend-design` wins on
*visual choices* (typography, colour, motion, composition). Tailwind v4
can load any font via `@font-face`; nothing in `sopify-sdlc` forces the
default system stack.

### Done definition

The user can click through the dev-server preview, see every screen with
representative placeholder data, and the chrome / typography / spacing
match what they expect. When they click **Approve design**, the gate
advances to `backend` — schema, API, and frontend wiring all happen
inside that single next phase.

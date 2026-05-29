## Phase: Backend (schema + API + wiring)

The frontend mockup is approved. In this single phase you design the
data layer AND wire the approved UI to it. The user reviews the data
shape with you first; once they approve, you stand up Supabase, write
the API, and replace placeholder data with real fetches — all in this
phase.

### Step 1 — Data shape review (BEFORE approve)

Before touching `supabase` CLI or writing SQL, produce a tight summary
of the data model the user can react to:

1. **`DATABASE.md`** at the project root:
   - Table list with one-line descriptions
   - Mermaid ER diagram covering the entities + relationships
   - Per-table column list (name, type, nullable, default, notes)
   - RLS posture per table (one line each)
   - Open questions you need the user to decide
2. **Chat through the trade-offs** — naming, denormalization, soft
   delete vs hard, who owns what relationship. Surface forks explicitly.

Do NOT run any migration command, install Supabase, or write SQL files
until the user signals the schema looks right in chat.

### Step 2 — Stand up Supabase + write the API (AFTER schema is settled)

Once the user is happy with `DATABASE.md`, build the data layer:

1. **SQL migrations** under `supabase/migrations/<timestamp>_<name>.sql`:
   - `CREATE TABLE` statements with `snake_case` columns (per `sopify-sdlc`)
   - Primary keys, foreign keys, indexes, NOT NULL where appropriate
   - `created_at` / `updated_at` columns with `default now()`
   - Explicit `enable row level security;` and a policy per table for
     user data, keyed on `auth.uid()` (if auth-jwt) or a project identifier
2. **Apply the migration** via the `supabase` CLI on the local stack
   (already installed alongside Sopify — see the `database-supabase`
   add-on prompt for endpoint / key conventions). Confirm the schema
   is live before moving on.
3. **TypeScript types** at `frontend/src/types/database.types.ts` —
   one `interface` per table, `snake_case` columns kept as-is.
4. **Supabase JS client** at `frontend/src/lib/supabase.ts` — reads
   `import.meta.env.VITE_SUPABASE_URL` / `..._ANON_KEY`, typed against
   `database.types.ts`.
5. **Service layer** at `frontend/src/services/<domain>.ts` — pure
   functions, snake_case → camelCase via `toX(dbRow)` transformers in
   `frontend/src/types/*.types.ts` so the DB shape never leaks to the UI.
6. **Backend thin layer** at `backend/` (Express) ONLY when writes need
   server-side validation: Controller → Service → Repository layering,
   Zod schemas for request validation, parameterised SQL only.
7. **Frontend page rewrites** — replace placeholder data with service
   calls. Keep the visual design 1:1 with the design phase; the
   loading / empty / error states already exist — re-use them.
8. **`API.md`** at the project root: endpoint list (method / path /
   body / response), auth posture (which routes are protected, how),
   error contract.

### What you DO NOT do in this phase

- Do not change the visual design — the user approved it.
- Do not add features the user did not ask for ("while I'm here").
- Do not expose service-role keys to the browser; only `VITE_*` ANON
  keys are safe in `import.meta.env.*`.
- Do not insert real PII or live customer data into seeds.

### Done definition

Every page that showed placeholder data in design now shows real data
from Supabase. Writes round-trip through the appropriate layer
(frontend service for reads + RLS-allowed writes; backend for
server-side-validated writes). `DATABASE.md` and `API.md` reflect the
live state. When the user clicks **Approve → Improvement**, the gate
advances to `improvement`.

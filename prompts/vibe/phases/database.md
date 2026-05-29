## Phase: Database (Supabase schema)

The frontend mockup is approved.  This phase designs the data layer.
Supabase Local is running on the host (see the `database-supabase` add-on
prompt for endpoint / key conventions).

### What you produce in this phase

1. **SQL migrations** under `supabase/migrations/<timestamp>_<name>.sql`:
   - `CREATE TABLE` statements with `snake_case` columns (per `sopify-sdlc`)
   - Primary keys, foreign keys, indexes, NOT NULL where appropriate
   - `created_at` / `updated_at` columns with `default now()`
2. **Row Level Security policies** for every table that holds user data:
   - Explicit `enable row level security;`
   - Policies keyed on `auth.uid()` (when auth-jwt add-on is on) or a
     project-defined identifier
3. **TypeScript types** generated or hand-written at
   `frontend/src/types/database.types.ts`:
   - One `interface` per table (PascalCase)
   - `snake_case` columns kept as-is (DB shape) — separate from API shape
4. **`DATABASE.md`** at the project root summarising:
   - Table list with one-line descriptions
   - Relationships (mermaid ER diagram if helpful)
   - RLS policy summary
   - Seed data plan (if any)

### What you DO NOT do in this phase

- Do not modify the existing frontend pages — they keep their placeholder
  data until the API phase wires them up.
- Do not create the Express backend yet (unless an endpoint is genuinely
  required for the schema demo, in which case make it minimal).
- Do not insert real PII or live customer data into seeds.

### Tools available

- `supabase` CLI for migrations + local stack management
- `psql` for ad-hoc verification (use parameterised queries in code,
  per the SOP-DEV-001 SQL rule)

### Done definition

The user can run `supabase db push` (or the project's equivalent),
see the migration apply cleanly, and verify the schema via Studio.
`DATABASE.md` reflects the live schema. When they click **Approve
schema**, the gate advances to `api`.

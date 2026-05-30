---
name: sopify-sdlc-database
description: "GS Battery database SOP for PostgreSQL via Supabase. Apply during the Vibe Code backend phase (schema design sub-step). Enforces naming, schema design, migration discipline, RLS policies, and indexing. Treat every rule below as binding — bad schema decisions are 10x harder to fix than bad API code."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [gs-battery, sopify-vibe, database, postgres, supabase, schema, rls, migrations]
    related_skills: [sopify-sdlc-backend, sopify-sdlc-design]
---

# sopify-sdlc-database — GS Battery Database SOP

You are designing the **data layer** of a GS Battery internal product. The stack is fixed: **PostgreSQL via Supabase** (managed or self-hosted, OpenAI-compatible API surface for auth + REST). Schema decisions outlive code — choose them carefully and write them down in `DATABASE.md`.

## Workflow (do not skip steps)

1. **Read `REQUIREMENTS.md`** — extract the entities + relationships the user described.
2. **Draft `DATABASE.md`** — propose tables + columns + relationships in markdown FIRST. Do NOT write SQL or migrations yet.
3. **Get user approval on `DATABASE.md`** — schema rework after data is in is expensive.
4. **Write migrations only after approval** — one feature per migration, never bundle.
5. **Apply RLS policies BEFORE seeding any data.**

## Naming conventions (binding)

| Element | Convention | Example |
|---|---|---|
| **Table** | `snake_case`, **plural**, lowercase | `users`, `battery_test_runs`, `audit_logs` |
| **Column** | `snake_case`, **singular**, lowercase | `email`, `created_at`, `battery_serial_number` |
| **Primary key** | `id` (always — never `user_id` on the `users` table) | `id uuid` |
| **Foreign key** | `<referenced_table_singular>_id` | `users.id` referenced as `user_id` |
| **Boolean** | `is_<adjective>` / `has_<noun>` | `is_active`, `has_admin_role` |
| **Timestamp** | `<verb>_at` (past tense) | `created_at`, `deleted_at`, `last_login_at` |
| **Junction table** | `<table_a>_<table_b>` (alphabetical) | `roles_users`, `projects_users` |
| **Index** | `idx_<table>_<col1>_<col2>` | `idx_battery_test_runs_battery_id_created_at` |
| **Constraint** | `chk_<table>_<purpose>` (check) / `uq_<table>_<col>` (unique) | `chk_users_email_format`, `uq_users_email` |
| **Enum type** | `<name>_enum` (suffix) | `user_status_enum`, `test_result_enum` |
| **Function** | `<verb>_<noun>` | `calculate_battery_health`, `notify_admin_on_critical` |
| **Trigger** | `trg_<table>_<verb>_<when>` | `trg_audit_logs_insert_after`, `trg_users_update_updated_at_before` |

## Required columns on every table

```sql
id              uuid        primary key default gen_random_uuid()
created_at      timestamptz not null    default now()
updated_at      timestamptz not null    default now()
```

If the entity is user-owned (multi-tenant):

```sql
user_id         uuid        not null    references users(id) on delete cascade
```

If soft-delete is needed (audit-critical entities):

```sql
deleted_at      timestamptz             -- NULL = active; NOT NULL = deleted
```

**Update trigger** for `updated_at`:

```sql
create or replace function trg_set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

create trigger trg_<table>_update_updated_at_before
  before update on <table>
  for each row execute function trg_set_updated_at();
```

Apply this to every table with `updated_at`.

## Schema design principles

### Types — pick the right one

| Use case | Type | Notes |
|---|---|---|
| IDs (primary + foreign keys) | `uuid` | `gen_random_uuid()` default. Never `serial` / `bigserial` for primary keys — predictable IDs leak info |
| Short text (< 255 chars, bounded) | `text` | Postgres `text` has no length penalty vs `varchar(n)` — always use `text` |
| Long text (free-form) | `text` | Same |
| Money / decimals | `numeric(precision, scale)` | NEVER `float` / `real` — rounding errors |
| Battery test values | `numeric(10, 3)` or as documented | Match the measurement precision |
| Timestamps | `timestamptz` | ALWAYS with timezone. NEVER `timestamp` (without TZ) — bug magnet |
| Date only | `date` | Birthdays, settlement dates — no time component |
| Boolean | `boolean` | NEVER `int 0/1` |
| Enum | `text` + `check (col in (...))` constraint, OR Postgres `enum type` | `check` is easier to migrate; enum type is faster |
| JSON | `jsonb` | NEVER `json` (text storage) — `jsonb` is binary + indexable |
| Sequences (sortable counters) | `bigint generated always as identity` | If you really need a sequence |

### Constraints — always declare

- `not null` on every column unless nullability is meaningful (e.g., optional `last_login_at`).
- `unique` on natural keys (`email`, `serial_number`, `slug`).
- `check` for value bounds (`check (rating >= 0 and rating <= 5)`).
- `references ... on delete cascade` (or `set null` if FK is optional) — never orphan rows.
- `default` for every non-null column with a sensible default.

### Indexes

Add an index for:
- Every foreign key column (`idx_<table>_<fk_col>`).
- Columns in `WHERE` of frequent queries (`status`, `created_at`).
- Columns in `ORDER BY` of paginated lists.
- Composite for common query pairs (`(user_id, created_at desc)`).

**Do NOT** add indexes for:
- Tables with < 1000 expected rows.
- Columns you "might" query someday — wait for measured slowness.
- Every column "just in case".

## Row-Level Security (RLS) — non-negotiable

**Every** table with multi-tenant data MUST have RLS enabled BEFORE any data is inserted:

```sql
alter table <table> enable row level security;

-- Read policy: users see only their own rows
create policy "users_can_read_own_<table>"
  on <table> for select
  using (auth.uid() = user_id);

-- Insert: users can only insert with their own user_id
create policy "users_can_insert_own_<table>"
  on <table> for insert
  with check (auth.uid() = user_id);

-- Update: users can only update their own rows
create policy "users_can_update_own_<table>"
  on <table> for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Delete: usually soft-delete via update — but if hard delete is allowed:
create policy "users_can_delete_own_<table>"
  on <table> for delete
  using (auth.uid() = user_id);
```

For **admin-only tables** (e.g., system_settings):

```sql
alter table system_settings enable row level security;

create policy "admins_only"
  on system_settings for all
  using (exists (
    select 1 from user_roles
    where user_id = auth.uid() and role = 'admin'
  ));
```

For **shared-team data** (everyone in the team sees the same data):

```sql
create policy "team_members_read"
  on <table> for select
  using (team_id in (
    select team_id from team_members where user_id = auth.uid()
  ));
```

## Migration discipline

- **One feature per migration.** Don't bundle unrelated changes.
- **Migration files named:** `YYYYMMDDHHMMSS_<verb>_<target>.sql` (Supabase convention).
  - `20260530120000_create_users.sql`
  - `20260530121500_add_status_to_battery_test_runs.sql`
- **Migrations are append-only.** Never edit a migration that's been applied to production. Write a new one to fix.
- **Every migration must be reversible** — include a `-- down` section as comments showing the rollback (Supabase doesn't auto-rollback but the comment helps reviewers).
- **Test the migration on a dev DB before production.**

## Backups + recovery

For any project with > 1 day of user data:
- Enable Supabase daily backups (point-in-time recovery if available on plan).
- Document the recovery procedure in `DATABASE.md` (which command to run, where backups live).

## DO

- Read `REQUIREMENTS.md` first, draft `DATABASE.md` in markdown, get approval BEFORE writing SQL.
- Use `uuid` primary keys with `gen_random_uuid()` default.
- Use `timestamptz` for every timestamp.
- Enable RLS on every table the moment it's created.
- Add an index for every foreign key column.
- Use `text` not `varchar(n)` — Postgres has no perf penalty.
- Document every non-obvious constraint with a comment in the migration.

## DO NOT

- **Use `int` / `serial` for primary keys.** Predictable IDs are a security smell.
- **Use `varchar(255)` reflexively.** It's a MySQL idiom that doesn't apply to Postgres.
- **Use `timestamp` (without timezone).** Always `timestamptz`.
- **Use `float` / `real` for money or measurements.** Use `numeric(p, s)`.
- **Skip RLS** "because the API will handle authorization". Defence in depth — RLS is the last line.
- **Bundle multiple features in one migration.**
- **Edit an applied migration.** Write a new one.
- **Cascade-delete user data without warning the user.** Soft-delete (`deleted_at`) is safer for audit.

## Quality gate before approving schema

Before writing the first migration, `DATABASE.md` must answer:

1. ✅ What are the entities + relationships? (ER outline)
2. ✅ Which entities are user-owned? (need `user_id` + RLS)
3. ✅ Which entities are admin-only? (need admin RLS policy)
4. ✅ Which fields need uniqueness? (email, serial_number, slug)
5. ✅ Which deletes cascade? Which set-null? Which soft-delete?
6. ✅ Backup + recovery plan stated.

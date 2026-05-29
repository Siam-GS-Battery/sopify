## Phase: API (backend + frontend integration)

Schema is approved.  This phase wires the data layer into the approved
mockup.  Follow `sopify-sdlc` (especially the Service / Repository
layering rule and the `toX(dbRow)` transformer convention so the
snake_case DB shape never leaks to the frontend).

### What you produce in this phase

1. **Supabase JS client** at `frontend/src/lib/supabase.ts`:
   - Reads `import.meta.env.VITE_SUPABASE_URL` / `..._ANON_KEY`
   - Single shared instance, typed against `database.types.ts`
2. **Service layer** at `frontend/src/services/<domain>.ts` (one file per
   domain — orders, users, products, …):
   - Pure functions: input args → typed result
   - All DB→API shape conversion via `toX(dbRow)` transformers in
     `frontend/src/types/*.types.ts`
3. **Backend thin layer** at `backend/` (Express) when writes need
   server-side validation:
   - Controller → Service → Repository layering
   - Zod schemas for request validation
   - Parameterised SQL only (no string interpolation)
4. **Frontend page rewrites** — replace placeholder data with service
   calls, keep the visual design 1:1 with the design phase:
   - Loading / empty / error states already exist from design phase —
     re-use them
   - Optimistic updates where the UX benefits
5. **`API.md`** at the project root:
   - Endpoint list (method / path / body / response)
   - Auth posture (which routes are protected, how)
   - Error contract

### What you DO NOT do in this phase

- Do not change the visual design / layout — the user approved it.
- Do not add features the user did not ask for ("while I'm here").
- Do not expose service-role keys to the browser; only `VITE_*` ANON
  keys are safe in `import.meta.env.*`.

### Done definition

Every page that showed placeholder data in the design phase now shows
real data from Supabase.  Writes round-trip through the appropriate
layer (frontend service for reads + RLS-allowed writes; backend for
server-side-validated writes).  `API.md` reflects the live endpoints.
When the user clicks **Approve integration**, the gate advances to
`verify`.

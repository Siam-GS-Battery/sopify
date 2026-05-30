---
name: sopify-sdlc-backend
description: "GS Battery backend SOP for Node.js + Express + TypeScript APIs serving React frontends backed by Supabase. Apply during the Vibe Code backend phase (API + wiring sub-step) and any backend work in improvement phase. Enforces request validation, error handling, auth, layering, and typed frontend wiring. Treat every rule below as binding."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [gs-battery, sopify-vibe, backend, express, nodejs, typescript, api, supabase, auth]
    related_skills: [sopify-sdlc-database, sopify-sdlc-design]
---

# sopify-sdlc-backend — GS Battery Backend SOP

You are building the **API layer** of a GS Battery internal product. The stack is fixed: **Node.js 20 + Express + TypeScript (strict) + Supabase (auth + DB)**. Treat the rules below as binding — past APIs failed review for skipping validation, leaking error details, or hand-rolling auth.

## Prerequisites (do not start without these)

1. **`DATABASE.md` is approved by the user.** API shape derives from schema; if schema isn't locked, API churn is wasted.
2. **Read `REQUIREMENTS.md`** for non-functional requirements (auth model, rate limits, integrations).
3. **Migrations are applied** — `DATABASE.md` reflects what's in Supabase, not aspirations.

## Folder structure

```
server/
├── src/
│   ├── routes/              # Express route handlers (thin — delegate to services)
│   │   ├── auth.routes.ts
│   │   ├── battery.routes.ts
│   │   └── index.ts         # Mount all routes
│   ├── services/            # Business logic (no HTTP knowledge)
│   │   ├── battery.service.ts
│   │   └── auth.service.ts
│   ├── middleware/          # Auth, validation, error handling
│   │   ├── auth.ts
│   │   ├── validate.ts
│   │   └── errorHandler.ts
│   ├── schemas/             # Zod schemas (request/response shapes)
│   │   └── battery.schema.ts
│   ├── types/               # Generated from Supabase + shared with frontend
│   │   ├── database.types.ts   # `supabase gen types typescript`
│   │   └── api.types.ts
│   ├── lib/                 # Cross-cutting (supabase client, logger, config)
│   │   ├── supabase.ts
│   │   ├── logger.ts
│   │   └── config.ts
│   ├── app.ts               # Express app setup (no .listen here)
│   └── server.ts            # `app.listen()` + graceful shutdown
├── package.json
└── tsconfig.json
```

- **Route handler:** parse + validate input → call service → format response. No business logic in routes.
- **Service:** pure functions that take typed input + Supabase client, return typed output. No `req` / `res`.
- **Middleware:** auth, validation, error handling. Composable, applied per-route or per-router.

## Request validation — Zod, always

Every request body / query / params **must** be validated. No exceptions.

```ts
import { z } from "zod";

export const CreateBatteryTestSchema = z.object({
  battery_id: z.string().uuid(),
  voltage: z.number().min(0).max(100),
  notes: z.string().max(1000).optional(),
});

export type CreateBatteryTestInput = z.infer<typeof CreateBatteryTestSchema>;
```

Middleware:

```ts
export const validate = (schema: z.ZodSchema) =>
  (req: Request, res: Response, next: NextFunction) => {
    const result = schema.safeParse(req.body);
    if (!result.success) {
      return res.status(400).json({
        error: "validation_failed",
        details: result.error.flatten(),
      });
    }
    req.body = result.data; // typed downstream
    next();
  };

// Usage:
router.post("/battery-tests", validate(CreateBatteryTestSchema), createBatteryTestHandler);
```

For query params: `validate(schema, "query")` variant. For URL params: same pattern with `req.params`.

## Error handling — one shape, always

Every error response **must** match this shape:

```ts
{
  "error": "<machine_readable_code>",          // snake_case
  "message": "<human_readable_one_liner>",      // safe to show to end user
  "details": { ... }                            // optional, structured
}
```

Error codes (machine-readable, expand as needed):

| Code | HTTP | Meaning |
|---|---|---|
| `validation_failed` | 400 | Request body / query failed Zod parse |
| `unauthorized` | 401 | Missing or invalid auth token |
| `forbidden` | 403 | Authenticated but lacks permission |
| `not_found` | 404 | Resource doesn't exist (or user can't see it) |
| `conflict` | 409 | Unique constraint, duplicate state, etc. |
| `rate_limited` | 429 | Too many requests |
| `internal_error` | 500 | Unhandled exception — log full trace, return generic message |

Global error handler:

```ts
import { logger } from "@/lib/logger";

export const errorHandler: ErrorRequestHandler = (err, req, res, _next) => {
  const requestId = req.id ?? crypto.randomUUID();
  logger.error({ err, requestId, path: req.path, method: req.method }, "request failed");

  if (err instanceof AppError) {
    return res.status(err.status).json({
      error: err.code,
      message: err.message,
      details: err.details,
      request_id: requestId,
    });
  }

  // Unknown — DO NOT leak `err.message` to client
  return res.status(500).json({
    error: "internal_error",
    message: "Something went wrong. Reference: " + requestId,
    request_id: requestId,
  });
};
```

**Never** `res.json({ error: err.message })` — that's how stack traces / DB column names / file paths leak.

Custom error class:

```ts
export class AppError extends Error {
  constructor(
    public code: string,
    public status: number,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

// Usage:
throw new AppError("not_found", 404, "Battery not found");
throw new AppError("forbidden", 403, "Admin role required");
```

## Authentication — Supabase JWT only

Do NOT roll your own JWT issuance. Use Supabase Auth's `getUser()` to verify tokens server-side.

```ts
// middleware/auth.ts
import { supabase } from "@/lib/supabase";

export const requireAuth: RequestHandler = async (req, res, next) => {
  const token = req.headers.authorization?.replace(/^Bearer\s+/i, "");
  if (!token) {
    return res.status(401).json({ error: "unauthorized", message: "Missing token" });
  }

  const { data, error } = await supabase.auth.getUser(token);
  if (error || !data.user) {
    return res.status(401).json({ error: "unauthorized", message: "Invalid token" });
  }

  req.user = data.user;          // attach for downstream
  next();
};
```

For role-based gates:

```ts
export const requireRole = (role: "admin" | "operator") =>
  async (req: Request, res: Response, next: NextFunction) => {
    const { data, error } = await supabase
      .from("user_roles")
      .select("role")
      .eq("user_id", req.user!.id)
      .single();
    if (error || data?.role !== role) {
      return res.status(403).json({ error: "forbidden", message: "Requires " + role });
    }
    next();
  };
```

## Supabase client — service-role vs anon

```ts
// lib/supabase.ts
import { createClient } from "@supabase/supabase-js";
import type { Database } from "@/types/database.types";

// Service-role: backend-only — bypasses RLS. Use sparingly + only after explicit auth check.
export const supabaseAdmin = createClient<Database>(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!,
);

// Anon-with-user-token: RLS enforced — preferred for user-scoped queries.
export const supabaseForUser = (userJwt: string) =>
  createClient<Database>(process.env.SUPABASE_URL!, process.env.SUPABASE_ANON_KEY!, {
    global: { headers: { Authorization: `Bearer ${userJwt}` } },
  });
```

**Default to `supabaseForUser`** so RLS does the heavy lifting. Use `supabaseAdmin` only for cross-tenant operations (background jobs, admin endpoints) with explicit comment explaining why.

## Typed frontend wiring

The frontend (React) and backend share types. The flow:

1. **Generate types from Supabase schema** (run after every migration):
   ```bash
   npx supabase gen types typescript --project-id <id> > src/types/database.types.ts
   ```
2. **Share API request/response types** by re-exporting from a workspace package or `shared/` folder.
3. **Frontend fetcher** uses the shared types:

```ts
// frontend: services/battery.api.ts
import type { CreateBatteryTestInput } from "@shared/types/api.types";

export async function createBatteryTest(input: CreateBatteryTestInput) {
  const res = await fetch("/api/battery-tests", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new ApiError(err.error, err.message, err.details);
  }
  return res.json();
}
```

## Logging

Use **structured JSON logging** (pino, winston) — NEVER `console.log` in production code paths.

```ts
import pino from "pino";
export const logger = pino({
  level: process.env.LOG_LEVEL ?? "info",
  redact: ["password", "token", "authorization"],
});
```

Log every request entry + exit + error. Include `request_id` for tracing. Redact secrets — never log auth tokens or PII.

## Async hygiene

- Every `async` route handler must catch errors → either `next(err)` or use `express-async-errors` to auto-forward.
- Every `await` must be inside a `try/catch` or wrapped by middleware that handles rejection.
- Never `setTimeout` without cleanup (leaks on server restart).
- Long-running tasks (> 30s): use a queue (e.g., pgmq on Supabase) — do NOT block a request.

## Rate limiting + abuse protection

- Apply `express-rate-limit` on auth endpoints (login, signup, password reset) — 5 req/min/IP default.
- Apply broader rate limit (100 req/min/IP) on all `/api/*` routes.
- Return `429` with `Retry-After` header.

## DO

- Validate every request with Zod schemas.
- Use one consistent error shape with machine-readable `error` codes.
- Authenticate via Supabase Auth's `getUser()` server-side — never trust the client's claim.
- Default to RLS-aware client (`supabaseForUser`) — service-role only with comment + reason.
- Generate types from Supabase schema after every migration.
- Log structured JSON with `request_id`, redact secrets.
- Wrap async handlers so unhandled rejections become 500 responses, not crashes.

## DO NOT

- **Echo `err.message` directly in 5xx responses.** Use a generic message + log the trace.
- **Trust `req.body.user_id`.** Use `req.user.id` from the verified token.
- **Bypass RLS reflexively** by using `supabaseAdmin`. Stop and write a comment justifying every use.
- **Use `console.log` in routes / services.** Use the structured logger.
- **Mix business logic into route handlers.** Routes parse input + call services + format output. Nothing else.
- **Hand-roll JWT verification.** Supabase Auth does it.
- **Store passwords or tokens in plaintext.** Anywhere. Ever. Even temporarily for debugging.

## Quality gate before "done"

Before declaring an API endpoint complete:

1. ✅ Zod schema covers body / query / params
2. ✅ Auth middleware applied (or comment justifying public access)
3. ✅ Errors use the standard shape — no raw `err.message` to client
4. ✅ Service function is unit-testable (no `req`/`res` inside)
5. ✅ Logged with `request_id`
6. ✅ Frontend type generated + imported, fetcher uses it
7. ✅ Manually tested success + validation-fail + unauthorized + forbidden cases

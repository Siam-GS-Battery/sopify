---
name: sopify-sdlc
description: "GS Battery SDLC code standards for React/TypeScript/Tailwind dashboards and websites. Apply when scaffolding a new project, writing frontend components, building backend APIs, or reviewing code. Enforces naming conventions, type safety, accessibility, security, and folder structure rules from SOP-DEV-001."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [code-standards, react, typescript, tailwind, dashboard, website, frontend, backend, sdlc, gs-battery, sopify-vibe]
    related_skills: []
---

# sopify-sdlc — GS Battery Code Standards (SOP-DEV-001)

You are building a dashboard or website for GS Battery. The Tech Stack is fixed: **React 18 + Vite + TypeScript (strict) + Tailwind CSS v4 + Node.js/Express + PostgreSQL (Supabase)**. Past dashboards delivered by AI agents were rejected for poor quality. This skill exists to prevent that. Treat every rule below as binding.

## Read before writing code

If the task touches:
- Type rules, naming, file layout, error handling → read `references/code-standards.md`
- React components, Tailwind, API client, accessibility, responsive → read `references/frontend-patterns.md`
- Express, validation, auth, SQL, security headers → read `references/backend-patterns.md`

You may skip references only for trivial, single-file edits inside an existing well-typed file.

## ข้อห้ามสำคัญ — DO / DON'T (non-negotiable)

| ห้ามทำ (DON'T) | ทำแทน (DO) |
|---|---|
| `any` type | Specific `interface`/`type`, or `unknown` + type guard |
| Short names (`x`, `tp`, `arr`, `data1`) | Descriptive names (`userName`, `totalPrice`, `activeOrders`) |
| Thai text inside code/identifiers | English only for code; Thai allowed only in user-facing strings |
| Hardcode secrets / API keys / DB URLs | `process.env.X` / `import.meta.env.VITE_X` + `.env.example` |
| String interpolation in SQL (`` `... ${id}` ``) | Parameterized queries (`$1`, `$2`) |
| Commit `.env` | `.env` in `.gitignore`; only `.env.example` is committed |
| `style={{...}}` inline styles in JSX | Tailwind utility classes only |
| Class components, `React.Component` | Functional components + Hooks |
| Push directly to `main` | Feature branch + Pull Request |
| `console.log` left in committed code | Remove, or use a structured logger |
| `\|\|` for defaults on numeric/boolean (`x \|\| 20`) | `??` nullish coalescing (`x ?? 20`) |
| Business logic in controllers | Controller → Service → Repository |
| `localStorage` for raw JWTs in security-critical apps | httpOnly cookie when feasible; document the choice |
| `CORS: *` in production | Allowlist of origins from env var |

## Naming Conventions (enforce on every file)

| Kind | Style | Example |
|---|---|---|
| Variables, functions | `camelCase` | `userName`, `calculateTotal()` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_LOGIN_ATTEMPTS`, `API_BASE_URL` |
| Classes, interfaces, types | `PascalCase` | `UserService`, `ProductCard`, `OrderStatus` |
| React components (file + export) | `PascalCase` | `UserProfile.tsx`, `LoginForm.tsx` |
| Utility files | `camelCase` | `formatDate.ts`, `authService.ts` |
| Custom hooks | `camelCase`, prefix `use` | `useAuth.ts`, `useCart.ts` |
| Folders | `kebab-case` | `user-management/`, `product-list/` |
| DB tables / columns | `snake_case` | `users`, `first_name`, `created_at` |
| API JSON fields | `camelCase` | `firstName`, `stockQuantity` |

DB uses `snake_case`; API responses use `camelCase`. Write a `toX(dbRow)` transformer in `types/x.types.ts` — never leak `snake_case` to the frontend.

## Project Structure (Vite + React + Tailwind)

```
frontend/
├── src/
│   ├── assets/
│   ├── components/
│   │   ├── common/         # Button, Input, Modal, Card, DataTable
│   │   ├── layout/         # Header, Sidebar, Footer, AppShell
│   │   └── features/       # auth/, products/, orders/ ...
│   ├── pages/              # one file per route
│   ├── hooks/              # useAuth, useDebounce, useProducts
│   ├── services/           # api.ts + one file per domain
│   ├── store/              # Zustand stores
│   ├── types/              # *.types.ts shared types
│   ├── utils/              # pure helpers
│   ├── lib/                # cn(), excel.ts, alert.ts
│   ├── schemas/            # zod schemas
│   ├── constants/
│   ├── App.tsx
│   └── main.tsx
├── .env.example
├── vite.config.ts
└── tsconfig.json

backend/
└── src/
    ├── config/             # env.ts, database.ts, logger.ts
    ├── controllers/        # HTTP I/O only
    ├── services/           # business logic
    ├── repositories/       # SQL only
    ├── routes/             # route definitions + index.ts
    ├── middlewares/        # auth, errorHandler, validateRequest
    ├── validators/         # zod schemas
    ├── types/
    ├── utils/              # apiResponse.ts
    ├── app.ts
    └── server.ts
```

## Seven non-negotiable rules

1. **TypeScript strict mode is on, and `any` is banned.** `tsconfig.json` MUST include `"strict": true`, `"noImplicitAny": true`, `"strictNullChecks": true`, `"noUnusedLocals": true`, `"noUnusedParameters": true`. ESLint rule `@typescript-eslint/no-explicit-any: error`.
2. **Tailwind utility classes only — no inline styles, no global CSS overrides, no CSS-in-JS.** Use `clsx` + `tailwind-merge` (`cn()` helper) for conditional classes.
3. **Parameterized SQL only.** Every `pool.query(...)` uses `$1, $2, ...`. Zero exceptions — even for "trusted" admin pages.
4. **Validate every backend input with Zod** at the route boundary via a `validateRequest(schema)` middleware. Never read `req.body` directly inside a controller without it passing a schema.
5. **MVC layering is mandatory.** Controllers receive/send HTTP and call services. Services contain business logic and throw typed errors. Repositories contain SQL. No business logic in controllers; no SQL outside repositories.
6. **API response shape is fixed.** Success: `{ success: true, data, pagination? }`. Error: `{ success: false, message, errors? }`. Use HTTP status codes correctly (200/201/400/401/403/404/409/500).
7. **Every async UI flow has Loading + Error + Empty states.** A dashboard that shows a blank screen during fetch, swallows errors, or shows an empty table without explanation is rejected.

## Quality gates before "done"

Run these and they MUST pass:

```bash
# Frontend
npm run lint        # 0 errors, 0 warnings
tsc --noEmit        # 0 type errors
npm run build       # builds

# Backend
npm run lint
tsc --noEmit
npm audit --audit-level=high   # 0 high/critical
```

Self-review checklist (apply to every diff before reporting "done"):

- [ ] No `any`, no `// @ts-ignore`, no `// eslint-disable` without justification
- [ ] No `console.log` left behind
- [ ] No hardcoded URLs, secrets, magic numbers (extract to `constants/` or env)
- [ ] Every API call has loading + error + empty UI states
- [ ] Every form input has a label or `aria-label`
- [ ] Tailwind layout is mobile-first (`grid-cols-1 md:grid-cols-2 lg:grid-cols-3`)
- [ ] Backend: every route → zod schema → middleware → controller → service → repository
- [ ] Backend: every SQL query parameterized
- [ ] Passwords hashed with bcrypt (cost ≥ 10)
- [ ] `helmet()` + CORS allowlist + rate limit on auth endpoints

## When scaffolding a NEW project

1. `npm create vite@latest frontend -- --template react-ts`
2. Install Tier 0: `react-router-dom`, `axios`, `zod`, `react-hook-form`, `@hookform/resolvers`, `zustand`, `tailwindcss@^4 @tailwindcss/vite`, `clsx`, `tailwind-merge`, `class-variance-authority`, `lucide-react`, `sonner`. Add Radix primitives + shadcn pattern under `src/components/ui/`.
3. Add `tsconfig.json` strict + `vite.config.ts` with `server: { host: '0.0.0.0', port: 5173 }` so sandboxes can reach it.
4. Backend: `express`, `cors`, `helmet`, `dotenv`, `pg`, `@supabase/supabase-js`, `jsonwebtoken`, `bcrypt`, `zod`, `express-rate-limit`.
5. Create `.env.example`, add `.env` to `.gitignore` immediately.
6. Set up ESLint + Prettier + Husky + lint-staged before writing the first feature.

If any step above is skipped, stop and finish setup first — quality problems cascade from a bad foundation.

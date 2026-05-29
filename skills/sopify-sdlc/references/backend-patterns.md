# Backend Patterns — Node.js + Express + PostgreSQL

Distilled from `4.4_Backend_Project.md` and `6.5_Security_Test_Guide.md`. Every backend endpoint follows the layered Request → Controller → Service → Repository → Database flow.

## 1. Folder layout

```
src/
├── config/             # env.ts, database.ts, logger.ts
├── controllers/        # HTTP I/O only — no business logic, no SQL
├── services/           # business logic — throws typed errors
├── repositories/       # SQL only — parameterized queries
├── routes/             # Express routers + index.ts
├── middlewares/        # auth, validateRequest, errorHandler, rateLimit
├── validators/         # zod schemas (or co-locate in routes/)
├── types/              # entity types + DTOs + DB↔API transformers
├── utils/              # apiResponse.ts, password.ts, jwt.ts
├── app.ts              # express() configuration
└── server.ts           # listen()
```

## 2. Types — DB ↔ API separation

DB rows are `snake_case`. API responses are `camelCase`. Define both and a transformer.

```typescript
// types/product.types.ts
export interface ProductDB {
  id: number;
  name: string;
  stock_quantity: number;
  is_active: boolean;
  created_at: string;
}

export interface Product {
  id: number;
  name: string;
  stockQuantity: number;
  isActive: boolean;
  createdAt: string;
}

export interface CreateProductDto {
  name: string;
  price: number;
  stockQuantity: number;
}

export function toProduct(db: ProductDB): Product {
  return {
    id: db.id,
    name: db.name,
    stockQuantity: db.stock_quantity,
    isActive: db.is_active,
    createdAt: db.created_at,
  };
}
```

Never leak `snake_case` field names to API consumers.

## 3. Repository — SQL only, parameterized always

```typescript
import { pool } from '@/config/database';
import type { ProductDB } from '@/types/product.types';

export class ProductRepository {
  async findAll(): Promise<ProductDB[]> {
    const result = await pool.query(
      'SELECT * FROM products WHERE is_active = true ORDER BY created_at DESC'
    );
    return result.rows;
  }

  async findById(id: number): Promise<ProductDB | null> {
    const result = await pool.query('SELECT * FROM products WHERE id = $1', [id]);
    return result.rows[0] ?? null;
  }

  async create(data: { name: string; slug: string; price: number; stock_quantity: number }):
    Promise<ProductDB> {
    const result = await pool.query(
      `INSERT INTO products (name, slug, price, stock_quantity)
       VALUES ($1, $2, $3, $4) RETURNING *`,
      [data.name, data.slug, data.price, data.stock_quantity]
    );
    return result.rows[0];
  }
}
export const productRepository = new ProductRepository();
```

Rules:
- **Never** interpolate user input into SQL strings — `$1, $2, ...` only.
- Repositories return DB rows (snake_case). The Service layer transforms them.
- No business validation here — that belongs in the service.

## 4. Service — business logic + typed errors

```typescript
import { productRepository } from '@/repositories/productRepository';
import { NotFoundError, ValidationError } from '@/middlewares/errorHandler';
import { toProduct, type CreateProductDto, type Product } from '@/types/product.types';

export class ProductService {
  async getById(id: number): Promise<Product> {
    const row = await productRepository.findById(id);
    if (!row) throw new NotFoundError('Product');
    return toProduct(row);
  }

  async create(data: CreateProductDto): Promise<Product> {
    if (data.price < 0) throw new ValidationError('Price cannot be negative');
    const slug = data.name.toLowerCase().replace(/\s+/g, '-');
    const row = await productRepository.create({
      name: data.name, slug, price: data.price, stock_quantity: data.stockQuantity,
    });
    return toProduct(row);
  }
}
export const productService = new ProductService();
```

## 5. Controller — HTTP I/O only

```typescript
import type { Request, Response, NextFunction } from 'express';
import { productService } from '@/services/productService';
import { sendSuccess, sendCreated } from '@/utils/apiResponse';

export class ProductController {
  async getById(req: Request, res: Response, next: NextFunction) {
    try {
      const product = await productService.getById(Number(req.params.id));
      sendSuccess(res, product);
    } catch (error) { next(error); }
  }

  async create(req: Request, res: Response, next: NextFunction) {
    try {
      const product = await productService.create(req.body);
      sendCreated(res, product);
    } catch (error) { next(error); }
  }
}
export const productController = new ProductController();
```

Every controller method: `try { ... } catch (error) { next(error); }`. No business rules here.

## 6. Response helpers — fixed shape

```typescript
// utils/apiResponse.ts
import type { Response } from 'express';

export function sendSuccess<T>(res: Response, data: T, status = 200) {
  return res.status(status).json({ success: true, data });
}
export function sendCreated<T>(res: Response, data: T) {
  return res.status(201).json({ success: true, data });
}
export function sendPaginated<T>(res: Response, data: T[], pagination: {
  page: number; pageSize: number; total: number; totalPages: number;
}) {
  return res.json({ success: true, data, pagination });
}
export function sendMessage(res: Response, message: string) {
  return res.json({ success: true, message });
}
```

## 7. Validation — Zod at the boundary

Every route receives validated input via middleware.

```typescript
// validators/productValidators.ts
import { z } from 'zod';

export const createProductSchema = z.object({
  name: z.string().min(1).max(200),
  price: z.number().nonnegative(),
  stockQuantity: z.number().int().nonnegative(),
  description: z.string().max(2000).optional(),
  categoryId: z.number().int().positive().optional(),
});
export type CreateProductInput = z.infer<typeof createProductSchema>;
```

```typescript
// middlewares/validateRequest.ts
import type { Request, Response, NextFunction } from 'express';
import { z, ZodError } from 'zod';

export function validateRequest(schema: z.ZodSchema) {
  return (req: Request, res: Response, next: NextFunction) => {
    const result = schema.safeParse(req.body);
    if (!result.success) {
      return res.status(400).json({
        success: false,
        message: 'Validation failed',
        errors: result.error.issues.map(i => ({
          field: i.path.join('.'),
          message: i.message,
        })),
      });
    }
    req.body = result.data;
    next();
  };
}
```

Apply at the route:

```typescript
router.post('/', authenticate, authorize('admin'), validateRequest(createProductSchema),
  (req, res, next) => productController.create(req, res, next));
```

## 8. Auth — JWT + role middleware

```typescript
// middlewares/authenticate.ts
import jwt from 'jsonwebtoken';
import type { Request, Response, NextFunction } from 'express';
import { config } from '@/config/env';

export interface AuthRequest extends Request {
  user?: { id: number; email: string; role: 'admin' | 'customer' | 'vendor' };
}

export function authenticate(req: AuthRequest, res: Response, next: NextFunction) {
  const header = req.headers.authorization;
  const token = header?.startsWith('Bearer ') ? header.slice(7) : null;
  if (!token) return res.status(401).json({ success: false, message: 'No token provided' });
  try {
    req.user = jwt.verify(token, config.jwtSecret) as AuthRequest['user'];
    next();
  } catch {
    return res.status(401).json({ success: false, message: 'Invalid or expired token' });
  }
}

export function authorize(...roles: Array<'admin' | 'customer' | 'vendor'>) {
  return (req: AuthRequest, res: Response, next: NextFunction) => {
    if (!req.user || !roles.includes(req.user.role)) {
      return res.status(403).json({ success: false, message: 'Forbidden' });
    }
    next();
  };
}
```

Rules:
- JWT secret comes from `process.env.JWT_SECRET` only — never hardcoded.
- Tokens expire (≤ 24h for access tokens). Use refresh tokens for longer sessions.
- For horizontal authorization (user A trying to read user B's order), check ownership in the service: `if (order.userId !== req.user.id) throw new ForbiddenError()`.

## 9. Passwords — bcrypt only

```typescript
import bcrypt from 'bcrypt';
const SALT_ROUNDS = 10;
export const hashPassword    = (pw: string) => bcrypt.hash(pw, SALT_ROUNDS);
export const comparePassword = (pw: string, hash: string) => bcrypt.compare(pw, hash);
```

- Never store plaintext passwords.
- Never return `password` or `password_hash` in any API response — strip in the transformer.
- Login endpoint returns the same generic error for "wrong email" and "wrong password" (prevents user enumeration).

## 10. Security middleware — apply on every app

```typescript
// app.ts
import express from 'express';
import helmet from 'helmet';
import cors from 'cors';
import rateLimit from 'express-rate-limit';
import { config } from '@/config/env';
import { errorHandler } from '@/middlewares/errorHandler';
import routes from '@/routes';

const app = express();

app.disable('x-powered-by');
app.use(helmet());
app.use(cors({
  origin: config.allowedOrigins,   // explicit allowlist, no `*` in production
  credentials: true,
}));
app.use(express.json({ limit: '1mb' }));

// Global rate limit
app.use(rateLimit({ windowMs: 15 * 60_000, max: 300 }));

// Stricter limit on auth endpoints
app.use('/api/auth', rateLimit({ windowMs: 15 * 60_000, max: 10 }));

app.use('/api', routes);
app.use(errorHandler);

export default app;
```

Required headers (Helmet provides them):
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Strict-Transport-Security` (HSTS)
- `Content-Security-Policy`
- Remove `X-Powered-By`

CORS: origin is a comma-separated allowlist from `ALLOWED_ORIGINS` env. Never `*` when `credentials: true`.

## 11. Environment

```typescript
// config/env.ts
import 'dotenv/config';

function required(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

export const config = {
  port: Number(process.env.PORT ?? 5000),
  nodeEnv: process.env.NODE_ENV ?? 'development',
  databaseUrl: required('DATABASE_URL'),
  jwtSecret: required('JWT_SECRET'),
  jwtExpiresIn: process.env.JWT_EXPIRES_IN ?? '24h',
  allowedOrigins: (process.env.ALLOWED_ORIGINS ?? 'http://localhost:5173').split(','),
};
```

`.env.example` is committed; `.env` is in `.gitignore`. Fail fast on missing required vars at boot.

## 12. Database connection pool

```typescript
// config/database.ts
import { Pool } from 'pg';
import { config } from './env';

export const pool = new Pool({
  connectionString: config.databaseUrl,
  max: 20,
  idleTimeoutMillis: 30_000,
  connectionTimeoutMillis: 5_000,
});
```

For pagination, always do `LIMIT $1 OFFSET $2` plus a parallel `COUNT(*)`:

```typescript
const offset = (page - 1) * pageSize;
const [rows, totalRows] = await Promise.all([
  pool.query('SELECT * FROM products ORDER BY created_at DESC LIMIT $1 OFFSET $2', [pageSize, offset]),
  pool.query('SELECT COUNT(*) FROM products'),
]);
const total = Number(totalRows.rows[0].count);
```

## 13. Logging

- Use a structured logger (`pino` or `winston`). Never `console.log` for production logs.
- **Never log** passwords, tokens, raw request bodies that contain secrets, or full email/phone (mask for PII).
- Log security events: failed logins, 401/403 hits, rate-limit triggers.
- Include a `requestId` (e.g., `nanoid`) in every log line for tracing.

## 14. Security checklist (per endpoint and per release)

- [ ] All inputs validated by zod schema
- [ ] All SQL parameterized — zero string interpolation
- [ ] `helmet()` enabled with HSTS + CSP + frameguard
- [ ] CORS allowlist explicit (no `*` with credentials)
- [ ] Rate limit on global + stricter on `/auth/*`
- [ ] Passwords hashed with bcrypt cost ≥ 10
- [ ] JWT with expiration; verified with secret from env
- [ ] Horizontal authorization checked (ownership) in service layer
- [ ] Error responses never expose stack traces, DB names, or env values
- [ ] `npm audit --audit-level=high` is clean
- [ ] No secrets in code or git history
- [ ] No `eval`, no `Function()`, no dynamic `require`

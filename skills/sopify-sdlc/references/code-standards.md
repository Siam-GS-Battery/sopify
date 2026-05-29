# Code Standards (SOP-DEV-001 distilled)

These rules apply to every TypeScript file you write — frontend and backend.

## 1. TypeScript

### Strict mode is mandatory

`tsconfig.json` MUST contain:

```json
{
  "compilerOptions": {
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "forceConsistentCasingInFileNames": true
  }
}
```

### `any` is banned — use specific types or `unknown`

```typescript
// ❌ wrong
function parse(data: any) { return data.value; }

// ✅ correct
interface Payload { value: string; }
function parse(data: Payload): string { return data.value; }

// ✅ when truly unknown, narrow with a guard
function handleError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return 'Unknown error';
}
```

### Generics over duplication

```typescript
function parseJSON<T>(jsonString: string): T {
  return JSON.parse(jsonString) as T;
}
```

### Union literal types for fixed value sets

```typescript
// ❌ wrong — accepts any string
function updateStatus(id: number, status: string) {}

// ✅ correct
type OrderStatus = 'pending' | 'confirmed' | 'processing' | 'shipped' | 'delivered' | 'cancelled';
function updateStatus(id: number, status: OrderStatus) {}
```

### `interface` vs `type`

- `interface` — for object shapes that may be extended (props, DTOs, entities).
- `type` — for unions, intersections, mapped types, primitives, function signatures.

### Optional chaining + nullish coalescing

```typescript
// ✅ correct — `pageSize: 0` survives
const pageSize = config.pageSize ?? 20;
const name = user?.profile?.firstName ?? 'Guest';

// ❌ wrong — `pageSize: 0` becomes 20
const pageSize = config.pageSize || 20;
```

### Never widen — keep types precise

```typescript
// ❌ Record<string, any>
// ✅ Record<string, string> or a named interface
```

### No non-null assertions (`!`) except for verified env vars

```typescript
// ✅ acceptable — env loaded at boot, fail fast
const JWT_SECRET = process.env.JWT_SECRET!;

// ❌ avoid in business code — use a guard
const user = users.find(u => u.id === id)!; // wrong
const user = users.find(u => u.id === id);
if (!user) throw new NotFoundError('User');
```

## 2. Naming

| Kind | Style | Example |
|---|---|---|
| Variables, functions | camelCase | `calculateTotal`, `userName` |
| Constants (module-level immutable) | UPPER_SNAKE_CASE | `MAX_LOGIN_ATTEMPTS` |
| Classes, interfaces, type aliases | PascalCase | `ProductService`, `User` |
| React components | PascalCase | `UserProfile` |
| Custom hooks | camelCase, `use` prefix | `useAuth` |
| Files: components | PascalCase.tsx | `UserProfile.tsx` |
| Files: utils, hooks, services | camelCase.ts | `formatDate.ts`, `authService.ts` |
| Folders | kebab-case | `user-management/` |
| DB tables, columns | snake_case | `first_name` |
| API JSON | camelCase | `firstName` |
| Booleans | `is/has/can/should` prefix | `isActive`, `canEdit` |
| Event handlers | `handleX` (prop: `onX`) | `handleSubmit`, prop `onSubmit` |

Names must be English and self-explanatory. `x`, `tmp`, `arr`, `data1`, `flag` are forbidden outside two-line callbacks.

## 3. React component structure

Order inside every component: **Props interface → Hooks → Effects → Handlers → Early returns → JSX**.

```typescript
interface UserProfileProps {
  userId: number;
  onUpdate?: (user: User) => void;
}

export function UserProfile({ userId, onUpdate }: UserProfileProps) {
  // 1. Hooks
  const { user, loading, error } = useUser(userId);
  const [isEditing, setIsEditing] = useState(false);

  // 2. Effects
  useEffect(() => { /* ... */ }, [userId]);

  // 3. Handlers
  const handleSave = async () => {
    if (!user) return;
    onUpdate?.(user);
    setIsEditing(false);
  };

  // 4. Early returns — loading / error / empty
  if (loading) return <Spinner />;
  if (error)   return <ErrorState message={error.message} />;
  if (!user)   return <EmptyState message="User not found" />;

  // 5. JSX
  return (
    <section className="rounded-lg bg-white p-6 shadow">
      <h2 className="text-xl font-semibold">{user.firstName} {user.lastName}</h2>
      <button onClick={handleSave} className="...">Save</button>
    </section>
  );
}
```

Rules:
- **Functional components + Hooks only.** No class components.
- **Destructure props in the signature.** Type via an `interface FooProps`.
- **Extract reused logic into custom hooks** (`useProducts`, `useDebounce`).
- **`key` must be a stable unique id**, never the array index.
- **Memoize only when there is evidence** of a perf issue: `React.memo` for heavy children that re-render needlessly, `useMemo` for expensive calculations, `useCallback` for handlers passed to memoized children.

## 4. Error handling

### Frontend

```typescript
async function loadProducts() {
  try {
    setLoading(true);
    setError(null);
    const products = await productService.getAll();
    setProducts(products);
  } catch (err) {
    if (err instanceof AxiosError) {
      setError(err.response?.data?.message ?? 'Server error');
    } else {
      setError('An unexpected error occurred');
    }
  } finally {
    setLoading(false);
  }
}
```

- Never swallow errors with empty `catch {}`.
- Surface errors visibly to the user (toast, banner, error component). A silent failure is the worst dashboard sin.
- Wrap the page tree in an `ErrorBoundary` for render-time crashes.

### Backend

Define typed error classes and throw from services. The global `errorHandler` middleware turns them into JSON.

```typescript
export class AppError extends Error {
  constructor(public statusCode: number, message: string) { super(message); }
}
export class ValidationError extends AppError { constructor(m: string) { super(400, m); } }
export class NotFoundError   extends AppError { constructor(r: string) { super(404, `${r} not found`); } }
export class UnauthorizedError extends AppError { constructor(m = 'Unauthorized') { super(401, m); } }
export class ForbiddenError    extends AppError { constructor(m = 'Forbidden')    { super(403, m); } }

export function errorHandler(err: Error, _req: Request, res: Response, _next: NextFunction) {
  if (err instanceof AppError) {
    return res.status(err.statusCode).json({ success: false, message: err.message });
  }
  console.error('ERROR:', err);
  return res.status(500).json({ success: false, message: 'Internal server error' });
}
```

Never leak stack traces, SQL errors, or library names ("supabase", "postgresql") to the client.

## 5. Imports

Order (separated by blank lines):

1. Node / framework built-ins (`node:fs`, `express`)
2. Third-party packages (`react`, `axios`)
3. Internal absolute aliases (`@/components/...`)
4. Relative imports (`./useFoo`)
5. Type-only imports last, using `import type`

Configure `tsconfig.json` path aliases:

```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] }
  }
}
```

Use them: `import { Button } from '@/components/common/Button';` — not `../../../../components/...`.

## 6. Comments

Write a comment when:
- A business rule has non-obvious context ("Bronze tier discount = 5%, set by marketing 2025-Q1").
- An algorithm is non-obvious or has a tricky invariant.
- You add `TODO:`, `FIXME:`, or `HACK:` — always with owner or ticket id.

Do NOT comment when:
- The code already says it (`// Get user by id` over `getUserById`).
- The comment merely restates the next line.

Public APIs and exported service functions: use JSDoc.

```typescript
/**
 * Registers a new user. Sends verification email asynchronously.
 * @throws {ValidationError} If email is already registered.
 */
async function registerUser(userData: CreateUserDto): Promise<User> { /* ... */ }
```

## 7. File size and function complexity caps

- File > 300 lines → split. Components > 200 lines → extract subcomponents/hooks.
- Function > 50 lines or cyclomatic complexity > 10 → refactor.
- No more than 4 parameters per function. Beyond that, take an options object.
- Nesting depth > 3 levels → invert with early returns / extract helper.

## 8. API response shape (shared contract)

Every API endpoint MUST respond with one of these shapes — frontend depends on it.

```typescript
// success — single
{ success: true, data: { ... } }

// success — list
{ success: true, data: [...], pagination: { page, pageSize, total, totalPages } }

// success — action
{ success: true, message: 'Product deleted successfully' }

// error
{ success: false, message: 'Product not found' }

// validation error
{ success: false, message: 'Validation failed',
  errors: [{ field: 'email', message: 'Invalid email format' }] }
```

| Status | Use when |
|---|---|
| 200 | GET / PUT / PATCH / DELETE success |
| 201 | POST that creates a resource |
| 400 | Validation / bad input |
| 401 | Missing / invalid / expired token |
| 403 | Authenticated but not authorized |
| 404 | Resource not found |
| 409 | Conflict (duplicate email, version mismatch) |
| 500 | Unexpected server error |

## 9. ESLint baseline

```js
// .eslintrc.cjs
module.exports = {
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react/recommended',
    'plugin:react-hooks/recommended',
    'plugin:security/recommended-legacy',
    'prettier',
  ],
  rules: {
    '@typescript-eslint/no-explicit-any': 'error',
    '@typescript-eslint/no-unused-vars': 'error',
    '@typescript-eslint/consistent-type-imports': 'error',
    'react/react-in-jsx-scope': 'off',
    'react/jsx-key': 'error',
    'react-hooks/rules-of-hooks': 'error',
    'react-hooks/exhaustive-deps': 'warn',
    'no-console': ['warn', { allow: ['warn', 'error'] }],
    'eqeqeq': ['error', 'always'],
  },
};
```

## 10. Pre-commit / definition-of-done

Before claiming a task complete:

- [ ] `npm run lint` — 0 errors, 0 warnings
- [ ] `tsc --noEmit` — 0 type errors
- [ ] `npm run build` — succeeds
- [ ] No `console.log`, commented-out code, or dead imports
- [ ] No `any`, no `@ts-ignore`, no `eslint-disable` without a justifying comment
- [ ] Names descriptive in English
- [ ] Error paths handled and surfaced to UI
- [ ] No secrets in code, no `.env` staged

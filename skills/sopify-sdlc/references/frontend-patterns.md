# Frontend Patterns — React + Vite + Tailwind

Distilled from `4.5_Frontend_Integration.md` and `2.2_UI_Design_with_Figma_Make.md`. Apply to every dashboard or website built for GS Battery.

## 1. Folder layout

```
src/
├── assets/               # images, fonts, static
├── components/
│   ├── ui/               # shadcn-style primitives (Button, Input, Card, Dialog)
│   ├── common/           # shared composite (DataTable, EmptyState, ErrorState, Spinner)
│   ├── layout/           # AppShell, Header, Sidebar, Footer
│   └── features/         # auth/, products/, dashboard/ ...
├── pages/                # one file per route
├── hooks/                # useAuth, useDebounce, useProducts
├── services/             # api.ts + authService.ts + productService.ts ...
├── store/                # Zustand stores
├── schemas/              # zod schemas (form + API DTOs)
├── types/                # shared types
├── lib/                  # cn(), excel.ts, alert.ts
├── utils/                # pure helpers (formatDate, parseQuery)
├── constants/
├── App.tsx
└── main.tsx
```

Co-locate feature-local components under `components/features/<feature>/`. Lift to `common/` only after the second use.

## 2. Tailwind rules

- **Only utility classes.** No inline `style`, no global CSS (other than `@import "tailwindcss"`), no CSS-in-JS, no `styled-components`.
- **Use `cn()` helper** for conditional classes — combines `clsx` + `tailwind-merge` (handles duplicate utility classes).

```typescript
// src/lib/utils.ts
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }
```

```tsx
<button
  className={cn(
    'rounded-lg px-4 py-2 text-sm font-semibold transition',
    variant === 'primary' && 'bg-blue-600 text-white hover:bg-blue-700',
    variant === 'ghost'   && 'text-gray-700 hover:bg-gray-100',
    disabled              && 'cursor-not-allowed opacity-50'
  )}
  disabled={disabled}
>
  {children}
</button>
```

## 3. Design tokens (GS Battery brand)

Encode in `tailwind.config.ts` so the agent never hand-codes hex values.

| Token | Hex | Tailwind |
|---|---|---|
| Primary | `#2563EB` | `blue-600` |
| Primary Hover | `#1D4ED8` | `blue-700` |
| Primary Active | `#1E40AF` | `blue-800` |
| Success | `#10B981` | `emerald-500` |
| Warning | `#F59E0B` | `amber-500` |
| Error | `#EF4444` | `red-500` |
| Info | `#3B82F6` | `blue-500` |
| Background | `#F8FAFC` | `gray-50` |
| Card | `#FFFFFF` | `white` |
| Text Primary | `#111827` | `gray-900` |
| Text Secondary | `#6B7280` | `gray-500` |
| Text Muted | `#9CA3AF` | `gray-400` |
| Border | `#E5E7EB` | `gray-200` |

Spacing scale: card padding `p-4` (small) / `p-6` (main) / `p-8` (hero). Border radius `rounded-lg` (8px) / `rounded-xl` (12px) / `rounded-2xl` (modal). Top nav height `h-16` (64px). Content max width `max-w-7xl` (1280px).

Typography: IBM Plex Sans / IBM Plex Sans Thai. Scale: H1 `text-3xl font-bold`, H2 `text-2xl font-semibold`, H3 `text-xl font-semibold`, body `text-sm`, caption `text-xs`.

## 4. Mobile-first responsive

Always start with the mobile layout, then add breakpoints upward.

```tsx
<div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
  {products.map(p => <ProductCard key={p.id} product={p} />)}
</div>

<main className="mx-auto max-w-7xl px-4 py-6 md:px-6 lg:px-8">
  {children}
</main>
```

| Breakpoint | Min | Use for |
|---|---|---|
| `sm:` | 640px | Landscape phone |
| `md:` | 768px | Tablet |
| `lg:` | 1024px | Desktop |
| `xl:` | 1280px | Large desktop |

A "desktop-only" dashboard is rejected. Every page must work on a 375px-wide screen.

## 5. API service layer

`src/services/api.ts`:

```typescript
import axios, { AxiosError } from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? 'http://localhost:5000/api',
  headers: { 'Content-Type': 'application/json' },
  timeout: 15000,
});

// Attach token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Normalize 401 → redirect to login
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default api;
```

One service file per domain: `authService.ts`, `productService.ts`, `orderService.ts`. Every function returns a typed promise.

```typescript
// src/services/productService.ts
import api from './api';
import type { Product, CreateProductDto, Pagination } from '@/types';

export const productService = {
  async getAll(params?: { page?: number; category?: string }):
    Promise<{ data: Product[]; pagination: Pagination }> {
    const res = await api.get('/products', { params });
    return res.data; // unwrap { success, data, pagination }
  },
  async getById(id: number): Promise<Product> {
    const res = await api.get(`/products/${id}`);
    return res.data.data;
  },
  async create(data: CreateProductDto): Promise<Product> {
    const res = await api.post('/products', data);
    return res.data.data;
  },
};
```

## 6. State management

- **Local UI state** → `useState`.
- **Cross-component shared state** → Zustand store under `src/store/`.
- **Server cache** (lists, detail, mutations) → either Zustand (small apps) or React Query (lists with caching/invalidation needs). Pick one and stick to it within the project.

Zustand store template:

```typescript
import { create } from 'zustand';
import { productService } from '@/services/productService';
import type { Product } from '@/types';

interface ProductState {
  products: Product[];
  loading: boolean;
  error: string | null;
  fetchProducts: () => Promise<void>;
}

export const useProductStore = create<ProductState>((set) => ({
  products: [],
  loading: false,
  error: null,
  fetchProducts: async () => {
    set({ loading: true, error: null });
    try {
      const { data } = await productService.getAll();
      set({ products: data, loading: false });
    } catch (err) {
      set({ error: 'Failed to fetch products', loading: false });
    }
  },
}));
```

## 7. Loading / Error / Empty states — every page

Every async-data screen MUST render all three. Skipping this is the #1 reason dashboards feel broken.

```tsx
function ProductsPage() {
  const { products, loading, error, fetchProducts } = useProductStore();
  useEffect(() => { fetchProducts(); }, [fetchProducts]);

  if (loading)              return <Spinner label="Loading products..." />;
  if (error)                return <ErrorState message={error} onRetry={fetchProducts} />;
  if (products.length === 0) return <EmptyState
    title="No products yet"
    description="Add your first product to get started."
    action={<Button onClick={openCreate}>Add product</Button>}
  />;

  return <ProductList products={products} />;
}
```

Provide reusable `<Spinner />`, `<ErrorState />`, `<EmptyState />` in `components/common/`.

## 8. Forms — react-hook-form + zod

```tsx
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

const loginSchema = z.object({
  email: z.string().email('Invalid email'),
  password: z.string().min(8, 'At least 8 characters'),
});
type LoginInput = z.infer<typeof loginSchema>;

export function LoginForm() {
  const { register, handleSubmit, formState: { errors, isSubmitting } } =
    useForm<LoginInput>({ resolver: zodResolver(loginSchema) });

  const onSubmit = async (data: LoginInput) => {
    await authStore.login(data.email, data.password);
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <div>
        <label htmlFor="email" className="block text-sm font-medium text-gray-700">Email</label>
        <input id="email" type="email" autoComplete="email"
          {...register('email')}
          className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-200"
        />
        {errors.email && <p role="alert" className="mt-1 text-xs text-red-500">{errors.email.message}</p>}
      </div>
      {/* password ... */}
      <button type="submit" disabled={isSubmitting}
        className="w-full rounded-lg bg-blue-600 px-4 py-2 font-semibold text-white hover:bg-blue-700 disabled:opacity-50">
        {isSubmitting ? 'Signing in...' : 'Sign in'}
      </button>
    </form>
  );
}
```

## 9. Routing & protected routes

```tsx
// src/components/common/ProtectedRoute.tsx
export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuthStore();
  if (loading) return <Spinner />;
  if (!user)   return <Navigate to="/login" replace />;
  return <>{children}</>;
}
```

Run `checkAuth()` once at app boot inside `App.tsx`'s `useEffect`.

## 10. Accessibility (WCAG AA — non-negotiable)

- Use **semantic HTML**: `<header>`, `<nav>`, `<main>`, `<section>`, `<article>`, `<button>`, `<a>`. Never `<div onClick>` for an interactive control.
- Every `<input>` has an associated `<label htmlFor>` or `aria-label`.
- Every icon-only button has `aria-label`.
- Color is never the only signal — pair status colors with icons or text.
- Color contrast ≥ 4.5:1 for body text, 3:1 for UI components.
- Focus rings are visible — never `outline-none` without a `focus:ring-*` replacement.
- Errors use `role="alert"` and `aria-invalid="true"` on the input.
- Modals trap focus and restore it on close (use Radix Dialog).
- Keyboard: every interactive element reachable by Tab; Esc closes modals.

## 11. Performance

- Lazy-load routes: `const Page = lazy(() => import('./pages/Page'));` + `<Suspense>`.
- Debounce search inputs (300ms).
- For lists > 200 rows: virtualize with `react-window` or `@tanstack/react-virtual`.
- Use `<img loading="lazy" />` for below-the-fold images.
- Avoid `useMemo`/`useCallback` everywhere — add only when a profiler shows a problem.

## 12. Vite config

```typescript
// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: {
    host: '0.0.0.0',   // required for sandboxed/containerized previews
    port: 5173,
  },
});
```

## 13. Environment

`.env.example` is committed; `.env` is gitignored.

```bash
VITE_API_URL=http://localhost:5000/api
VITE_SUPABASE_URL=https://xxxxx.supabase.co
VITE_SUPABASE_ANON_KEY=...
```

Read via `import.meta.env.VITE_X`. Never hardcode URLs.

## 14. Dashboard checklist (apply to every dashboard page)

- [ ] Mobile layout works at 375px wide (no horizontal scroll, no clipped controls)
- [ ] Tablet (768px) and desktop (1280px) tested
- [ ] Sidebar collapses on mobile (hamburger / Drawer)
- [ ] Every chart, table, and stat card has a loading skeleton
- [ ] Every async fetch has a visible error state with a retry button
- [ ] Empty state for zero-data tables (icon + title + description + CTA)
- [ ] Tables: pagination, sortable columns, filter, and export to Excel where requested
- [ ] Forms validated client + server (zod schema shared if possible)
- [ ] Toast (`sonner`) for success / error feedback on mutations
- [ ] Confirm modal for destructive actions (delete, archive)
- [ ] Page title in `<title>` + heading
- [ ] No `console.log` left in code

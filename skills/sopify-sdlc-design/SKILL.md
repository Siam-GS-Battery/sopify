---
name: sopify-sdlc-design
description: "GS Battery design + frontend SOP for React/TypeScript/Tailwind. Apply during the Vibe Code design phase and any frontend work in improvement phase. Enforces brand identity (logo, palette, typography), component patterns, accessibility, and responsive rules. Treat every rule below as binding — past dashboards were rejected for ignoring these."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [gs-battery, sopify-vibe, design, frontend, react, tailwind, accessibility, branding]
    related_skills: [frontend-design, sopify-sdlc-backend, sopify-sdlc-database]
---

# sopify-sdlc-design — GS Battery Design SOP

You are designing the **frontend layer** of a GS Battery internal product. The stack is fixed: **React 18 + Vite + TypeScript (strict) + Tailwind CSS v4**. Treat the rules below as binding — agents that ignore them produce work that gets rejected at review.

## Brand identity (non-negotiable)

### Logo

Use **`assets/GS_Battery_Logo.png`** as the GS Battery wordmark. If your project's `assets/` (or `public/`) folder doesn't have it yet, **copy it in from the canonical source**:

```bash
# canonical source — read-only, always current
<sopify-harness>/assets/GS_Battery_Logo.png

# Place in YOUR project at one of:
public/GS_Battery_Logo.png           # if using Vite public folder
src/assets/GS_Battery_Logo.png       # if importing via Vite asset pipeline
```

Where to use the logo:
- **Sidebar / app shell brand strip** (top-left, ~32–40 px tall)
- **Login / signup screen header** (centred, ~80–120 px wide)
- **Empty states / splash screens** (centred, ~60 px wide, optional)
- **Email templates** (top-centre, ≤200 px wide, PNG-embedded)
- **PDF report headers** (top-left, ~40 px tall)

Do NOT:
- Stretch / squash / recolour / outline the logo. Use the original PNG as-is.
- Place against busy photographic backgrounds. Solid surface (white / `--surface`) only.
- Use `mix-blend-mode` filters that change the logo's perceived colour.

### Color palette

Defined in [web/src/index.css](../../web/src/index.css). Reuse these tokens via Tailwind utilities — DO NOT introduce new hex codes:

| Token | Hex | Use |
|---|---|---|
| `--primary` | `#1D63ED` | CTAs, primary buttons, links, active nav |
| `--primary-hover` | `#1857D4` | Hover state on primary |
| `--accent` | `#0DB7ED` | Secondary highlights, info badges |
| `--text-primary` | `#03061E` | Body text, headings |
| `--text-secondary` | `#384D54` | Captions, hints, metadata |
| `--success` | `#10B981` | OK / live / completed status |
| `--warning` | `#F59E0B` | Caution / pending |
| `--danger` | `#EF4444` | Errors, destructive actions |
| `--surface` | `#FFFFFF` | Cards, panels, modals |
| `--surface-alt` | `#F3F4F6` | Sidebar bg, hover rows |
| `--bg` | `#F8FAFC` | Page canvas |
| `--border` | `#E5E7EB` | Dividers, input borders |

### Typography

- **Font:** Roboto (already loaded via Tailwind config — do NOT swap to Inter / system default).
- **Base size:** 13px / line-height 1.5 — the dashboard convention. Body text at this scale; bigger only for headings.
- **Scale:**
  - h1: 24px / 600 weight (page title)
  - h2: 20px / 600 (section header)
  - h3: 18px / 600 (card title)
  - body: 13px / 400
  - caption: 11px / 500 / `tracking-[0.08em]` uppercase (chips, badges, table headers)
- **Numbers / IDs / timestamps:** use `font-mono` + `tabular-nums` (`.font-num` utility).

### Spacing scale

Tailwind default `--spacing` (0.25rem step). Common patterns:

| Spacing | Use |
|---|---|
| `gap-1` / `p-1` | Tight elements (icon + label) |
| `gap-2` / `p-2` | Form rows, list items |
| `gap-4` / `p-4` | Card padding |
| `gap-6` / `p-6` | Section spacing |
| `gap-8` | Major page sections |

DO NOT use raw pixel values (`p-[12px]`, `mt-[7px]`) — round to the nearest scale step.

## Component patterns

### Buttons

```tsx
// Primary CTA
<button className="bg-primary hover:bg-primary-hover text-white px-4 py-2 rounded-md transition-colors">
  Save
</button>

// Secondary
<button className="border border-border bg-transparent hover:bg-surface-alt text-text-primary px-4 py-2 rounded-md">
  Cancel
</button>

// Danger (destructive)
<button className="border border-danger text-danger hover:bg-danger/8 px-4 py-2 rounded-md">
  Delete
</button>
```

Required `data-variant` attribute (`primary` / `secondary` / `danger`) so global theme overrides work. See [index.css §5](../../web/src/index.css).

### Forms

- Every `<input>` / `<select>` / `<textarea>` must have a paired `<label>` (visible or `sr-only`).
- Focus ring: `focus-visible:ring-2 focus-visible:ring-primary/30`. Never `outline: none` without a replacement.
- Error state: red border `border-danger` + `<p>` below with `text-danger text-xs` describing the error.
- Required fields: asterisk in label (`<span aria-hidden>*</span>`) + `required` attribute on input.

### Tables

- Header row: `text-uppercase text-xs tracking-wide text-text-secondary border-b`.
- Cells: `py-3 px-4` for comfortable density, `py-2` for compact.
- Hover: `hover:bg-surface-alt` on the row.
- Numeric columns: right-align (`text-right`) + `tabular-nums`.
- Empty state: centred message + small Sopify icon — do NOT just render an empty table.

### Cards / sections

- Background: `bg-surface` (`#FFFFFF`).
- Border: `border border-border` (`#E5E7EB`).
- Radius: `rounded-2xl` (16px) for content cards, `rounded-md` (6px) for inline chips.
- Shadow: `shadow` (subtle) for default, `shadow-lg` for elevated/modal.
- Padding: `p-6` for content cards.

### Status indicators

Use `data-status` attribute, not arbitrary class names:

```tsx
<span data-status="ok">Live</span>      // green
<span data-status="warn">Pending</span> // yellow
<span data-status="error">Failed</span> // red
```

CSS targets `[data-status="ok"]` etc. globally so colours stay consistent.

## Responsive breakpoints

Tailwind defaults — do NOT redefine:

| Prefix | Min width | Use |
|---|---|---|
| (none) | < 640 px | Mobile (single column, stacked) |
| `sm:` | ≥ 640 px | Large mobile / small tablet |
| `md:` | ≥ 768 px | Tablet |
| `lg:` | ≥ 1024 px | Laptop |
| `xl:` | ≥ 1280 px | Desktop |
| `2xl:` | ≥ 1536 px | Wide desktop |

Default: **mobile-first**. Write base styles for mobile, then layer `lg:` etc. on top. Sidebars collapse below `lg`; multi-column grids drop to single column below `md`.

## Accessibility (non-negotiable)

- Every interactive element must be reachable by **Tab** key + activated by **Enter / Space**.
- Use **semantic HTML first**: `<button>` for actions, `<a>` for navigation, `<form>` for forms. Do NOT make a `<div>` clickable.
- ARIA attributes only when no semantic element fits. Common needs:
  - `aria-label` for icon-only buttons.
  - `aria-expanded` for collapsible sections.
  - `aria-current="page"` for active nav link.
  - `role="alert"` for inline error messages.
- Colour is never the sole indicator. Always pair with text or icon (red border + error text, not just red border).
- Contrast: body text ≥ 4.5:1 against background. The token palette above meets this.

## File / folder structure (frontend)

```
src/
├── components/           # Reusable UI (Button, Card, Modal — domain-agnostic)
├── pages/                # Route-level components (DashboardPage, LoginPage)
├── features/<name>/      # Feature-scoped (auth, reports, users)
│   ├── components/
│   ├── hooks/
│   └── api.ts
├── lib/                  # Cross-cutting helpers (formatDate, cn, etc.)
├── assets/               # Images, icons (including GS_Battery_Logo.png)
└── App.tsx
```

- One component per file. Filename = component name (`UserCard.tsx`, not `user-card.tsx`).
- Co-locate styles ONLY if using CSS modules; otherwise Tailwind classes in JSX.
- `index.ts` re-export only when the folder is a barrel — don't `index.ts` every directory.

## DO

- Use Tailwind utility classes. Compose with `cn()` helper from `clsx` + `tailwind-merge`.
- Import the GS Battery logo from a project-local path (`src/assets/...` or `public/...`), not a URL.
- Add loading + empty + error states for every async UI surface.
- Use `data-` attributes for state hooks that CSS / tests need (`data-variant`, `data-status`, `data-loading`).
- Test keyboard navigation manually for every form / modal / menu before declaring "done".

## DO NOT

- **Use inline `style={{}}` attributes.** Use Tailwind utilities. Exception: dynamic values that can't be expressed as classes (e.g., `style={{ width: \`${pct}%\` }}`).
- **Use raw hex colours** in JSX or CSS. Use CSS variables / Tailwind tokens.
- **Use `<div>` for interactive elements.** Use `<button>` / `<a>` / `<input>` etc.
- **Hardcode pixel values** for spacing (`mt-[7px]`). Round to the Tailwind scale.
- **Stretch or recolour the GS Battery logo.** Original PNG, original aspect ratio, on solid surface only.
- **Ship a feature without empty / error states.** "It works when the data loads" is half the work.
- **Use `mix-blend-mode: plus-lighter`** unless inside the dashboard chrome where it's the documented pattern. It will desaturate the logo / text on light surfaces.

## Quality gate before "done"

Before declaring a UI feature complete, verify:

1. ✅ Logo renders correctly on every screen that has one
2. ✅ All interactive elements reachable by Tab + activated by Enter/Space
3. ✅ Mobile (375 px) layout doesn't break — no horizontal scroll
4. ✅ Empty / loading / error states all implemented
5. ✅ Focus rings visible on all buttons / inputs / links
6. ✅ No inline `style={{}}` for things expressible as classes
7. ✅ No raw hex codes — only Tailwind tokens / CSS variables

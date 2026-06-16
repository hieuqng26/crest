# CREST — Design System

> **Audience:** anyone touching the CREST frontend (engineers, designers, AI agents).
> **Status:** authoritative — `src/assets/layout/_brand.scss` is the implementation of what's described here. Update both together.

---

## 1. Design Intent

CREST is a banking-grade analytics surface aimed at quantitative analysts and risk modellers. The visual language borrows from **ey.com**: confident dark surfaces, restrained use of the EY Yellow accent, clean modern sans typography, and generous whitespace. The result must read as **professional, calm, precise** — never decorative.

Three rules govern every decision:

1. **One brand colour.** EY Yellow (`#FFE600`) is the only loud colour on the page. It marks primary actions, the active nav state, the first chart series, and selection highlights. If you reach for a second loud colour, you're over-decorating — pull back.
2. **Hierarchy through size and weight, not borders and shadows.** A page is "designed" when a user can navigate it with the chrome turned down. Headings are big and tight; supporting text is small and muted. Cards are flat, separated by a single 1-pixel hairline, never by drop shadows.
3. **Dark only.** Light mode has been removed. The toggle, the `ey-light` theme link, and the conditional logo logic are all gone. Do not reintroduce a light-mode code path; if a user complains about glare, address it with surface tones, not a second theme.

---

## 2. Colour Tokens

All colours flow through CSS custom properties on `:root`. The PrimeVue `ey-dark` theme loads first; `_brand.scss` overrides the tokens that matter. **Never hardcode a hex** outside `_brand.scss`.

### 2.1 Surfaces (page → overlay scale)

| Token              | Hex       | Use                                              |
|--------------------|-----------|--------------------------------------------------|
| `--surface-ground` | `#0A0A0F` | Page canvas — the layer below everything         |
| `--surface-section`| `#11111A` | Input backgrounds, secondary fills               |
| `--surface-card`   | `#16161E` | Cards, panels, sidebar, content surfaces         |
| `--surface-overlay`| `#1C1C26` | Dialogs, toasts, dropdowns, menus                |
| `--surface-border` | `#2A2A36` | All borders. Single hairline, never doubled      |
| `--surface-hover`  | `rgba(255, 230, 0, 0.04)` | Row, list, button hover wash      |

> The hover wash is **tinted yellow** at 4% opacity. This is intentional — it gives every interactive element a faint sense of the brand without ever shouting.

### 2.2 Text

| Token                     | Hex        | Use                                       |
|---------------------------|------------|-------------------------------------------|
| `--text-color`            | `#F5F5F7`  | Body text, headings, primary content      |
| `--text-color-secondary`  | `#9F9FAE`  | Labels, captions, secondary information   |
| `--text-color-muted`      | `#6B6B7A`  | Placeholders, disabled, separators        |

Pure `#FFFFFF` is reserved for text-on-yellow contrast cases (rare). `#F5F5F7` is warmer and easier on long viewing.

### 2.3 Brand & accent

| Token                  | Hex       | Use                                                 |
|------------------------|-----------|-----------------------------------------------------|
| `--primary-color`      | `#FFE600` | Primary buttons, active nav rail, first chart slot  |
| `--primary-color-hover`| `#FFEA33` | Hover state of primary buttons                      |
| `--primary-color-text` | `#1A1A24` | Text on yellow surfaces (never #FFFFFF — fails WCAG)|
| `--highlight-bg`       | `rgba(255, 230, 0, 0.10)` | Selected row, active tab background |
| `--focus-ring`         | `0 0 0 2px rgba(255, 230, 0, 0.35)` | Keyboard focus ring  |

**Hard rule:** never put EY Yellow text on a light surface — contrast is ~1.08:1 and fails WCAG. The platform is dark-only so this is structurally enforced, but be aware if you ever export a PDF or print view.

### 2.4 Semantic (status only — never decoration)

| Token              | Hex       | Meaning      |
|--------------------|-----------|--------------|
| `--success-color`  | `#34D399` | Success / completed |
| `--warning-color`  | `#F59E0B` | Warning / drift     |
| `--danger-color`   | `#F87171` | Failure / error     |
| `--info-color`     | `#60A5FA` | Neutral / informational |

These appear as small coloured dots, single-word tags, or one-line status text. They never become a background fill, a gradient, or a button colour.

### 2.5 Chart palette (fixed order)

| Slot      | Hex        | Conventional use |
|-----------|------------|------------------|
| `--chart-1` | `#FFE600` | Primary model / current run |
| `--chart-2` | `#60A5FA` | Comparison run / baseline   |
| `--chart-3` | `#34D399` | Third series                |
| `--chart-4` | `#F472B6` | Fourth                      |
| `--chart-5` | `#A78BFA` | Fifth                       |
| `--chart-6` | `#FB923C` | Sixth                       |
| `--chart-7` | `#22D3EE` | Seventh                     |
| `--chart-8` | `#F87171` | Eighth                      |

Slot 1 is **always EY Yellow**. Do not reassign — comparison charts depend on this for consistency across pages. Use flat colour only, never gradients.

---

## 3. Typography

### 3.1 Faces

| Family             | Stack                                                                                                          | Use                  |
|--------------------|----------------------------------------------------------------------------------------------------------------|----------------------|
| Primary sans-serif | `"EYInterstate", "Inter var", "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`      | All UI text          |
| Monospace          | `"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`                                   | IDs, code, log lines |

EYInterstate is EY's licensed brand face — it is **not bundled** in this repo. The stack falls through to **Inter var** (already self-hosted in `/themes/ey-dark/fonts/`), which is a near-twin. If/when an EYInterstate licence is provisioned, drop the woff2 files into `public/fonts/eyinterstate/` and add `@font-face` declarations at the top of `_brand.scss` — no other code changes needed.

### 3.2 Type scale

Tracking is mildly negative on every heading; this is what makes the type read as modern rather than corporate-default.

| Level        | Size       | Weight | Tracking | Use                                                  |
|--------------|------------|--------|----------|------------------------------------------------------|
| `h1` / page  | `1.75rem`  | 600    | -0.015em | Page title (top of every view)                       |
| `h2`         | `1.375rem` | 600    | -0.015em | Major section header                                 |
| `h3`         | `1.125rem` | 600    | -0.015em | Card header                                          |
| `h4`         | `1rem`     | 600    | -0.015em | Sub-card heading                                     |
| `h5`         | `0.875rem` | 600    | -0.015em | Inline group label                                   |
| `h6`         | `0.75rem`  | 600    |  0.06em  | UPPERCASE eyebrow label (`text-color-secondary`)     |
| Body         | `0.875rem` | 400    | -0.005em | Default body and table cells                         |
| Small        | `0.8125rem`| 400    | -0.005em | Captions, footnotes                                  |
| Micro / eyebrow | `0.7rem`| 600    |  0.06em  | UPPERCASE labels on tiny cards or strips             |

### 3.3 Numbers

Numbers always render in the monospace stack via the `.font-mono` class (Tailwind utility) or by wrapping in `<code>`. This includes:

- Run IDs and dataset fingerprints
- All metric values in KPI strips
- Model coefficients, p-values, confidence bounds
- Timestamps in tables

---

## 4. Spacing, Radii, Elevation

### 4.1 Spacing

Base unit: **4px** (use Tailwind's standard ramp). Defaults inside cards:

| Context                  | Padding              |
|--------------------------|----------------------|
| Page (`.layout-main-container`) | `6rem 1.75rem 2rem 1.75rem` |
| Card surface             | `1rem 1.25rem` (`p-4` / `p-5`) |
| Table cell               | `0.6rem 0.875rem`    |
| Tag / chip               | `0.15rem 0.45rem`    |
| Button (default)         | `0.5rem 0.875rem`    |
| Stack gap inside a card  | `1rem`               |
| Gap between top-level cards on a page | `1.5rem` |

### 4.2 Radius scale

| Token         | Value | Use                                            |
|---------------|-------|------------------------------------------------|
| `--radius-sm` | 4px   | Buttons, tags, inputs                          |
| `--radius-md` | 6px   | Menu items, popovers, log lines                |
| `--radius-lg` | 8px   | Cards, panels, sidebar, dialog                 |
| `--radius-xl` | 12px  | Reserved — do not use for new components       |

ey.com favours **square-leaning** edges. Anything bigger than 12px reads as childish in this context — don't use Tailwind's `rounded-xl` / `rounded-2xl`.

### 4.3 Elevation

We do not use drop shadows for surface elevation. Surface differentiation comes from:

1. **Background tone** — pick from the surface scale (page → card → overlay).
2. **One hairline border** — `1px solid var(--surface-border)`.

The only place shadow is acceptable is **modal dialogs and toasts**, where we use a strong shadow to push them visually above the page (`0 24px 48px rgba(0,0,0,0.45)`). This is in `_brand.scss` already.

---

## 5. Component Patterns

### 5.1 Buttons

| Variant   | Background      | Border                       | Text                       | When to use                       |
|-----------|-----------------|------------------------------|----------------------------|-----------------------------------|
| Primary   | `--primary-color` | same | `--primary-color-text` (off-black) | The single primary action on the page |
| Outlined  | transparent       | `1px solid --surface-border` | `--text-color`            | Secondary actions                  |
| Text      | transparent       | none                         | `--text-color-secondary`  | Tertiary actions, inline links    |

Rules:
- One primary button per region. Two yellow buttons next to each other is wrong every time.
- Buttons are `var(--radius-sm)` (4px). PrimeVue's pill default is overridden by `_brand.scss`.
- All buttons are `font-weight: 600`.

### 5.2 Cards & panels

```html
<div class="surface-card border-round-lg" style="border: 1px solid var(--surface-border)">
  <div class="px-4 pt-4 pb-2">
    <span class="text-xs font-semibold uppercase text-color-secondary"
          style="letter-spacing: 0.06em">Section eyebrow</span>
  </div>
  <!-- content -->
</div>
```

- Background: `var(--surface-card)`
- Border: 1px hairline
- Radius: `var(--radius-lg)` (8px)
- **No `shadow-1`/`shadow-2` classes** — `_brand.scss` zeroes them anyway, but don't add them in markup either.
- Card header is a small uppercase eyebrow (`text-color-secondary`, `letter-spacing: 0.06em`, ~0.7rem), not a chunky `h2`.

### 5.3 Tables

- No alternating row stripes. Hover wash only (`var(--surface-hover)`).
- Column headers: `0.7rem`, uppercase, `letter-spacing: 0.06em`, `text-color-secondary`, `font-weight: 600`.
- Cell padding: `0.6rem 0.875rem`. Body font 14px.
- Row separator: 1px `--surface-border`.
- Numeric columns right-aligned, monospace.

### 5.4 Status indicators

A status is **a coloured dot + one word**. Not an icon, not a tag with background fill, not a sentence.

```html
<span class="status-dot" :style="{ background: 'var(--success-color)' }"></span>
<span class="text-xs uppercase">Success</span>
```

For `running` add a `status-ping` halo (already in `CalibrateRun.vue`). Use the established pattern there as the reference.

### 5.5 Tabs / segmented controls

Use the pill pattern established in `CalibrateRun.vue` (`tab-bar` + `tab-btn`) for all in-page tabs — Overview / Progress / Diagnostics / Forecast. Active state: yellow text, `var(--highlight-bg)` background. Inactive state: `text-color-secondary`, no background.

### 5.6 Forms

- Inputs sit on `var(--surface-section)` (slightly lighter than card) with a 1px `var(--surface-border)` outline.
- Focus = 1px yellow border + 1px yellow box-shadow (already wired in `_brand.scss`).
- Field labels are `0.75rem text-color-secondary` and sit above the input.
- Help text is `0.75rem text-color-muted` and sits below the input.

### 5.7 Sidebar

- Floating card style: `surface-card` + hairline border + 8px radius.
- Section headers (`Data`, `Models`, `Calibration`, ...) render as small (`0.68rem`) uppercase eyebrows with wide tracking.
- Menu items: `0.875rem`, `--text-color`, hover gives the yellow wash.
- **Active route**: yellow vertical rail (3px wide, half-height, centred) on the left edge of the item, plus a 6%-opacity yellow background and bold weight. The rail is what's distinctive — never use a heavy filled background to indicate active.

### 5.8 Topbar

- Flat: same background as `--surface-ground`, single hairline bottom border, no shadow.
- Logo on the left (white EY mark, 32px), followed by `CREST` (bold, tracked +0.04em) and a 0.6875rem tagline below.
- All topbar icon buttons use `text-color-secondary` with the yellow wash on hover.

---

## 6. Iconography

- We use PrimeIcons (`pi-*`) and the bundled UIcons sets.
- Icon colour: `var(--text-color-secondary)` by default; matches its label when interactive; `var(--primary-color)` only when reinforcing an active brand state.
- Size: 14px (`text-sm`) inline, 16px in buttons, 24px (`text-2xl`) for empty-state hero icons.
- Never combine an icon with a tag *and* a status label on the same row — pick one.

---

## 7. Motion

| Effect             | Duration | Easing            |
|--------------------|----------|-------------------|
| Hover / focus      | 150ms    | `ease`            |
| Tab / sidebar transition | 200ms | `ease`         |
| Layout/route change | 250ms   | `ease`            |
| `running` status ping | 1.6s  | `cubic-bezier(0, 0, 0.2, 1)` |
| Toast slide-in     | 250ms    | `ease-out`        |

No animations longer than 300ms except the status ping. No bouncing, no scaling, no parallax — the EY brand is calm.

---

## 8. Accessibility

- All text/background pairs must meet **WCAG 2.1 AA** (4.5:1 small, 3:1 large). The token combinations above are pre-verified.
- Focus rings are always visible — `_brand.scss` reinstates a 2px yellow ring with 35% opacity that PrimeVue otherwise hides.
- Status is never communicated by colour alone. Always pair with a label (`Success`, `Failed`, etc.) or an icon.
- The yellow primary button has `--primary-color-text` of off-black (`#1A1A24`) — a 17:1 ratio. Never use white on yellow.

---

## 9. What Changed From the Old Codebase

When this design system was applied, the following changes happened in the repo. **Read this section if you're trying to understand why something looks different from a year ago.**

### 9.1 Removed

| File / element                                 | Reason                                                |
|------------------------------------------------|-------------------------------------------------------|
| Dark/light toggle button in `AppTopbar.vue`    | Light mode is gone                                    |
| `onChangeTheme`, `toggleDarkModeChange` in `AppTopbar.vue` | Dead with the toggle                       |
| Conditional `logoUrl` computed in `AppTopbar.vue`, `AppFooter.vue`, `Login.vue`, `Access.vue`, `Error.vue`, `NotFound.vue` | The logo is always the white EY mark — refer to `/layout/images/logo-ey.svg` directly |
| `layout-theme-light` / `layout-theme-dark` class swap in `AppLayout.vue` | The booleans-vs-strings comparison was buggy and never fired anyway; now hardcoded to `layout-theme-dark: true` |

The `ey-light` theme files at `public/themes/ey-light/` are left on disk for now (they are dead assets but safe to keep until a cleanup pass).

### 9.2 Added

| File                              | Purpose                                                                    |
|-----------------------------------|----------------------------------------------------------------------------|
| `src/assets/layout/_brand.scss`   | The brand override layer — implements everything in this DESIGN.md         |
| `DESIGN.md` (this file)           | Authoritative reference                                                    |

`_brand.scss` is imported **last** by `src/assets/layout/layout.scss` so its tokens win over the PrimeVue theme tokens loaded by the static `<link>` in `index.html`.

### 9.3 Changed

| File                              | What                                                                       |
|-----------------------------------|----------------------------------------------------------------------------|
| `index.html`                      | `<link href="/themes/ey-dark/theme.css">` (was `ey-light`)                  |
| `src/layout/composables/layout.js`| `darkTheme: true`, `theme: 'ey-dark'`                                      |
| `src/layout/AppLayout.vue`        | `containerClass` simplified — `layout-theme-dark` always on                |
| `src/layout/AppTopbar.vue`        | Toggle removed; `brand-text` block added with name + tagline; scoped styles for it |
| `src/layout/AppFooter.vue`        | Reduced to an empty container; conditional logo computed deleted          |
| `src/views/auth/{Login,Access,Error,NotFound}.vue` | Logo is a plain const, no `useLayout()` import           |

---

## 10. Migration Checklist for Existing Pages

If you find a page that doesn't follow this system yet, work through this checklist:

- [ ] Remove every hardcoded hex colour. Replace with the appropriate `var(--*)` token from §2.
- [ ] Replace `shadow-1` / `shadow-2` / `shadow-3` with a single `1px solid var(--surface-border)`. (`_brand.scss` zeroes the shadow utility, so leaving them in markup is harmless but misleading — remove them.)
- [ ] Page title is an `<h1>` with the default tokens — do not override its size.
- [ ] Card headers are small uppercase eyebrows (§5.2 example), not chunky `h2/h3`.
- [ ] Any "primary" coloured background (blue, green, purple) on a button → switch to the EY Yellow primary button.
- [ ] Any chart series colour → switch to `var(--chart-N)` and ensure the first series is `--chart-1`.
- [ ] Any `border-radius` larger than `12px` (or any `rounded-xl` / `rounded-2xl` Tailwind class) → reduce to `var(--radius-lg)` or smaller.
- [ ] Any table with alternating row stripes → remove stripes; lean on the hover wash from `_brand.scss`.
- [ ] Any inline `style="background: #..."` for a status pill → use a status dot + label (§5.4).
- [ ] All datetime values formatted via `fmtDate` from `@/utils/datetime.js` (CLAUDE.md rule, restated here).
- [ ] All numeric IDs and metric values rendered in `font-mono`.

The reference implementations to copy from are:

- `views/calibrate/CalibrateJobs.vue` — table + filter strip + segmented control
- `views/calibrate/CalibrateRun.vue` — page header, tabs, status indicators, progress strip
- `views/calibrate/runTabs/OverviewTab.vue` — flat KPI cards, "Run details" strip
- `views/credit_risk/CreditRiskECL.vue` — segmented pill, panel grid

If a page diverges from these in look or feel, the page is wrong — not the references.

---

## 11. Open Questions / Future Work

- **EYInterstate font licensing.** Stack falls through to Inter today. When licence is sorted, drop the woff2 in `public/fonts/eyinterstate/` and add `@font-face` blocks at the top of `_brand.scss`.
- **Custom theme upload.** A user-uploaded JSON theme override path is documented in the platform CLAUDE.md but not wired. Until it is, all design decisions go through `_brand.scss`.
- **Print / PDF export.** Some export paths (`html2canvas` + `jsPDF`) inherit dark backgrounds, which look bad on printed paper. The current export uses an inverted print stylesheet only on `ResultsDashboard` — extend this pattern when more export paths are added.
- **Cleanup `public/themes/ey-light/`.** Dead asset since the toggle is removed. Safe to delete in a follow-up commit.

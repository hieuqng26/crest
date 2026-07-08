# Design System & Theme

The visual language for every page. Non-negotiable — follow even for "one quick field".

**v2 (current).** CREST is on the v2 EY-style redesign: ink black, a single sparse
yellow accent, and 2px squared corners everywhere. See `design/README.md` (design
tokens + screen-by-screen spec) and `design/CREST Redesign v2.dc.html` (hi-fi reference)
for the full source of truth — **match its px values exactly**, don't approximate.
This file summarizes the parts that matter for day-to-day component work.

## Units: raw px, not rem

`AppConfig.vue` sets `html { font-size: <slider value>px }` (default 13px) — a legacy
sakai-template feature that lets a user shrink/grow the whole UI. Any `rem` value you
write is silently scaled by that root font-size, **not** by the 16px the mockup assumes.
At the default 13px root, `1rem` renders as 13px instead of 16px — an ~19% shrink that
was the cause of a "fonts look smaller/thinner than the mockup" bug across the shell,
buttons, and Login/Dashboard.

**Rule: all v2 sizing (font-size, padding, margin, width, height, gap) is raw `px`
copied straight from the mockup, never `rem`.** This is intentional, not an oversight —
the font-scale slider should affect legacy/dense data screens if anything, not this
fixed-px chrome and typography system. `_brand.scss`, `_topbar.scss`, `_menu.scss`,
`_content.scss`, `Login.vue`, `Dashboard.vue`, and `components/ui/*` all follow this.

## Theme architecture

- Base PrimeVue theme: **`ey-light`**, linked in `index.html`
  (`/themes/ey-light/theme.css`). The base theme bakes literal colors into component
  CSS — to change light/dark you switch the `<link>`, not the tokens (tokens alone
  won't override the base theme's literal colors in dropdowns/menus/overlays).
- Refinement layer: **`src/assets/layout/_brand.scss`** — imported last so it wins.
  This is the single source of truth for tokens and component overrides.
- **Ink chrome + light content.** The topbar (`#1A1A24`) and sidebar (`#2E2E38`) are
  the persistent dark frame; content surfaces are light (`--surface-ground #F4F4F6`).
  The sidebar's border matches its own background (no visible seam) — only the topbar
  has a `1px solid var(--chrome-border)` bottom edge.
- Drive ALL colors through CSS tokens — never hardcode hex in a component:
  - `var(--surface-ground|inset|card|overlay|border|border-row|border-input|hover)`
    and the numbered ramp `--surface-0…900` (re-based light).
  - `var(--text-color|-secondary|-muted|-muted-2)`.
  - `var(--chrome-*)` for anything sitting on the dark topbar/sidebar (white/light text
    there — `--chrome-bg` topbar, `--chrome-bg-2` sidebar).
  - `var(--ink|-2|-3)` for dark surfaces/borders outside the chrome (e.g. emphasis-card
    top border, dark SYSTEM status card on the dashboard).
  - `var(--primary-color)` = `#FFE600` (the real EY yellow — not a softened gold).
- **Yellow is THE sparse accent — never a large fill or body text.** Used only for:
  active/selected states (sidebar rail, active tab bg, filter chip count, pagination
  current page, selected radio/checkbox fill), progress bars, focus rings
  (`box-shadow: 0 0 0 2px var(--yellow)`), CTA-button bottom borders, the logo beam,
  and hover underlines.
- **Radii are 2px everywhere** (`--radius-sm/md/lg/xl` all = `2px`). Status dots and
  radio dots are the only circles — don't round anything else.
- Semantic status colors (`--success-color`/`--error-color`/`--running-color`/
  `--queued-color` + matching `-text-color` pairs) are muted, banking-appropriate —
  not saturated stoplight colors.
- **No PROD/environment badge and no "internal use only" copy anywhere** (topbar,
  Login) — removed by design decision. Login's dark-panel footer just reads
  `EY · © 2026`.

## Buttons — two primary variants, don't conflate them

Both are ink bg (`--button-primary-bg`) + white text + `13px/600`, 2px radius. The
**only** difference is the CTA border:

- **Header/toolbar primary** (e.g. "+ New Model" in a page header) — plain `.p-button`,
  **no** bottom border, `height: 38px`. This is the default; most primary buttons in the
  app are this variant.
- **CTA / submit-launch primary** (Sign in, Start training, Launch analysis, Re-run
  segment) — add the `.btn-cta` class → adds a `3px solid var(--yellow)` bottom border.
  Typically `height: 40–44px`.

Icons/glyphs inside solid-ink buttons (the "+" in New Model, "▶" in Start training) are
always yellow — handled globally (`.p-button-icon` color rule), don't override per
button. Outlined buttons (secondary actions, e.g. "Job History", "Continue with SSO")
hover to an **ink** border+text, not a muted gray.

## PrimeFlex utility gotcha
`.text-primary` resolves to the yellow accent and is illegible as body text on white.
`styles.scss` (loaded after PrimeFlex) overrides `.text-primary` to ink at rest and a
dark hover. Prefer `text-color`/`text-color-secondary` for identifiers.

## Logo
- v2 uses an inline SVG lockup, not an image file: a yellow beam
  (`<polygon points="0,7 62,0 62,3.4 0,7" fill="#FFE600"/>`) stacked **above** the
  "CREST" wordmark in a column (`flex-direction: column`), not side-by-side. Topbar:
  beam+wordmark column, then a `1px×24px` divider, then the two-line tagline — all in
  one `align-items: flex-end` row. Login (dark left panel): same stacked lockup, scaled
  up (beam `78×9`, wordmark `22px`). It's ink-chrome-only — there is no light-surface
  variant because v2 has no light-background logo placement.

## Layout & hierarchy rules
- Page title: `<h1>` (24px/700, -0.01em). Eyebrow: `.eyebrow` utility (11px/700,
  0.1em tracking, uppercase, muted) — pair with the title, e.g. "ANALYSIS" + "Sector
  Heatmap". Numbers/identifiers use `.font-mono`; supporting text small & muted.
- Flat panels: `surface-card` + 1px `surface-border`, 2px radius, **no shadow**.
  Emphasis cards (KPIs, key metrics) use `.card--emphasis` (3px solid ink top border)
  instead of a shadow to lift off the canvas.
- Primary action lives in the page header, top-right. Filters live above the table,
  never inside it. URLs reflect state (`?tab=`, `?algorithm=`).
- Don't dump everything: >5 controls or >4 sections → push secondary stuff into
  `⋮` row menus, `OverlayPanel` filters, tabs, or create-dialogs.
- Compress: stage tags → colored dot + label; KPI cards → one flat strip with
  dividers; legend boxes → small pills above the chart.
- Empty/loading/error states are first-class: dashed-border placeholder, muted icon,
  one sentence — never a blank div.
- Don't fabricate data for a KPI/caption that isn't backed by a real computation
  (e.g. Dashboard's KPI captions are derived from actual run data, or omitted — never a
  made-up number).

## Tables — one canonical skin

- The app-wide DataTable/paginator/sortable-header skin lives in `_brand.scss`
  (no `!important` — selectors are doubled with `.p-datatable-sm` to beat the
  base theme; see `.claude/bugs/global-important-vs-row-tints.md`). Components
  only declare *deltas*: `BaseTable` keeps its flush-left cell boxes,
  `CommonDataTable` its alignment helpers.
- **CommonDataTable** is the standard server-driven table: header-click
  sorting (instant, server-side), staged search/filters with a **dirty-Apply**
  highlight, skeleton rows on first load, dashed empty state, CSV download.
  Pass `card` + `title` to render it as a self-contained table card inside an
  **unpadded** `.panel` (the workflow tabs pattern); default mode stays flush
  for padded wrappers (DatasetView, credit-risk `.bare-table`).
- Numeric columns: `align: 'right', mono: true` in the column def (or
  `bodyClass="cell-num" headerClass="cell-num-h"` on a raw Column). Widths in
  px, never rem.
- `.panel` is a global class — never re-declare it in a view.
- Shared primitives in `components/ui/`: `EmptyState` (dashed box + icon),
  `RetrainingBanner`, `FilterBar`/`FilterField` (inset strip above results),
  `StageTag` (IFRS 9 stages), plus the existing `StatusDot`/`EySelect`/
  `StatCard`/`PageHeader`. Check here before hand-rolling.

## Dates & times

- Everything renders through `@/utils/datetime` (`fmtDate`, `fmtDateShort`,
  `fmtTime`, `duration`) in the configured display timezone
  (`DATETIME_CONFIG`). Backend serialises full UTC timestamps (log lines
  included — never bare `%H:%M:%S`, which caused an 8-hour log/run-detail
  mismatch). Never format dates ad hoc in a view.

## Filter placements (three sanctioned idioms)

1. **Status/type chips** above job-style lists (All / Auto / Manual with
   counts) — quick mutually-exclusive scopes.
2. **CommonDataTable toolbar + filter strip** — staged, applies on Apply.
3. **FilterBar + FilterField** above a results panel — page-scope selectors
   (target/sector/segment, ECL client/scenario).
Don't invent a fourth.

## Charts
- Charts read CSS tokens via `getComputedStyle` so they auto-adapt to the theme.
  Series palette is `--chart-1…8` (slot 1 = `--yellow-chart #E8C400`, the darkened
  yellow used for chart lines — the raw accent `--yellow` is reserved for UI state,
  not data series). Use the helpers in `@/utils/chartTheme`
  (`cssVar`, `chartPalette`, `scenarioLineStyles`, `fallbackSeriesColors`,
  `axisDefaults`) — never hardcode the token *values* in a chart config.
  Scenario mapping: Baseline = chart-1, Adverse = chart-2 (ink),
  Severely Adverse = chart-3 dashed; on pages where History occupies the ink
  slot (Financial Forecast), both stress scenarios go muted (solid vs dashed).
- apexcharts → time-series & bar/line; chart.js → simple pie/donut;
  plotly.js → statistical residual plots.

## Reference implementations
Before building/redesigning a page, copy the patterns in `views/Dashboard.vue` (page
header w/ CTA buttons, KPI strip, custom grid table, quick-actions list, dark status
card) and `views/auth/Login.vue` (split-screen). For pre-v2 screens not yet touched:
`views/calibrate/CalibrateJobs.vue`, `CalibrateRun.vue`,
`views/credit_risk/CreditRiskECL.vue` — these still use the older rem-based/soft-radius
patterns (`.seg-pill`/`.status-pill`, `.panel`) and will drift visually until migrated;
don't copy their unit choices into new v2 work. Use PrimeVue for behavior; override the
look with scoped `:deep()`. Don't invent a new card style if one exists — check
`components/ui/` (PageHeader, StatCard, StatusDot) first.

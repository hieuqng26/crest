# Design System & Theme

The visual language for every page. Non-negotiable — follow even for "one quick field".

**v2 (current).** CREST is on the v2 EY-style redesign: ink black, a single sparse
yellow accent, and 2px squared corners everywhere. See `design/README.md` (design
tokens + screen-by-screen spec) and `design/CREST Redesign v2.dc.html` (hi-fi reference)
for the full source of truth. This file summarizes the parts that matter for day-to-day
component work.

## Theme architecture

- Base PrimeVue theme: **`ey-light`**, linked in `index.html`
  (`/themes/ey-light/theme.css`). The base theme bakes literal colors into component
  CSS — to change light/dark you switch the `<link>`, not the tokens (tokens alone
  won't override the base theme's literal colors in dropdowns/menus/overlays).
- Refinement layer: **`src/assets/layout/_brand.scss`** — imported last so it wins.
  This is the single source of truth for tokens and component overrides.
- **Ink chrome + light content.** The topbar (`#1A1A24`) and sidebar (`#2E2E38`) are
  the persistent dark frame; content surfaces are light (`--surface-ground #F4F4F6`).
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
  (`box-shadow: 0 0 0 2px var(--yellow)`), the primary-button bottom border, the logo
  beam, and hover underlines. Primary buttons are ink (`--button-primary-bg`) with
  white text and a 3px yellow bottom border; secondary buttons are outlined.
- **Radii are 2px everywhere** (`--radius-sm/md/lg/xl` all = `2px`). Status dots and
  radio dots are the only circles — don't round anything else.
- Semantic status colors (`--success-color`/`--error-color`/`--running-color`/
  `--queued-color` + matching `-text-color` pairs) are muted, banking-appropriate —
  not saturated stoplight colors.

## PrimeFlex utility gotcha
`.text-primary` resolves to the yellow accent and is illegible as body text on white.
`styles.scss` (loaded after PrimeFlex) overrides `.text-primary` to ink at rest and a
dark hover. Prefer `text-color`/`text-color-secondary` for identifiers.

## Logo
- v2 uses an inline SVG lockup, not an image file: a yellow beam
  (`<polygon points="0,7 62,0 62,3.4 0,7" fill="#FFE600"/>`, scaled up on Login) stacked
  above the "CREST" wordmark. It's ink-chrome-only (topbar, sidebar, Login's dark
  panel) — there is no light-surface variant because v2 has no light-background logo
  placement.

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

## Charts
- Charts read CSS tokens via `getComputedStyle` so they auto-adapt to the theme.
  Series palette is `--chart-1…8` (slot 1 = `--yellow-chart #E8C400`, the darkened
  yellow used for chart lines — the raw accent `--yellow` is reserved for UI state,
  not data series).
- apexcharts → time-series & bar/line; chart.js → simple pie/donut;
  plotly.js → statistical residual plots.

## Reference implementations
Before building/redesigning a page, copy the patterns in:
`views/calibrate/CalibrateJobs.vue`, `CalibrateRun.vue`, `views/credit_risk/CreditRiskECL.vue`.
Shared patterns: segmented pill (`.seg-pill`/`.status-pill`), flat panel (`.panel`),
status dot with ping, thin custom progress track, flat-table `:deep()` rules.
Use PrimeVue for behavior; override the look with scoped `:deep()`. Don't invent a new
card style if one exists — check `components/ui/` (PageHeader, StatCard, StatusDot)
first.

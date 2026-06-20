# Design System & Theme

The visual language for every page. Non-negotiable — follow even for "one quick field".

## Theme architecture

- Base PrimeVue theme: **`ey-light`**, linked in `index.html`
  (`/themes/ey-light/theme.css`). The base theme bakes literal colors into component
  CSS — to change light/dark you switch the `<link>`, not the tokens (tokens alone
  won't override the base theme's literal colors in dropdowns/menus/overlays).
- Refinement layer: **`src/assets/layout/_brand.scss`** — imported last so it wins.
  This is the single source of truth for tokens and component overrides.
- **Light, airy content + dark charcoal chrome.** Content surfaces are light; the
  topbar is dark charcoal `#2E2E38` (the only persistent dark band). The sidebar is a
  light card.
- Drive ALL colors through CSS tokens — never hardcode hex in a component:
  - `var(--surface-ground|section|card|overlay|border|hover)` and the numbered ramp
    `--surface-0…900` (re-based light).
  - `var(--text-color|-secondary|-muted)`.
  - `var(--chrome-*)` for anything sitting on the dark topbar (white text there).
  - `var(--primary-color)` = EY light gold `#F2C200` (NOT neon `#FFE600`).
- **EY Yellow is a sparse accent only:** active nav bar, card top-accent, focus ring.
  Never as body text or large fills. Primary buttons are charcoal `#2E2E38` with
  white text; secondary buttons are outlined.
- Radii are soft tokens: `--radius-sm/md/lg/xl` = 6/8/10/14px.
- Status colors must be readable on white — use `-500`/`-600`/`-700` PrimeFlex shades,
  not `-400` (those were tuned for dark and read too pale on white).

## PrimeFlex utility gotcha
`.text-primary` resolves to the gold accent and is illegible as body text on white.
`styles.scss` (loaded after PrimeFlex) overrides `.text-primary` to ink at rest and a
dark amber on hover. Prefer `text-color`/`text-color-secondary` for identifiers.

## Logos
- Dark topbar: `logo-ey.svg` (white "EY").
- Light surfaces (login, auth, error pages): `logo-ey-dark.svg` (charcoal "EY").
- Using the white logo on a light background makes the "EY" letters vanish.

## Layout & hierarchy rules
- Page title: `text-3xl tracking-tight`. Section titles: tiny uppercase
  (`0.7rem`, `letter-spacing: 0.06em`, muted). Numbers/identifiers large & light;
  supporting text small & muted. Never give two elements equal weight unless equal.
- Flat panels: `surface-card` + 1px `surface-border` + ~12px radius. Cards that sit
  on the canvas need a soft shadow (`shadow-1`) to lift off the light background.
- Primary action lives in the page header, top-right. Filters live above the table,
  never inside it. URLs reflect state (`?tab=`, `?algorithm=`).
- Don't dump everything: >5 controls or >4 sections → push secondary stuff into
  `⋮` row menus, `OverlayPanel` filters, tabs, or create-dialogs.
- Compress: stage tags → colored dot + label; KPI cards → one flat strip with
  dividers; legend boxes → small pills above the chart.
- Empty/loading/error states are first-class: dashed-border placeholder, muted icon,
  one sentence — never a blank div.

## Charts
- Charts read CSS tokens via `getComputedStyle` (`components/Charts/utils.js`) so they
  auto-adapt to the theme. Series palette is `--chart-1…8` (slot 1 = gold).
- apexcharts → time-series & bar/line; chart.js → simple pie/donut;
  plotly.js → statistical residual plots.

## Reference implementations
Before building/redesigning a page, copy the patterns in:
`views/calibrate/CalibrateJobs.vue`, `CalibrateRun.vue`, `views/credit_risk/CreditRiskECL.vue`.
Shared patterns: segmented pill (`.seg-pill`/`.status-pill`), flat panel (`.panel`),
status dot with ping, thin custom progress track, flat-table `:deep()` rules.
Use PrimeVue for behavior; override the look with scoped `:deep()`. Don't invent a new
card style if one exists.

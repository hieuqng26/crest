# CREST v2 Redesign — Foundation Pass

## Context
CREST is getting a full EY-style visual redesign + IA restructure ("v2"). The design is
handed off as a hi-fi HTML prototype (`design/CREST Redesign v2.dc.html`) + a detailed
token/screen spec (`design/README.md`). Both already live in the repo, so the "import" is
in place — `DesignSync` is a push-to-remote tool and is **not** needed to read a local
reference.

The v2 system is sharper than the current theme: ink `#1A1A24` + a **sparse** yellow accent
`#FFE600`, **2px radius everywhere**, Archivo (UI) + IBM Plex Mono (data/numbers), flat
cards with hairline borders and a 2px ink rule under table headers. The current
`_brand.scss` is a *different*, softer EY refinement (gold `#F2C200`, 6–14px radii,
Inter/JetBrains Mono) — it gets rewritten.

The IA is also restructured into OVERVIEW / DATA / MODEL / ANALYSIS / JOBS / SYSTEM,
consolidating the old separate Calibration/Forecast/Analysis-launch + Model
Catalog/Configurations modules into **New Model**, **Job History**, and **Analysis**.

**Scope of THIS pass (agreed): Foundation only** — the PrimeVue theme preset, the shell
(top bar + dark sidebar + new nav/IA), routing skeleton for the full v2 nav, **Login**, and
**Dashboard**, all working and on-brand. Every remaining screen is a follow-up pass.

**Decisions carried into later passes** (record now, act later):
- **Delete-as-replaced**: superseded v1 views/routes are removed *when* their consolidated
  replacement lands — not before. This pass deletes nothing; it just drops old entries from
  the nav and adds placeholders for unbuilt v2 screens.
- **Financial Forecast** data already exists in the backend (`credit_risk_results`) — wire
  the real endpoint when that screen is built.
- **Sector Heatmap**: ship illustrative data, but behind a **proper new backend API** whose
  response block can later be swapped for real calculations (no faked data in the frontend).

## Existing architecture (reuse, don't reinvent)
- **Theme**: compiled PrimeVue 3.51 CSS at `public/themes/ey-light/theme.css` (loaded via
  `<link id="theme-css">` in `index.html`) + sakai-style layout SCSS in
  `src/assets/layout/` imported by `layout.scss`. **`src/assets/layout/_brand.scss` is the
  single override layer** (loaded last) — CSS variables + component `!important` overrides.
- **Shell**: `src/layout/AppLayout.vue` (wrapper), `AppTopbar.vue`, `AppSidebar.vue` →
  `AppMenu.vue` (hardcoded `model` nav array) → `AppMenuItem.vue`. Layout state in
  `src/layout/composables/layout.js`.
- **Data layer is complete and reused as-is**: `datasetsAPI`, `calibrationsAPI`,
  `forecastRunsAPI`, `creditRiskAPI`, `roleAPI`, `userAPI`, `logAPI` (`src/api/*`). The
  three run types already share `{queued,running,success,failed}` status + `[{t,level,
  message}]` logs + paginated `{rows,total,columns}` — the shape the future unified Job
  History/Detail needs. Auth via `store` (`login`, `fetchMe`, `logout`; `getCurrentUser`).
- **Shared table**: `components/Table/CommonDataTable.vue` (standard for raw tables).
- **Charts**: `vue3-apexcharts` via `components/Charts/*` + `plot.js`.

## Plan

### 1. Theme preset — rewrite `src/assets/layout/_brand.scss` to v2 tokens
Single source of the visual system; drive everything through CSS variables so it applies
globally.
- **Fonts**: add Google Fonts `<link>` (preconnect + Archivo 400–800, IBM Plex Mono
  400–600) to `services/client/index.html`. Set body `font-family: "Archivo"…`; set
  `code, .font-mono, pre` → `"IBM Plex Mono"`. Provide a `.font-mono` utility used for all
  IDs/timestamps/numbers/metrics.
- **Color tokens** (`:root`): `--ink #1A1A24`, `--ink-2 #2E2E38`, `--ink-3 #3A3A46`;
  `--accent/--primary-color #FFE600`, `--yellow-chart #E8C400`; grays (`--surface-ground
  #F4F4F6`, inset `#F7F7F9`, row-hover `#FAFAF2`, borders `#ECECF0/#E1E1E6/#D8D8DE`, muteds
  `#747480/#9B9BA6`, secondary `#4A4A55`, on-dark `#8A8A98/#B9B9C4`); semantic
  success/error/running/queued per README §Colors.
- **Shape**: set every `--radius-*` and `--border-radius` to **2px**; remove 999px pill
  radii (progress bar → 2px yellow fill; status dots stay circles).
- **Primary button**: ink bg `#1A1A24`, white text, **3px `#FFE600` bottom border**; hover
  bg `#3A3A46`. Keep the existing chained `.p-button:not(...)` override, retargeted to ink.
- **Yellow = accent only**: PrimeVue `--primary-color #FFE600` drives selected radio/
  checkbox fill, highlight, active states; focus ring `box-shadow: 0 0 0 2px #FFE600`.
- **Tables**: `thead th` → 2px solid `#1A1A24` bottom rule, mono-ish uppercase labels;
  rows 1px `#ECECF0` dividers; hover `#FAFAF2`.
- **Emphasis card**: add `.card--emphasis` (3px solid `#1A1A24` top border) utility; flat
  cards = 1px `#E1E1E6` border, no shadow.
- Update chart palette tokens (`--chart-1 #E8C400`, ink series, etc.).
- **Docs**: update `.claude/docs/design.md` so the token table + "yellow is sparse accent"
  guidance reflects v2 (CLAUDE.md points here).

### 2. Shell restyle
- **`AppTopbar.vue`** → 54px ink bar. Replace `<img>` logo with an inline logo lockup:
  yellow-beam SVG `<polygon points="0,7 62,0 62,3.4 0,7" fill="#FFE600"/>` above a "CREST"
  wordmark (16px/800, tracking 0.18em, white), 1px `#3A3A46` divider, 2-line subtitle.
  Right: PROD badge (yellow, 1px `#3A3A46` border) + 28px yellow avatar square with ink
  initials derived from `getCurrentUser().email` + username. Keep the existing
  Change-password / Log-out menu on the avatar (preserves function; matches visual).
- **`AppMenu.vue`** → rewrite the `model` array to the v2 IA with PrimeIcons per item:
  `OVERVIEW`→Dashboard · `DATA`→Datasets · `MODEL`→New Model, Model Results ·
  `ANALYSIS`→Heatmap, Financial Forecast, PD / LGD, IFRS 9 ECL, Transitions ·
  `JOBS`→Job History · `SYSTEM`→User Access Management, Role Management, Audit Logs.
  Preserve the `perm`-based `filteredModel` logic.
- **Sidebar styling** (`_brand.scss` / `_menu.scss`): 236px, bg `#2E2E38`; section labels
  10.5px/700 `#7A7A88` uppercase; items `#B9B9C4`, hover `#3A3A46`; active = 3px `#FFE600`
  **left rail** + `#1A1A24` bg + white 600 text (adapt the existing `.active-route::before`
  rail).
- **Layout metrics**: sidebar 300→236px and topbar 4.5rem→54px in `_content.scss`,
  `_responsive.scss`, `_topbar.scss`, and `.layout-main-container` (page padding 28px 32px,
  content max-width 1440px). Sidebar becomes a flush dark panel (drop the floating
  card/radius/border).

### 3. Routing / IA skeleton — `src/router/index.js`
Add the full v2 route table so nav is structurally correct now:
- Real this pass: `dashboard` (Dashboard.vue), `login`.
- **New routes with a placeholder** (build in later passes): `model_new` (New Model),
  `model_results`, `analysis_heatmap`, `analysis_forecast`, `jobs_history`, `jobs_detail`.
  Create one shared stub `src/views/_ComingSoon.vue` (renders the screen's eyebrow + title
  via route `meta`) so every nav target resolves and is on-brand.
- Keep existing routes for restyle-only screens (Datasets/Dataset View, PD-LGD, ECL,
  Transitions, UAM, Roles, Audit) — the theme restyles them automatically; polish is a
  later pass. Old consolidated v1 routes stay reachable by URL (deleted with their
  replacement). Repoint `/` to redirect to `dashboard`.

### 4. Login — rebuild `src/views/auth/Login.vue` as split-screen
Left 42% (min 380px) `#1A1A24`: logo lockup top; center 48×4px yellow bar + "Credit Risk &
Economic Stress Testing" 34px/700 white + supporting line; bottom PROD badge + "Internal
use only · © 2026". Right `#F4F4F6`: centered 400px white card, **3px ink top border**,
"Sign in", EMAIL + PASSWORD labeled inputs (focus = ink border + 2px yellow ring),
"Forgot?" link, full-width primary button (ink + 3px yellow bottom border), OR divider,
outlined "Continue with SSO". **Keep the existing `store.dispatch('login')` → push
`dashboard` logic.** SSO + Forgot are non-functional stubs (toast "not configured") — noted.

### 5. Dashboard — build `src/views/Dashboard.vue` (currently empty)
- Greeting `<h1>` + date line; right: "Job History" (outlined → `jobs_history`) + "+ New
  Model" (primary, yellow "+" → `model_new`).
- **4 KPI cards** (`.card--emphasis`): DATASETS, MODEL RUNS, ANALYSIS RUNS, FAILED · LAST 7
  DAYS (value in error red). Aggregate client-side from `datasetsAPI.list()`,
  `calibrationsAPI.list()`, `forecastRunsAPI.list()`, `creditRiskAPI.listRuns()`.
- 1.7fr/1fr grid: left "Recent runs" table (merge the three run lists, tag TRAINING vs
  ANALYSIS, sort by finished/created desc, top ~8; RUN/TYPE/STATUS/FINISHED/BY; rows → run
  detail; "View all" → `jobs_history`); right Quick-actions card (Upload dataset, Train new
  model, Explore heatmap, Review audit trail — 3px yellow left rail on hover, → their
  routes) + dark `#1A1A24` SYSTEM status card.
- Gracefully handle empty/failed fetches (skeletons / "—").

### 6. Shared UI primitives (establish patterns reused by later passes)
Create small, tokenized components: `components/ui/PageHeader.vue` (eyebrow + title +
`#actions` slot), `components/ui/StatCard.vue` (emphasis KPI card), `components/ui/
StatusDot.vue` (semantic dot + text). Use them in Dashboard now.

## Files
- **Theme**: `services/client/src/assets/layout/_brand.scss` (rewrite),
  `services/client/index.html` (fonts), touch `_menu.scss` / `_topbar.scss` /
  `_content.scss` / `_responsive.scss` for metrics; `.claude/docs/design.md` (docs).
- **Shell**: `src/layout/AppTopbar.vue`, `src/layout/AppMenu.vue` (+ minor
  `AppMenuItem.vue`, `AppSidebar.vue`, `AppLayout.vue` if needed).
- **Routing**: `src/router/index.js`, new `src/views/_ComingSoon.vue`.
- **Screens**: `src/views/auth/Login.vue` (rebuild), `src/views/Dashboard.vue` (build).
- **New**: `src/components/ui/{PageHeader,StatCard,StatusDot}.vue`.

## Verification
- `cd services/client && npm run dev` (via the preview tools) — no build/console errors.
- **Login** (`/auth/login`): screenshot the split-screen; confirm ink left panel, yellow
  bar/beam, white card with 3px ink top border, 2px yellow focus ring on inputs, 2px radius,
  Archivo/IBM Plex Mono loaded (`preview_inspect` computed `font-family`, `border-radius`).
- **Shell**: with the infra stack up (`docker compose -f docker-compose.debug.yml up -d` +
  backend) sign in; confirm 54px ink top bar with logo lockup + PROD badge + yellow avatar,
  236px dark sidebar with the 6 new sections, and active item shows the 3px yellow left
  rail. If the backend isn't available, verify Login + shell chrome/nav render and note that
  Dashboard KPI/recent-run data needs the live API.
- **Dashboard**: screenshot KPI strip (emphasis cards, failed count in red) + recent-runs
  table + quick actions/SYSTEM card; click a KPI action and a recent-run row to confirm
  routing.
- Spot-check a restyled-by-theme screen (e.g. Datasets) picks up the new tables/buttons/
  inputs correctly.
- Run `npm run lint`/format if configured; no PrimeVue v4 APIs introduced (stay on v3).

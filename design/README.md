# Handoff: CREST UI Redesign v2 (EY-style)

## Overview
Full visual redesign + IA restructure of CREST (Credit Risk & Economic Stress Testing), an ML platform for banks. The visual system is EY-style: black (#1A1A24), yellow (#FFE600), white/gray, squared corners, and a strict Archivo + IBM Plex Mono type pairing.

**v2 restructures the modules around two user types** — insight-seekers and technical model owners:
- OVERVIEW: Dashboard
- DATA: Datasets (+ Dataset View)
- MODEL: New Model (Auto / Manual modes), Model Results
- ANALYSIS: Heatmap, Financial Forecast, PD / LGD, IFRS 9 ECL, Transitions
- JOBS: Job History (+ Job Detail with per-segment re-run)
- SYSTEM: User Access Management, Role Management, Audit Logs
Plus Login. The old Calibration/Forecast/Analysis-launch modules are consolidated: training launches from New Model; forecasts/analyses surface under Analysis; every run lands in Job History.

## About the Design Files
The bundled `CREST Redesign v2.dc.html` is a **design reference created in HTML** — an interactive prototype showing intended look and behavior, NOT production code to copy directly. Your task is to **recreate this design in the existing CREST codebase** (Vue 3 + PrimeVue, `services/client`) using its established patterns, routing, and data layer. Do NOT rebuild or migrate frameworks. Approach:
- Map the design tokens below into a **custom PrimeVue theme preset** (PrimeVue 4 `definePreset` / CSS-variable overrides; or a custom theme in PrimeVue 3) so colors, radius (2px), and typography apply globally.
- Where the theme doesn't reach, use PrimeVue **pass-through (`pt`) options** and scoped styles to restyle components (DataTable, TabView, Chips, Dropdown, Paginator, etc.).
- The IA change (nav sections, consolidated jobs) is intentional and should be implemented as described.
- The prototype file also contains legacy v1 screens (Model Catalog, Model Configurations, New Calibration, New Forecast, separate job lists) that are unreachable from the v2 nav — **ignore them**; they are superseded.

Note: the file uses a proprietary runtime (`support.js`) and won't render standalone outside its original environment. Treat it as a **source-of-truth spec**: all styles are inline in the markup, so every exact value (hex, px, weight) can be read directly from the file. Sample data in it is illustrative only.

## Fidelity
**High-fidelity.** Colors, typography, spacing, and states are final. Recreate pixel-perfectly at desktop widths.

**Responsiveness:** the prototype is a fixed-width desktop reference (1440px max-width) and is intentionally NOT responsive. Desktop-only is not a design decision — implement sensible responsive behavior using the codebase's existing breakpoints: let data tables scroll horizontally within their card (as Dataset View already demonstrates), collapse multi-column stat strips/KPI grids to 2-up or 1-up on narrow widths, and allow the sidebar to collapse per the app's current pattern. Preserve the token system and component styling at all sizes.

## Design Tokens

### Colors
- `ink` #1A1A24 — primary text, primary buttons, table header rules, dark surfaces (top bar, log console, system card)
- `ink-2` #2E2E38 — sidebar background, secondary dark, chart "Actual/History" series
- `ink-3` #3A3A46 — dark-surface borders, button hover on ink
- `yellow` #FFE600 — THE accent. Used ONLY for: active/selected states (sidebar rail, active tab bg, filter chip count, pagination current page, selected radio/checkbox fill), progress bars, focus rings, primary-button bottom border, logo beam, hover underlines, heatmap growth cells. Never for large decorative fills.
- `yellow-chart` #E8C400 — darkened yellow for chart lines (readability on white)
- Grays: #F4F4F6 (app bg), #F7F7F9 (inset panel / customize panel), #FAFAF2 (row hover — warm tint), #ECECF0 (row borders), #E1E1E6 (card borders), #D8D8DE (input borders), #C4C4CD, #9B9BA6 (muted-2), #747480 (muted), #4A4A55 (secondary text), #8A8A98 / #B9B9C4 / #C9C9D4 (text on dark)
- Semantic (muted, banking-appropriate): success #188647 (text #146B39), error #C4331D (text #A32B18), running #D6B600 (text #8A7600), queued/neutral #9B9BA6 (text #747480)
- Heatmap scale: growth = `rgba(255,214,0, α)` with ink text, α = min(0.10 + v/9·0.85, 0.95); decline = `rgba(46,46,56, α)` with white text when α > 0.45, α = min(0.08 + |v|/9·0.8, 0.9)

### Typography
- UI: **Archivo** (Google Fonts; weights 400/500/600/700/800). Closest free match to EY Interstate.
- Data/numeric/code: **IBM Plex Mono** (400/500/600) — all IDs, timestamps, numbers, metrics, log lines, table figures, hyperparameter names.
- Scale: page title 24px/700 (-0.01em); eyebrow 11px/700 letter-spacing 0.1em uppercase #747480; card title 13.5px/700; section label 11px/700, letter-spacing 0.07–0.1em, uppercase, #747480; body 13–13.5px; table cell 12–13.5px; mono cell 11.5–12.5px; KPI value 21–28px mono 600; caption 11.5–12px #9B9BA6.

### Shape & elevation
- Border radius: **2px everywhere** (status dots and radio dots are the only circles). No shadows — flat cards with 1px #E1E1E6 borders.
- Emphasis card: 3px solid #1A1A24 **top border**.
- Tables: 2px solid #1A1A24 rule under the header row; 1px #ECECF0 row dividers; row hover #FAFAF2; grid columns with `column-gap: 12px`.
- Spacing: page padding 28px 32px, max-width 1440px (forms 960–1040px); card padding 16–24px.

## Screens / Views

### Shell (all authenticated screens)
- **Top bar**: 54px, #1A1A24. Left: logo lockup — yellow beam SVG (62×7 polygon) stacked ABOVE "CREST" wordmark (16px/800, letter-spacing 0.18em, white), then 1px #3A3A46 vertical divider, then 2-line subtitle "Credit Risk & Economic Stress Testing" (10.5px #8A8A98). Right: PROD badge (10.5px/700 yellow, 1px #3A3A46 border) + avatar (28px square, yellow bg, ink initials) + username; clicking avatar signs out.
- **Sidebar**: 236px, #2E2E38 (dark). Section labels 10.5px/700 #7A7A88 uppercase. Items 34px tall, 13.5px, #B9B9C4; hover #3A3A46; active: 3px #FFE600 left rail, #1A1A24 bg, white 600 text. Sections as listed in Overview above.

### Login
Split screen. Left 42% (min 380px) #1A1A24: logo lockup top; center — 48×4px yellow bar, then "Credit Risk & Economic Stress Testing" 34px/700 white, supporting line 14px #8A8A98; bottom — PROD badge + "Internal use only · © 2026". Right: #F4F4F6, centered 400px white card (3px ink top border): "Sign in" 21px/700; EMAIL + PASSWORD labeled inputs (42px, focus = ink border + 2px yellow ring); "Forgot?" link with yellow underline; primary button full-width 44px ink bg + 3px yellow bottom border; "OR" divider; "Continue with SSO" outlined button.

### Dashboard (post-login landing)
Greeting h1 + date line; right: "Job History" (outlined) + "+ New Model" (primary, yellow "+"). Row of 4 KPI cards (3px ink top border): DATASETS, MODEL RUNS, ANALYSIS RUNS, FAILED · LAST 7 DAYS (value in error red). Below, 1.7fr/1fr grid: left — "Recent runs" table (RUN name+mono id, TYPE outlined tag TRAINING/ANALYSIS, STATUS dot+text, FINISHED mono, BY) with "View all" yellow-underline link, rows → Job Detail; right — "Quick actions" card (Upload dataset, Train new model, Explore heatmap, Review audit trail; rows get 3px yellow left rail + #FAFAF2 on hover, → arrow) and dark SYSTEM card (#1A1A24) with status rows.

### New Model (form, max-width 1040px)
MODEL eyebrow + title "New Model". **Mode picker**: two radio cards side-by-side — "Auto" (RECOMMENDED tag, ink bg/yellow text: "CREST selects algorithms, tunes hyperparameters and segments automatically…") and "Manual" ("Full control over algorithm, hyperparameters, segmentation and features…"). Selected card: 2px ink border, radio dot yellow-filled with ink center. Then four numbered step cards (3px ink top; step badge = 26px ink square, yellow mono number):
- **01 Dataset** — select + inset #F7F7F9 strip (ROWS / COLUMNS / TYPE).
- **02 Target** — target column select (mono) + inset strip: REGRESSION tag (ink bg, yellow text) + "Objective detected automatically from the target column type".
- **03 Model configuration** — header shows AUTO/MANUAL outlined tag. *Auto*: info panel (4px yellow left bar, #F7F7F9) explaining candidate algorithms (ElasticNet, Ridge, GradientBoosting, RandomForest) + best-by-validation-RMSE + automatic segmentation; below, 2-col grid: OPTIMIZATION METRIC select (RMSE), TRAINING BUDGET select (1 hour max). *Manual*: ALGORITHM select; HYPERPARAMETERS 3-col mono inputs (alpha, l1_ratio, max_iter); SPLIT BY segmented control (active = ink bg yellow text); MAX SEGMENTS stepper; FEATURE COLUMNS removable mono chips.
- **04 Review & train** — MODEL NAME input + summary strip (MODE / ALGORITHM ("Auto-selected" in auto) / DATASET / TARGET / SEGMENTS).
Sticky footer: "Cancel" (outlined) + "▶ Start training" (primary, yellow ▶, 3px yellow bottom border) → Job History.

### Model Results
Title + subtitle. 300px/1fr grid:
- **Left list card**: TRAINED MODELS label; model rows (name 13.5/600; "algo · R² x.xxxx" mono muted; date mono #C4C4CD); active = 3px yellow rail + #F4F4F6 bg.
- **Right**: properties card (3px ink top) — model name mono 19/600 + MODE tag (ink/yellow) + algorithm outlined tag; key/value rows (Algorithm, Mode, Target, Dataset, Split by, Segments, Features, Trained; mono values). Then 4 metric cards (R², MAE, RMSE, MAX |ERR| — mono 24px, 3px ink top). Then "Residual distribution" card (histogram: #2E2E38 bars, modal bar yellow, dashed ink zero line). Then "Backtesting — Actual vs Predicted" chart card (Actual #2E2E38 1.4px, Predicted #E8C400 2.6px, #F0F0F3 gridlines, mono axis labels).

### Heatmap (Analysis)
ANALYSIS eyebrow; title "Sector Heatmap" (or the sector name when drilled); legend right (ink square = Decline, yellow square = Growth). METRIC chips (Revenue growth / COGS / Revenue / Net debt / EBITDA; active = ink bg white text) + mono unit caption (% YoY / Δ pp / Δ turns). Card: grid 230px + 5 year columns (2026–2030), 2px ink rule under header; row label (sector 13px/600 with "›" affordance, cursor pointer) + heat cells: mono 12px/600 signed values, 2px radius, colors per the heatmap scale in tokens. Clicking a sector **drills into companies**: back link "← All sectors", row labels become mono company IDs, column header SECTOR→COMPANY. Footer caption: "Click a sector to view company-level detail" (top level only).

### Financial Forecast (Analysis)
ANALYSIS eyebrow + title; SECTOR + COMPANY dropdowns right. Shared legend: History (#2E2E38 2px), Baseline (#E8C400 3px), Adverse (#9B9BA6 2px), Severely Adverse (#9B9BA6 dashed). 2×2 grid of chart cards (Revenue, COGS / Revenue, Total Assets, Short-term Debts): header = title + unit caption left, 2030-baseline value (mono 19/600) + "±x.x% vs 2025 · baseline 2030" right; SVG chart — history line spans left 55% of plot, three scenario lines fan out from 2025; dashed #D8D8DE vertical divider at the split with "FORECAST →" mono label; #F0F0F3 gridlines, mono year labels (2019/2022/2025/2028/2030).

### PD / LGD, IFRS 9 ECL, Transitions (Analysis)
Unchanged from v1 spec: scenario line charts (Baseline #E8C400 2.6px, Adverse #2E2E38 1.6px, Severely Adverse #9B9BA6 dashed) + detail tables; 8×8 transition heat matrix (ink diagonal with yellow figures, gray-intensity migrations).

### Job History
Title "Job History" + subtitle "Every training, forecast and analysis run"; primary "+ New Model". TYPE filter chips (All / Training / Forecast / Analysis with mono counts; active = ink bg, yellow count) + search. Table: RUN (name + mono uuid), TYPE outlined tag, INPUT (mono — dataset or "target · model"), STATUS dot+text, PROGRESS (running: 5px yellow bar + mono %; else Completed / "Failed at N%" / —), STARTED / FINISHED mono, BY. Rows → Job Detail.

### Job Detail (with per-segment re-run)
"← Job history" back link; status line (dot + SUCCESS + duration mono + TRAINING outlined tag); name h1; "Delete" (outlined) + "Re-run all" (primary). 380px/1fr grid:
- **Left**: RUN DETAILS card (Job ID, Type, Mode, Algorithm, Dataset, Target, Split by, Segments, Triggered by, Started, Finished; mono values) + 100% yellow progress bar.
- **Right**: "Segment models" card — caption "60 segments · showing 6 largest by observations" + segment search. Table: SEGMENT (sector 600 + mono country sub-line), N / R² / RMSE (mono right), STATUS dot+text, ACTION — "Customize" text link (permanent yellow underline; becomes "Close" when open). Clicking Customize expands an **inline panel** below the row (#F7F7F9, full width): "CUSTOMIZE SEGMENT — sector · country" label; 4-col grid (algorithm select + alpha / l1_ratio / max_iter mono inputs); note "Only this segment is retrained — all other segment models are kept"; "Cancel" (outlined) + "▶ Re-run segment" (primary). Re-run closes the panel and flips that row's status to "Re-training" (running amber dot).

### Datasets / Dataset View / UAM / Role Management / Audit Logs
Unchanged from v1 spec (tables with 2px ink header rule, outlined/solid ink tags, text-link actions with yellow/red hover underlines, SEARCH CRITERIA card on Audit Logs).

## Interactions & Behavior
- Sidebar/nav: single-page routing; active item styled as above. Avatar → Login; sign-in → Dashboard.
- New Model: mode cards toggle Auto/Manual (step 03 content and review strip change accordingly); "Start training" → Job History.
- Model Results: list selection swaps properties/metrics.
- Heatmap: metric chips switch data; sector click drills to companies; back link returns.
- Job History: type chips filter; rows → Job Detail. Job Detail: Customize toggles inline panel (one at a time); Re-run segment updates only that row's status.
- Hovers: rows #FAFAF2; outlined buttons border → ink; primary buttons bg → #3A3A46; inputs on focus: border ink + `box-shadow: 0 0 0 2px #FFE600`; text-link hovers use 2px yellow bottom border.
- No transitions/animations required beyond default hover; keep it instant and precise.

## State Management
- Route/screen + active nav; model mode (auto/manual); selected trained model; heatmap metric + drilled sector; job type filter; customizing segment index + re-run segment set; form state (split-by, max segments, features[]).
- Two theme flags exist in the prototype (sidebar dark/light, semantic vs monochrome status colors) — **ship dark sidebar + semantic status**.
- Data comes from existing CREST APIs; all figures in the prototype are illustrative.

## Assets
- No image assets. Logo beam is inline SVG: `<polygon points="0,7 62,0 62,3.4 0,7" fill="#FFE600">` (scaled 78×9 on login).
- Fonts via Google Fonts: Archivo (400–800), IBM Plex Mono (400–600). Charts are inline SVG polylines — reuse the app's existing chart lib, styled to match (colors/weights above).

## Files
- `CREST Redesign v2.dc.html` — the v2 prototype (source of truth). Markup between `<x-dc>` tags is the template (all styles inline; `sc-if`/`sc-for` are conditionals/loops, `{{ }}` are data holes); the `Component` class at the bottom holds sample data, chart-path generation, the heatmap color formula, and the transition-matrix intensity formula. Ignore template blocks for screens not reachable from the v2 sidebar (legacy v1 screens).
- `CREST Redesign.dc.html` — v1 prototype (previous IA), kept for reference only.

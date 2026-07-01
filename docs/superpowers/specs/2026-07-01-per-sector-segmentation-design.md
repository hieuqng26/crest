# Per-Sector Segmentation Customization — Design

## Context

`CalibrateNew.vue`'s "Segmentation" card lets a user pick sectors to segment and set ONE global Split By / Max Segments pair applied to every selected sector. The model configuration and feature columns are also single, run-wide choices. In practice different sectors often warrant different treatment — e.g. a sector with strong country-level variation should split by country while another splits by subsector, or a sector with a small client base benefits from a simpler model. This design adds per-sector customization of segmentation settings, model configuration, and feature columns, while also fixing a visual bug in the current Split By control (the unselected option renders as a blank box).

**Explicitly out of scope:** the target column (`target_col`) stays a single, run-wide value. The Forecast → Credit Risk pipeline assumes one coherent target per `CalibrationRun` (a `ForecastRun` maps to one credit-risk "slot"); letting sectors predict genuinely different targets would break that assumption and requires a much larger redesign than this UI change. This was confirmed with the user during design.

## Data Model

### `CalibrationRun` — new column

```python
seg_sector_overrides_json = db.Column(db.Text, nullable=True)
```

JSON dict keyed by sector name. Values are **sparse** — only fields a sector actually overrides are present:

```json
{
  "Financials": {"split_by": "country", "max_segments": 8, "model_config_id": 3},
  "Energy": {"feature_cols": ["oil_price", "notional_gdp"]}
}
```

Any key missing for a sector (or the sector missing from the dict entirely) falls back to the run's existing global fields: `seg_split_by`, `seg_max_segments`, `model_config_id`, `feature_cols_json`. A run with `seg_sector_overrides_json = null` behaves identically to today — this is purely additive, no migration touches the meaning of existing rows.

### `CalibrationRunSegment` — new column

```python
model_config_id = db.Column(db.Integer, db.ForeignKey("model_configs.id"), nullable=True)
```

Records which model configuration actually trained each segment (relevant once segments can use different models), so the Segments tab / diagnostics can display it directly instead of only being able to infer the run-level default. Nullable so existing segment rows (pre-migration) remain valid with an unknown/implied value.

### Migration

One `alembic` migration: `add_column("calibration_runs", "seg_sector_overrides_json", Text, nullable=True)` and `add_column("calibration_run_segments", "model_config_id", Integer, nullable=True)` + FK constraint to `model_configs.id`. Both nullable, both purely additive — safe, reversible `downgrade()` just drops them.

## Backend

### `project/api/calibrations/routes.py` — `create_run()`

Accept `segmentation.sector_overrides` (dict) alongside the existing `segmentation.sectors` / `split_by` / `max_segments`. Validate each present override the same way the existing global fields are validated:
- `split_by` (if present) ∈ {`subsector`, `country`}
- `max_segments` (if present) is an int in [2, 20]
- `model_config_id` (if present) references an existing `ModelConfig` row
- `feature_cols` (if present) is a list of strings (column-existence is checked at train time against the actual dataset, same as the existing global `feature_cols`, not at submission time)

Only sectors present in `segmentation.sectors` may appear as keys in `sector_overrides`; reject otherwise with a 400.

Store as `json.dumps(sector_overrides)` on the new `CalibrationRun.seg_sector_overrides_json` column (or `None` if empty/absent).

### `project/workers/tasks.py` — `run_calibration()`

Before the per-sector loop starts (still within the "load foreign keys as scalars" phase, before any `_write_progress()` call that could expire ORM objects — see `.claude/bugs/detached-instance-in-celery-tasks.md`):

1. Parse `seg_sector_overrides_json` into a plain dict.
2. Collect the distinct `model_config_id` values referenced by any override, plus the run's own top-level `model_config_id`. Query all of them in one pass and extract `{id: (algorithm, hyperparams_json, family)}` into a plain dict — never hold the ORM rows across the loop.

Inside the existing `for sector, df_sector in df_seg.groupby("sector"):` loop, resolve four values per sector from `overrides.get(sector, {})`, falling back to the existing run-level defaults exactly like `split_col`/`max_seg` already do today:

```python
sector_override = overrides.get(sector, {})
split_col = sector_override.get("split_by") or default_split
max_seg = sector_override.get("max_segments") or default_max
sector_cfg_id = sector_override.get("model_config_id") or model_config_id
sector_algorithm, sector_raw_params, sector_model_family = resolved_configs[sector_cfg_id]
sector_feature_cols = sector_override.get("feature_cols") or feature_cols_json
```

Pass `sector_algorithm`, `sector_raw_params`, `sector_feature_cols`, `sector_model_family` into `_fit_segment(...)` (already parameterized on exactly these, per-call — no signature change needed there). When constructing the `CalibrationRunSegment` row after each segment, set `model_config_id=sector_cfg_id`.

No changes needed to `_fit_segment()` itself, `run_forecast()`, or `run_credit_analysis()` — segments already carry their own artifact (model + scaler + feature_cols) independently, and forecast scoring already reads `feature_cols` from each segment's artifact, not from the run-level field. The only downstream consumer that reads `CalibrationRun.feature_cols_json`/`model_config_id` directly (rather than through a segment's artifact) is the *non-segmented* path, which is unaffected by this change.

## Frontend (`CalibrateNew.vue`)

### State changes

- `splitBy` / `maxSegments` (existing refs) stay as the segmentation **defaults**, unchanged in name/behavior.
- `selectedConfig` (Model Configuration) and `featureCols` (Variables card) **stay exactly as they are today** — their cards remain standalone and always visible, since any run (segmented or not) needs a model and a target/feature set. These existing refs double as "the default" a per-sector override starts from; no new top-level refs are introduced.
- New: `sectorOverrides = ref({})` — a plain object keyed by sector name, values `{ customized: boolean, split_by, max_segments, model_config_id, feature_cols }`. Initialized/pruned in the existing `watch(selectedSectors, ...)` handler: adding a sector adds an entry seeded from the current `splitBy`/`maxSegments`/`selectedConfig`/`featureCols` values with `customized: false`; removing a sector deletes its entry.

### Template changes

Card order stays: Dataset → Sectors → **Segmentation** (defaults + overrides, only when sectors selected) → Model Configuration → Variables. Only the Segmentation card's contents change:

1. **Defaults** — the existing Split By `SelectButton` + Max Segments `InputNumber`, unchanged in behavior. Fixes the blank-box rendering bug (likely a missing `unstyled`/CSS-variable contrast issue where the unselected option's text color matches its background — will diagnose against the running dev server).

2. **Per-Sector Overrides accordion** — `<Accordion>` with one `<AccordionTab>` per entry in `selectedSectors`. Tab header: sector name + a `Tag`: muted "Default" when `!sectorOverrides[sector].customized`, or an accent-colored summary (e.g. "Country · RandomForest · 4 features") when customized. Tab body: a toggle bound to `sectorOverrides[sector].customized`; unchecked shows a read-only summary row of the four inherited default values (reading live from `splitBy`/`maxSegments`/`selectedConfig`/`featureCols` so it stays in sync if the user changes a default afterward); checked reveals the same four controls (Split By, Max Segments, a Model Configuration dropdown reusing `configOptions`, a Feature Columns MultiSelect reusing `featureOptions`) scoped to `sectorOverrides[sector]`, plus a small "Reset to default" text button that sets `customized: false`.

### Submit payload

```js
const sectorOverridesPayload = {}
for (const sector of selectedSectors.value) {
  const o = sectorOverrides.value[sector]
  if (!o?.customized) continue
  const diff = {}
  if (o.split_by !== splitBy.value) diff.split_by = o.split_by
  if (o.max_segments !== maxSegments.value) diff.max_segments = o.max_segments
  if (o.model_config_id !== selectedConfig.value) diff.model_config_id = o.model_config_id
  if (!arraysEqual(o.feature_cols, featureCols.value)) diff.feature_cols = o.feature_cols
  if (Object.keys(diff).length) sectorOverridesPayload[sector] = diff
}
```

`segmentation.sector_overrides` is only included in the request body when non-empty, keeping old-style requests (no per-sector customization) byte-identical to today's payload shape.

## Testing

- **Backend**: extend the segmentation coverage in `tests/test_e2e_pipeline.py` (or a new focused test) with a scenario where two sectors get different overrides — one on `country` split with a non-default `max_segments`, one on default settings with an overridden `feature_cols` subset — asserting each segment's `CalibrationRunSegment.model_config_id` and trained feature set matches what was requested for its sector, and that a sector with no override entry falls back to the run-level defaults correctly.
- **Frontend**: no existing frontend test suite in this repo; verify manually via the dev server — accordion expand/collapse, default→customized toggle, "Reset to default", and inspecting the actual submitted payload shape (sparse, only customized sectors present) via browser devtools network tab.

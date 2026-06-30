# Plan: Add Sector / Subsector / Country Portfolio Segmentation

## Context

CREST currently trains a single model per calibration run on the entire dataset. The "sector/subsector/country" feature introduces **portfolio segmentation**: the dataset is partitioned into sector groups, each sector is further split by subsector or country (ranked by EAD), with a tail group collapsed into "Others". Each segment gets its own trained model. At forecast time, each input row is routed to the model whose segment matches its sector+split value.

This plan also removes the dataset-merge feature from the calibration flow (replaced by the assumption that input data is pre-merged) and adds a reusable `SegmentationConfig` entity.

---

## Phase 0: Demo Data Updates

Update CSV files in `services/server/project/data/test_data/`:

- **`financials.csv`** — add columns: `subsector` (string), `ead` (float)
- **`demo_macro_forecast.csv`** — add columns: `sector`, `subsector`, `base_year` (int), `total_assets`, `total_longterm_debts`, `total_shortterm_debts` (floats)

Populate with realistic synthetic values consistent with existing rows (sectors like Energy/Financials/Industrials; subsectors within each; EAD values in $M range).

---

## Phase 1: Database Migration

### New table: `segmentation_configs`

```python
class SegmentationConfig(db.Model):
    __tablename__ = "segmentation_configs"
    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(255), nullable=False)
    description     = db.Column(db.Text, nullable=True)
    default_split   = db.Column(db.String(16), nullable=False)   # 'subsector' | 'country'
    max_segments    = db.Column(db.Integer, default=5)
    sector_rules_json = db.Column(db.Text, nullable=True)        # JSON [{sector, split_by, max_segments}]
    created_by      = db.Column(db.String(64), db.ForeignKey("users.email"))
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    calibration_runs = db.relationship("CalibrationRun", backref="segmentation_config", lazy=True)
```

### New table: `calibration_run_segments`

```python
class CalibrationRunSegment(db.Model):
    __tablename__ = "calibration_run_segments"
    id                   = db.Column(db.Integer, primary_key=True)
    calibration_run_id   = db.Column(db.Integer, db.ForeignKey("calibration_runs.id", ondelete="CASCADE"))
    segment_key          = db.Column(db.String(256))    # "{sector}__{split_value}"
    sector               = db.Column(db.String(128))
    split_by             = db.Column(db.String(16))     # 'subsector' | 'country'
    split_value          = db.Column(db.String(128))    # actual value or "Others"
    row_count            = db.Column(db.Integer)
    ead_total            = db.Column(db.Float, nullable=True)
    artifact_path        = db.Column(db.String(1024))
    train_metrics_json   = db.Column(db.Text, nullable=True)
    val_metrics_json     = db.Column(db.Text, nullable=True)
    status               = db.Column(db.String(32))     # 'success' | 'failed' | 'skipped'
    error_message        = db.Column(db.Text, nullable=True)
```

### Modified table: `calibration_runs`

Add nullable FK column via migration:
```sql
ALTER TABLE calibration_runs ADD COLUMN segmentation_config_id INTEGER REFERENCES segmentation_configs(id);
```

Keep `secondary_dataset_ids_json` and `merge_steps_json` columns — stop populating them; existing rows retain data.

### Migration file

Generate via `flask db migrate -m "add_segmentation_configs_and_segments"` after adding models.
File: `services/server/migrations/versions/<hash>_add_segmentation_configs_and_segments.py`

---

## Phase 2: Backend — Segmentation Config API

### Files to create

**`services/server/project/api/segmentation_configs/`**
- `__init__.py`
- `routes.py` — follows the same pattern as `project/api/model_configs/routes.py`

### Endpoints

| Method | Path | Permission | Notes |
|--------|------|-----------|-------|
| GET | `/api/segmentation-configs/` | `segmentation:read` | Paginated list |
| POST | `/api/segmentation-configs/` | `segmentation:write` | Create |
| GET | `/api/segmentation-configs/:id` | `segmentation:read` | Get one |
| PATCH | `/api/segmentation-configs/:id` | `segmentation:write` | Update |
| GET | `/api/segmentation-configs/:id/refs` | `segmentation:read` | Calibration runs referencing this config |
| DELETE | `/api/segmentation-configs/:id` | `segmentation:write` | 409 if refs exist (use `delete-with-refs.md` skill) |

Request/response schema for create/update:
```json
{
  "name": "Corporate Standard",
  "description": "...",
  "default_split": "subsector",
  "max_segments": 5,
  "sector_rules": [
    { "sector": "Energy", "split_by": "country", "max_segments": 4 }
  ]
}
```

### Register blueprint

In `services/server/project/__init__.py` (or wherever blueprints are registered), add:
```python
from project.api.segmentation_configs.routes import bp as seg_bp
app.register_blueprint(seg_bp, url_prefix="/api/segmentation-configs")
```

### Permission domain

Add `segmentation` to the permission domain list in `services/server/project/api/auth/` (wherever the 9 domains are declared — check `decorators.py` or `permissions.py`). Roles that have `model_config:*` should also get `segmentation:*` by convention (update seed data / sysadmin wildcard already covers it).

---

## Phase 3: Backend — Modified Calibrations API

File: `services/server/project/api/calibrations/routes.py`

### `POST /api/calibrations/` (`create_run`)

**Remove** from accepted body:
- `dataset_ids` (list) → replace with `dataset_id` (single integer, required)
- `merge_steps` (list)
- Secondary dataset validation logic

**Add** to accepted body:
- `segmentation_config_id` (integer, optional)

Store `segmentation_config_id` on the new `CalibrationRun` row.

### New endpoint: `GET /api/calibrations/:run_id/segments`

Returns `calibration_run_segments` rows for the run:
```json
{
  "segments": [
    {
      "segment_key": "Energy__US",
      "sector": "Energy",
      "split_by": "country",
      "split_value": "US",
      "row_count": 142,
      "ead_total": 4820000000.0,
      "status": "success",
      "val_metrics": { "r2": 0.82, "rmse": 0.031 }
    }
  ]
}
```

### Modified: `GET /api/calibrations/:run_id/diagnostics`

Accept optional `?segment_key=Energy__US`. When provided, load the artifact from `CalibrationRunSegment.artifact_path` for that key and compute/return diagnostics for it. When absent (non-segmented run), current behavior unchanged.

---

## Phase 4: Backend — Task Logic

File: `services/server/project/workers/tasks.py`

### `run_calibration` — remove merge logic

Delete lines 272–320 (secondary dataset download + merge loop). Simplify dataset loading to: download single `dataset_id` file → parse → proceed to feature prep.

### `run_calibration` — segmented training path

After dataset loading, check `calibration_run.segmentation_config_id`:

```python
if calibration_run.segmentation_config_id:
    _run_segmented_calibration(db, run, df, seg_config, log_fn)
else:
    _run_single_calibration(db, run, df, log_fn)   # existing logic extracted to helper
```

**`_run_segmented_calibration(...)` logic:**

```python
MIN_ROWS = 10

rules = {r["sector"]: r for r in seg_config.sector_rules}  # override dict
default_split = seg_config.default_split
default_max   = seg_config.max_segments

for sector, df_sector in df.groupby("sector"):
    rule       = rules.get(sector, {})
    split_col  = rule.get("split_by", default_split)   # 'subsector' or 'country'
    max_seg    = rule.get("max_segments", default_max)

    # Rank groups by EAD descending
    ead_ranks = (
        df_sector.groupby(split_col)["ead"]
        .sum()
        .sort_values(ascending=False)
    )
    top_values  = list(ead_ranks.index[:max_seg])
    rest_values = list(ead_ranks.index[max_seg:])

    # Build group map: split_value → df slice
    groups = {v: df_sector[df_sector[split_col] == v] for v in top_values}
    if rest_values:
        others_df = df_sector[df_sector[split_col].isin(rest_values)]
        groups["Others"] = others_df

    for split_value, df_group in groups.items():
        seg_key = f"{sector}__{split_value}"
        if len(df_group) < MIN_ROWS:
            # write skipped segment row
            continue

        # feature prep, fit, diagnostics (reuse extracted helper)
        segment_artifact_path = f"artifacts/{run.run_id}/segments/{seg_key}/model.pkl"
        # ... fit + upload ...

        # write CalibrationRunSegment to DB
        seg_row = CalibrationRunSegment(
            calibration_run_id=run.id,
            segment_key=seg_key,
            sector=sector,
            split_by=split_col,
            split_value=split_value,
            row_count=len(df_group),
            ead_total=float(df_group["ead"].sum()) if "ead" in df_group else None,
            artifact_path=segment_artifact_path,
            ...
        )
        db.session.add(seg_row)

db.session.commit()
run.status = "success"
run.artifact_path = None   # segments table is the manifest
```

### `run_forecast` — segmented prediction path

After loading forecast dataset, check whether the linked `CalibrationRun` has segments:

```python
segments = CalibrationRunSegment.query.filter_by(
    calibration_run_id=cal_run.id, status="success"
).all()

if segments:
    artifact_cache = {}  # segment_key → loaded artifact dict

    results = []
    for _, row in df.iterrows():
        sector = row.get("sector", "")
        split_val = row.get(seg_col_for_sector(sector, segments), "")
        seg_key = f"{sector}__{split_val}"

        if seg_key not in {s.segment_key for s in segments}:
            seg_key = f"{sector}__Others"   # fallback

        if seg_key not in artifact_cache:
            artifact_cache[seg_key] = load_artifact(seg_key_to_path[seg_key])

        art = artifact_cache[seg_key]
        predicted = art["model"].predict([row[art["feature_cols"]].values])[0]
        results.append({...})

    # bulk insert ForecastRunResult
else:
    # existing single-model path unchanged
```

Helper `seg_col_for_sector(sector, segments)` looks up what `split_by` dimension that sector uses (from the segment rows).

---

## Phase 5: Frontend — Merge Removal

File: `services/client/src/views/calibrate/CalibrateNew.vue`

- Remove the `v-for` dataset loop that renders multiple dataset cards
- Remove the merge-step card component
- Remove `intersectColumns`, `projectSchema`, `unjoinable`, `mergeSteps` refs
- Replace `selectedDatasetIds` (array) with `selectedDatasetId` (single integer)
- Update `canLaunch` guard — remove `unjoinable` check
- Update API call: pass `dataset_id` (singular) instead of `dataset_ids`

Delete file: `services/client/src/views/calibrate/mergePlan.js`

---

## Phase 6: Frontend — Segmentation Config Page

### New files

```
services/client/src/views/segmentation/
  SegmentationConfigs.vue   — table page (mirrors Configurations.vue)
  segmentationConfigsAPI.js — API client (mirrors modelConfigsAPI.js)
```

### Router entry

In `services/client/src/router/index.js`, add under the MODELS group:
```js
{
  path: "/segmentation",
  name: "segmentation_configs",
  component: () => import("@/views/segmentation/SegmentationConfigs.vue"),
  meta: { requiresPerm: "segmentation:read" }
}
```

### Sidebar entry

In the sidebar component (check `AppLayout.vue` or `Sidebar.vue`), add "Segmentation" nav item under the MODELS group, alongside "Model Configurations".

### `SegmentationConfigs.vue` layout

Follows `Configurations.vue` pattern:
- Top toolbar: title "Segmentation Configs" + "New Config" button + bulk delete
- DataTable columns: Name | Default Split | Max Segments | Created By | Created At | Actions
- Row actions (3-dot menu): View | Edit | Delete
- Create/Edit dialog:
  - Name (InputText, required)
  - Description (Textarea, optional)
  - Default Split (pill group: `subsector | country`)
  - Max Segments (InputNumber 2–10, default 5)
  - Per-sector overrides table:
    - "Add override" button → appends a row
    - Each row: Sector name (InputText) | Split By (Dropdown) | Max Segments (InputNumber) | Delete row button
  - Save / Cancel buttons

---

## Phase 7: Frontend — Modified CalibrateNew.vue

After merge removal (Phase 5), add a new optional "Segmentation" card between the Dataset card and the Model Configuration card:

```
[Dataset card]           ← now single-dataset dropdown only
[Segmentation card]      ← NEW, optional
[Model Configuration card]
[Variables card]
[Launch button]
```

**Segmentation card UI:**
- Heading: "Segmentation (Optional)"
- Dropdown: lists saved SegmentationConfigs + a "None — single model" option at top (default)
- When a config is selected: shows a read-only preview panel:
  - "Default split: Subsector / Country"
  - "Max segments per sector: N"
  - If sector overrides exist: small table listing them
- Link: "Manage segmentation configs →" (opens `/segmentation` in same tab or new tab)

Update API payload in the launch handler:
```js
calibrationsAPI.create({
  dataset_id:              selectedDatasetId.value,
  segmentation_config_id:  selectedSegConfigId.value || null,
  model_config_id:         selectedConfig.value,
  target_col:              targetCol.value,
  feature_cols:            featureCols.value,
})
```

---

## Phase 8: Frontend — Modified CalibrateRun.vue

File: `services/client/src/views/calibrate/CalibrateRun.vue`

### Overview tab

Add a "Segmentation" info section (only shown when `run.segmentation_config_id` is non-null):
- Config name (linked to segmentation config detail)
- Number of segments trained successfully / skipped / failed

### New "Segments" tab

Appears only for segmented runs. Fetches `GET /api/calibrations/:run_id/segments`.

DataTable columns: Sector | Split By | Split Value | Rows | EAD Total | Primary Val Metric | Status

Clicking a row sets `activeSegmentKey` and re-fetches the Diagnostics tab data using `?segment_key=...`.

### Diagnostics tab

When `activeSegmentKey` is set, pass it as query param to the diagnostics API call. Add a breadcrumb or header showing which segment is being viewed. A "← All segments" link clears the selection.

---

## Verification

1. **Backend unit**:
   - `pytest services/server/tests/` covering `SegmentationConfig` CRUD + the segmented calibration task with a fixture dataset that has `sector`, `subsector`, `country`, `ead` columns.

2. **Migration**:
   - `flask db upgrade` runs cleanly on a fresh DB and on an existing DB with calibration run rows.

3. **End-to-end (browser)**:
   a. Upload `financials.csv` (with new `subsector`+`ead` columns) as a calibration dataset.
   b. Create a SegmentationConfig: default split = subsector, max 3 segments; add one sector override (e.g. Energy → country).
   c. Start a calibration run using that dataset + config.
   d. Verify Segments tab shows expected sector×split_value rows, each with metrics.
   e. Upload updated `demo_macro_forecast.csv` as a forecast dataset.
   f. Run a forecast using the segmented calibration run.
   g. Verify forecast results contain rows routed to correct segment models (check `meta_json` for sector info).

4. **Merge removal verification**:
   - Confirm `CalibrateNew.vue` only shows a single dataset dropdown.
   - Confirm `POST /api/calibrations/` rejects a payload with `dataset_ids` array (returns 422).

5. **Ruff**:
   - `ruff check . --exclude migrations --fix && ruff format . --exclude migrations` from `services/server/`.

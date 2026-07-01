# Per-Sector Segmentation Customization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user segmenting a calibration by sector override Split By, Max Segments, Model Configuration, and Feature Columns per sector (instead of one global setting for every selected sector), with a shared default that pre-fills new sectors and can be overridden individually. Target column stays run-wide.

**Architecture:** One new sparse-JSON column on `CalibrationRun` (`seg_sector_overrides_json`) carries per-sector overrides; sectors absent from it use the run's existing global fields. `run_calibration()`'s per-sector loop resolves each sector's effective config through a new pure function (`_resolve_sector_training_config`) before calling the existing `_fit_segment()` — no change to how a segment is actually trained. The frontend redesigns the "Segmentation" card into a Defaults section plus a collapsed-by-default accordion, one row per selected sector.

**Tech Stack:** Flask-SQLAlchemy, Alembic, Celery, pytest (Flask `app`/`client`/`make_user` fixtures from `tests/conftest.py`), Vue 3 `<script setup>`, PrimeVue 3 (`Accordion`, `MultiSelect`, `Dropdown`, `SelectButton`, `InputNumber`, `Tag`).

## Global Constraints

- Target column (`target_col`) remains a single run-wide value — never per-sector. (Design spec: the Forecast/CreditRisk pipeline assumes one coherent target per `CalibrationRun`.)
- All new DB columns are nullable and additive — a `CalibrationRun`/`CalibrationRunSegment` with no overrides must behave identically to today. No existing-row migration logic.
- `seg_sector_overrides_json` is sparse: only fields a sector actually overrides are present; missing keys fall back to the run-level `seg_split_by` / `seg_max_segments` / `model_config_id` / `feature_cols_json`.
- Hyperparameter search (`search_config_json`, resolved once at submission from the run's top-level `ModelConfig`) only applies to sectors using the run-level default `model_config_id` — a sector overriding to a different algorithm skips search rather than grid-searching over the wrong algorithm's parameter names.
- After any Python edit, from `services/server/`: `ruff check . --exclude migrations --fix && ruff format . --exclude migrations`.
- Never add `Co-Authored-By` trailers to commits. Only commit when explicitly told to.

---

### Task 1: `CalibrationRun.seg_sector_overrides_json` + `CalibrationRunSegment.model_config_id` (migration + models)

**Files:**
- Create: `services/server/migrations/versions/y0z2a4b6c8d0_add_seg_sector_overrides.py`
- Modify: `services/server/project/db_models/calibration_models.py:112-162` (`CalibrationRun`), `:187-229` (`CalibrationRunSegment`)
- Modify: `.claude/docs/database_models.md` (document the two new columns)
- Test: Create `services/server/tests/test_calibration_segmentation_overrides.py`

**Interfaces:**
- Produces: `CalibrationRun.seg_sector_overrides_json` (`Text`, nullable) — raw JSON string, parsed dict shape `{sector: {split_by?, max_segments?, model_config_id?, feature_cols?}}`. `CalibrationRun.to_dict()` gains key `seg_sector_overrides` (parsed dict or `None`, mirroring the existing `seg_sectors` parsing pattern at `calibration_models.py:153-155`).
- Produces: `CalibrationRunSegment.model_config_id` (`Integer`, nullable, FK to `model_configs.id`). `CalibrationRunSegment.to_dict()` gains key `model_config_id`.

- [ ] **Step 1: Write the failing test**

Create `services/server/tests/test_calibration_segmentation_overrides.py`:

```python
"""
Tests for per-sector segmentation overrides (seg_sector_overrides_json on
CalibrationRun, model_config_id on CalibrationRunSegment).

Run from services/server/:
    pytest tests/test_calibration_segmentation_overrides.py -v
"""

import json

import pytest


@pytest.fixture()
def dataset_and_configs(app, make_user):
    from project import db
    from project.db_models.calibration_models import Dataset, ModelConfig

    user = make_user("modeler@example.com", "sysadmin")
    ds = Dataset(
        name="test-calibration-data",
        source="upload",
        file_path="uploads/test/data.csv",
        row_count=100,
        created_by=user.email,
        status="ready",
        kind="calibration",
    )
    cfg_a = ModelConfig(
        name="elastic-default",
        family="regression",
        algorithm="ElasticNet",
        hyperparams_json=json.dumps({"alpha": 1.0, "l1_ratio": 0.5}),
        train_split=0.8,
        created_by=user.email,
    )
    cfg_b = ModelConfig(
        name="rf-tuned",
        family="regression",
        algorithm="RandomForest",
        hyperparams_json=json.dumps({"n_estimators": 200}),
        train_split=0.8,
        created_by=user.email,
    )
    db.session.add_all([ds, cfg_a, cfg_b])
    db.session.commit()
    return {"user": user, "dataset": ds, "cfg_a": cfg_a, "cfg_b": cfg_b}


class TestCalibrationRunSectorOverridesModel:
    def test_seg_sector_overrides_json_round_trips_through_to_dict(
        self, app, dataset_and_configs
    ):
        from project import db
        from project.db_models.calibration_models import CalibrationRun

        d = dataset_and_configs
        overrides = {
            "Financials": {
                "split_by": "country",
                "max_segments": 8,
                "model_config_id": d["cfg_b"].id,
            },
            "Energy": {"feature_cols": ["oil_price", "notional_gdp"]},
        }
        run = CalibrationRun(
            run_id="test-run-1",
            dataset_id=d["dataset"].id,
            model_config_id=d["cfg_a"].id,
            status="queued",
            triggered_by=d["user"].email,
            target_col="total_assets",
            feature_cols_json=json.dumps(["inflation_rate", "notional_gdp"]),
            seg_sectors_json=json.dumps(["Financials", "Energy"]),
            seg_split_by="subsector",
            seg_max_segments=5,
            seg_sector_overrides_json=json.dumps(overrides),
        )
        db.session.add(run)
        db.session.commit()

        fetched = CalibrationRun.query.filter_by(run_id="test-run-1").first()
        result = fetched.to_dict()
        assert result["seg_sector_overrides"] == overrides

    def test_seg_sector_overrides_defaults_to_none(self, app, dataset_and_configs):
        from project import db
        from project.db_models.calibration_models import CalibrationRun

        d = dataset_and_configs
        run = CalibrationRun(
            run_id="test-run-2",
            dataset_id=d["dataset"].id,
            model_config_id=d["cfg_a"].id,
            status="queued",
            triggered_by=d["user"].email,
        )
        db.session.add(run)
        db.session.commit()

        fetched = CalibrationRun.query.filter_by(run_id="test-run-2").first()
        assert fetched.to_dict()["seg_sector_overrides"] is None


class TestCalibrationRunSegmentModelConfigId:
    def test_model_config_id_persists_and_serializes(self, app, dataset_and_configs):
        from project import db
        from project.db_models.calibration_models import (
            CalibrationRun,
            CalibrationRunSegment,
        )

        d = dataset_and_configs
        run = CalibrationRun(
            run_id="test-run-3",
            dataset_id=d["dataset"].id,
            model_config_id=d["cfg_a"].id,
            status="success",
            triggered_by=d["user"].email,
        )
        db.session.add(run)
        db.session.commit()

        seg = CalibrationRunSegment(
            calibration_run_id=run.id,
            segment_key="Financials__Retail Banking",
            sector="Financials",
            split_by="subsector",
            split_value="Retail Banking",
            status="success",
            model_config_id=d["cfg_b"].id,
        )
        db.session.add(seg)
        db.session.commit()

        fetched = CalibrationRunSegment.query.filter_by(
            segment_key="Financials__Retail Banking"
        ).first()
        assert fetched.to_dict()["model_config_id"] == d["cfg_b"].id

    def test_model_config_id_nullable(self, app, dataset_and_configs):
        from project import db
        from project.db_models.calibration_models import (
            CalibrationRun,
            CalibrationRunSegment,
        )

        d = dataset_and_configs
        run = CalibrationRun(
            run_id="test-run-4",
            dataset_id=d["dataset"].id,
            model_config_id=d["cfg_a"].id,
            status="success",
            triggered_by=d["user"].email,
        )
        db.session.add(run)
        db.session.commit()

        seg = CalibrationRunSegment(
            calibration_run_id=run.id,
            segment_key="Energy__Oil & Gas",
            sector="Energy",
            split_by="subsector",
            split_value="Oil & Gas",
            status="success",
        )
        db.session.add(seg)
        db.session.commit()

        fetched = CalibrationRunSegment.query.filter_by(
            segment_key="Energy__Oil & Gas"
        ).first()
        assert fetched.to_dict()["model_config_id"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/server && pytest tests/test_calibration_segmentation_overrides.py -v`
Expected: FAIL — `TypeError: 'seg_sector_overrides_json' is an invalid keyword argument for CalibrationRun` (column doesn't exist yet), and separately `model_config_id` invalid keyword for `CalibrationRunSegment`.

- [ ] **Step 3: Add the columns to the models**

In `services/server/project/db_models/calibration_models.py`, in `CalibrationRun` (after the existing `seg_max_segments` column, currently at line 116):

```python
    seg_max_segments = db.Column(db.Integer, nullable=True)
    seg_sector_overrides_json = db.Column(
        db.Text, nullable=True
    )  # JSON: {sector: {split_by?, max_segments?, model_config_id?, feature_cols?}}
```

In `CalibrationRun.to_dict()`, after the existing `seg_max_segments=self.seg_max_segments,` line:

```python
            seg_max_segments=self.seg_max_segments,
            seg_sector_overrides=json.loads(self.seg_sector_overrides_json)
            if self.seg_sector_overrides_json
            else None,
            is_segmented=self.is_segmented,
```

In `CalibrationRunSegment` (after the existing `split_value` column):

```python
    split_value = db.Column(db.String(128), nullable=False)  # actual value or "Others"
    model_config_id = db.Column(
        db.Integer, db.ForeignKey("model_configs.id"), nullable=True
    )
```

In `CalibrationRunSegment.to_dict()`, after `split_value=self.split_value,`:

```python
            split_value=self.split_value,
            model_config_id=self.model_config_id,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/server && pytest tests/test_calibration_segmentation_overrides.py -v`
Expected: 4 passed

- [ ] **Step 5: Write the migration**

Create `services/server/migrations/versions/y0z2a4b6c8d0_add_seg_sector_overrides.py`:

```python
"""add seg_sector_overrides_json to calibration_runs, model_config_id to calibration_run_segments

Revision ID: y0z2a4b6c8d0
Revises: x8y0z2a4b6c8
Create Date: 2026-07-01
"""

import sqlalchemy as sa
from alembic import op

revision = "y0z2a4b6c8d0"
down_revision = "x8y0z2a4b6c8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "calibration_runs",
        sa.Column("seg_sector_overrides_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "calibration_run_segments",
        sa.Column("model_config_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_crs_model_config",
        "calibration_run_segments",
        "model_configs",
        ["model_config_id"],
        ["id"],
    )


def downgrade():
    op.drop_constraint(
        "fk_crs_model_config", "calibration_run_segments", type_="foreignkey"
    )
    op.drop_column("calibration_run_segments", "model_config_id")
    op.drop_column("calibration_runs", "seg_sector_overrides_json")
```

Verify it's the sole migration head:

```bash
cd services/server && python3 -c "
import os, re
versions_dir = 'migrations/versions'
revs, down_revs = {}, {}
for fname in os.listdir(versions_dir):
    if not fname.endswith('.py'): continue
    content = open(os.path.join(versions_dir, fname)).read()
    m = re.search(r'^revision\s*=\s*[\"\']([^\"\']+)[\"\']', content, re.M)
    if not m: continue
    rev = m.group(1)
    m2 = re.search(r'^down_revision\s*=\s*(.+)$', content, re.M)
    down_revs[rev] = m2.group(1).strip() if m2 else 'None'
    revs[rev] = fname
referenced = set()
for down_val in down_revs.values():
    referenced.update(re.findall(r'[\"\']([a-z0-9]+)[\"\']', down_val))
heads = set(revs.keys()) - referenced
for h in heads: print(h, '->', revs[h])
"
```

Expected output: `y0z2a4b6c8d0 -> y0z2a4b6c8d0_add_seg_sector_overrides.py` (the only head).

- [ ] **Step 6: Update the database docs**

In `.claude/docs/database_models.md`, find the section documenting `calibration_runs` and `calibration_run_segments` columns and add:

```markdown
- `calibration_runs.seg_sector_overrides_json` — sparse per-sector override of
  segmentation settings/model/features: `{sector: {split_by?, max_segments?,
  model_config_id?, feature_cols?}}`. Missing keys per sector fall back to the
  run's own `seg_split_by`/`seg_max_segments`/`model_config_id`/`feature_cols_json`.
- `calibration_run_segments.model_config_id` — which ModelConfig actually trained
  this segment (nullable; null for segments trained before this column existed).
```

- [ ] **Step 7: Lint and format**

Run: `cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations`

- [ ] **Step 8: Commit**

```bash
git add services/server/migrations/versions/y0z2a4b6c8d0_add_seg_sector_overrides.py \
  services/server/project/db_models/calibration_models.py \
  services/server/tests/test_calibration_segmentation_overrides.py \
  .claude/docs/database_models.md
git commit -m "feat(db): add per-sector segmentation override columns

CalibrationRun.seg_sector_overrides_json (sparse per-sector split_by/
max_segments/model_config_id/feature_cols) and CalibrationRunSegment.
model_config_id, both nullable and additive."
```

---

### Task 2: API validation — `calibrations/routes.py` accepts `segmentation.sector_overrides`

**Files:**
- Modify: `services/server/project/api/calibrations/routes.py:94-179` (`create_run()`)
- Test: append to `services/server/tests/test_calibration_segmentation_overrides.py`

**Interfaces:**
- Consumes: `CalibrationRun.seg_sector_overrides_json` from Task 1.
- Produces: `POST /calibrations/` request body accepts `segmentation.sector_overrides: {sector: {split_by?, max_segments?, model_config_id?, feature_cols?}}`. Invalid entries return `400` with the same error-shape convention as the existing segmentation validation (`{"error": "..."}`).

- [ ] **Step 1: Write the failing test**

Append to `services/server/tests/test_calibration_segmentation_overrides.py`:

```python
class TestCreateRunSectorOverridesAPI:
    def _login_headers(self, client, login, dataset_and_configs):
        resp = login(dataset_and_configs["user"].email)
        csrf = resp.headers.get("X-CSRF-TOKEN") or client.get_cookie(
            "csrf_access_token"
        )
        return {"X-CSRF-TOKEN": csrf.value} if csrf else {}

    def test_rejects_override_for_sector_not_in_sectors_list(
        self, client, login, dataset_and_configs
    ):
        d = dataset_and_configs
        login(d["user"].email)
        resp = client.post(
            "/api/calibrations/",
            json={
                "dataset_id": d["dataset"].id,
                "model_config_id": d["cfg_a"].id,
                "target_col": "total_assets",
                "segmentation": {
                    "sectors": ["Financials"],
                    "split_by": "subsector",
                    "max_segments": 5,
                    "sector_overrides": {"Energy": {"max_segments": 8}},
                },
            },
        )
        assert resp.status_code == 400
        assert "Energy" in resp.get_json()["error"]

    def test_rejects_invalid_split_by_in_override(
        self, client, login, dataset_and_configs
    ):
        d = dataset_and_configs
        login(d["user"].email)
        resp = client.post(
            "/api/calibrations/",
            json={
                "dataset_id": d["dataset"].id,
                "model_config_id": d["cfg_a"].id,
                "target_col": "total_assets",
                "segmentation": {
                    "sectors": ["Financials"],
                    "split_by": "subsector",
                    "max_segments": 5,
                    "sector_overrides": {"Financials": {"split_by": "region"}},
                },
            },
        )
        assert resp.status_code == 400

    def test_rejects_unknown_model_config_id_in_override(
        self, client, login, dataset_and_configs
    ):
        d = dataset_and_configs
        login(d["user"].email)
        resp = client.post(
            "/api/calibrations/",
            json={
                "dataset_id": d["dataset"].id,
                "model_config_id": d["cfg_a"].id,
                "target_col": "total_assets",
                "segmentation": {
                    "sectors": ["Financials"],
                    "split_by": "subsector",
                    "max_segments": 5,
                    "sector_overrides": {"Financials": {"model_config_id": 999999}},
                },
            },
        )
        assert resp.status_code == 400

    def test_accepts_valid_sector_overrides_and_stores_them(
        self, client, login, dataset_and_configs
    ):
        d = dataset_and_configs
        login(d["user"].email)
        resp = client.post(
            "/api/calibrations/",
            json={
                "dataset_id": d["dataset"].id,
                "model_config_id": d["cfg_a"].id,
                "target_col": "total_assets",
                "segmentation": {
                    "sectors": ["Financials", "Energy"],
                    "split_by": "subsector",
                    "max_segments": 5,
                    "sector_overrides": {
                        "Financials": {
                            "split_by": "country",
                            "max_segments": 8,
                            "model_config_id": d["cfg_b"].id,
                        }
                    },
                },
            },
        )
        assert resp.status_code == 202, resp.get_json()
        body = resp.get_json()
        assert body["seg_sector_overrides"] == {
            "Financials": {
                "split_by": "country",
                "max_segments": 8,
                "model_config_id": d["cfg_b"].id,
            }
        }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/server && pytest tests/test_calibration_segmentation_overrides.py::TestCreateRunSectorOverridesAPI -v`
Expected: FAIL — the endpoint currently ignores `sector_overrides` entirely, so `test_rejects_override_for_sector_not_in_sectors_list` and the two other rejection tests fail (status 202 instead of 400), and `test_accepts_valid_sector_overrides_and_stores_them` fails (`seg_sector_overrides` missing from response, defaults to `None`).

- [ ] **Step 3: Add validation and storage**

In `services/server/project/api/calibrations/routes.py`, modify the `if seg:` block (currently lines 116-134):

```python
    seg = body.get("segmentation") or None
    seg_sectors_json = None
    seg_split_by = None
    seg_max_segments = None
    seg_sector_overrides_json = None
    if seg:
        sectors = seg.get("sectors") or []
        split_by = seg.get("split_by") or ""
        max_segs = seg.get("max_segments")
        if not sectors or not isinstance(sectors, list):
            return jsonify(
                {"error": "segmentation.sectors must be a non-empty list"}
            ), 400
        if split_by not in ("subsector", "country"):
            return jsonify(
                {"error": "segmentation.split_by must be 'subsector' or 'country'"}
            ), 400
        if not isinstance(max_segs, int) or not (2 <= max_segs <= 20):
            return jsonify(
                {"error": "segmentation.max_segments must be an integer 2–20"}
            ), 400
        seg_sectors_json = json.dumps(sectors)
        seg_split_by = split_by
        seg_max_segments = max_segs

        sector_overrides = seg.get("sector_overrides") or {}
        if sector_overrides:
            if not isinstance(sector_overrides, dict):
                return jsonify(
                    {"error": "segmentation.sector_overrides must be an object"}
                ), 400
            for sector_name, override in sector_overrides.items():
                if sector_name not in sectors:
                    return jsonify(
                        {
                            "error": f"segmentation.sector_overrides has an entry "
                            f"for '{sector_name}', which is not in "
                            f"segmentation.sectors"
                        }
                    ), 400
                if not isinstance(override, dict):
                    return jsonify(
                        {
                            "error": f"segmentation.sector_overrides['{sector_name}'] "
                            f"must be an object"
                        }
                    ), 400
                if "split_by" in override and override["split_by"] not in (
                    "subsector",
                    "country",
                ):
                    return jsonify(
                        {
                            "error": f"segmentation.sector_overrides['{sector_name}']"
                            f".split_by must be 'subsector' or 'country'"
                        }
                    ), 400
                if "max_segments" in override and (
                    not isinstance(override["max_segments"], int)
                    or not (2 <= override["max_segments"] <= 20)
                ):
                    return jsonify(
                        {
                            "error": f"segmentation.sector_overrides['{sector_name}']"
                            f".max_segments must be an integer 2–20"
                        }
                    ), 400
                if "model_config_id" in override:
                    override_cfg = ModelConfig.query.get(
                        int(override["model_config_id"])
                    )
                    if not override_cfg:
                        return jsonify(
                            {
                                "error": f"segmentation.sector_overrides"
                                f"['{sector_name}'].model_config_id "
                                f"{override['model_config_id']} not found"
                            }
                        ), 400
                if "feature_cols" in override and not isinstance(
                    override["feature_cols"], list
                ):
                    return jsonify(
                        {
                            "error": f"segmentation.sector_overrides['{sector_name}']"
                            f".feature_cols must be a list"
                        }
                    ), 400
            seg_sector_overrides_json = json.dumps(sector_overrides)
```

Then in the `CalibrationRun(...)` constructor (currently lines 163-177), add the new field:

```python
        run = CalibrationRun(
            run_id=run_id,
            dataset_id=ds.id,
            model_config_id=cfg.id,
            status="queued",
            triggered_by=get_jwt_identity(),
            search_config_json=search_config_json,
            train_split=cfg.train_split if cfg.train_split is not None else 0.8,
            scaler=cfg.scaler,
            target_col=target_col,
            feature_cols_json=json.dumps(feature_cols),
            seg_sectors_json=seg_sectors_json,
            seg_split_by=seg_split_by,
            seg_max_segments=seg_max_segments,
            seg_sector_overrides_json=seg_sector_overrides_json,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/server && pytest tests/test_calibration_segmentation_overrides.py -v`
Expected: 8 passed (4 from Task 1 + 4 from this task)

- [ ] **Step 5: Lint and format**

Run: `cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations`

- [ ] **Step 6: Commit**

```bash
git add services/server/project/api/calibrations/routes.py \
  services/server/tests/test_calibration_segmentation_overrides.py
git commit -m "feat(api): validate and store per-sector segmentation overrides

POST /calibrations/ accepts segmentation.sector_overrides, validating each
entry's split_by/max_segments/model_config_id/feature_cols the same way
the existing global segmentation fields are validated."
```

---

### Task 3: `run_calibration()` resolves per-sector overrides

**Files:**
- Modify: `services/server/project/workers/tasks.py:310-497` (`run_calibration`, plus a new helper function placed near `_fit_segment` at line 201)
- Test: append to `services/server/tests/test_e2e_pipeline.py`

**Interfaces:**
- Consumes: `CalibrationRun.seg_sector_overrides_json` (Task 1), validated shape from Task 2.
- Produces: `_resolve_sector_training_config(sector, overrides, default_split_by, default_max_segments, default_feature_cols, default_model_config_id, resolved_configs) -> dict` — a pure function (no Flask/DB/MinIO access) returning `{"split_by": str, "max_segments": int, "feature_cols": list, "model_config_id": int, "algorithm": str, "raw_params": dict, "model_family": str, "use_search": bool}`. `resolved_configs` is `dict[int, tuple[str, dict, str]]` mapping `model_config_id -> (algorithm, raw_params, model_family)`.

- [ ] **Step 1: Write the failing test**

Append to `services/server/tests/test_e2e_pipeline.py` (this file already has segmentation-focused pure-function test classes like `TestSegmentationLogic` — this mirrors that pattern, replicating the algorithm from `tasks.py` rather than importing it, exactly like `_resolve_segment_key`/`_client_stage` are replicated elsewhere in this test suite since `tasks.py` pulls in Celery/MinIO/Flask at import time):

```python
# ---------------------------------------------------------------------------
# TestSectorOverrideResolution
#
# Mirrors _resolve_sector_training_config in project/workers/tasks.py.
# Replicated (not imported) because tasks.py pulls in Celery/MinIO/Flask at
# import time — same convention as _resolve_segment_key/_client_stage
# elsewhere in this test suite.
# ---------------------------------------------------------------------------


def _resolve_sector_training_config(
    sector,
    overrides,
    default_split_by,
    default_max_segments,
    default_feature_cols,
    default_model_config_id,
    resolved_configs,
):
    o = overrides.get(sector, {})
    split_by = o.get("split_by") or default_split_by
    max_segments = o.get("max_segments") or default_max_segments
    feature_cols = o.get("feature_cols") or default_feature_cols
    cfg_id = o.get("model_config_id") or default_model_config_id
    algorithm, raw_params, model_family = resolved_configs[cfg_id]
    use_search = cfg_id == default_model_config_id
    return {
        "split_by": split_by,
        "max_segments": max_segments,
        "feature_cols": feature_cols,
        "model_config_id": cfg_id,
        "algorithm": algorithm,
        "raw_params": dict(raw_params),
        "model_family": model_family,
        "use_search": use_search,
    }


class TestSectorOverrideResolution:
    RESOLVED_CONFIGS = {
        1: ("ElasticNet", {"alpha": 1.0, "l1_ratio": 0.5}, "regression"),
        2: ("RandomForest", {"n_estimators": 200}, "regression"),
    }

    def test_sector_with_no_override_uses_defaults(self):
        result = _resolve_sector_training_config(
            "Energy",
            {},
            default_split_by="subsector",
            default_max_segments=5,
            default_feature_cols=["inflation_rate", "notional_gdp"],
            default_model_config_id=1,
            resolved_configs=self.RESOLVED_CONFIGS,
        )
        assert result["split_by"] == "subsector"
        assert result["max_segments"] == 5
        assert result["feature_cols"] == ["inflation_rate", "notional_gdp"]
        assert result["algorithm"] == "ElasticNet"
        assert result["use_search"] is True

    def test_sector_with_partial_override_falls_back_for_missing_keys(self):
        overrides = {"Financials": {"max_segments": 8}}
        result = _resolve_sector_training_config(
            "Financials",
            overrides,
            default_split_by="subsector",
            default_max_segments=5,
            default_feature_cols=["inflation_rate", "notional_gdp"],
            default_model_config_id=1,
            resolved_configs=self.RESOLVED_CONFIGS,
        )
        assert result["max_segments"] == 8  # overridden
        assert result["split_by"] == "subsector"  # fell back to default
        assert result["algorithm"] == "ElasticNet"  # fell back to default

    def test_sector_with_different_model_skips_hyperparameter_search(self):
        overrides = {"Financials": {"model_config_id": 2}}
        result = _resolve_sector_training_config(
            "Financials",
            overrides,
            default_split_by="subsector",
            default_max_segments=5,
            default_feature_cols=["inflation_rate", "notional_gdp"],
            default_model_config_id=1,
            resolved_configs=self.RESOLVED_CONFIGS,
        )
        assert result["algorithm"] == "RandomForest"
        assert result["raw_params"] == {"n_estimators": 200}
        assert result["use_search"] is False, (
            "Overriding to a different algorithm must skip hyperparameter "
            "search — the run's search grid is tuned for the default "
            "algorithm's parameter names"
        )

    def test_sector_with_same_model_config_id_as_default_uses_search(self):
        overrides = {"Financials": {"model_config_id": 1}}
        result = _resolve_sector_training_config(
            "Financials",
            overrides,
            default_split_by="subsector",
            default_max_segments=5,
            default_feature_cols=["inflation_rate", "notional_gdp"],
            default_model_config_id=1,
            resolved_configs=self.RESOLVED_CONFIGS,
        )
        assert result["use_search"] is True

    def test_sector_with_feature_cols_override(self):
        overrides = {"Energy": {"feature_cols": ["oil_price", "coal_price"]}}
        result = _resolve_sector_training_config(
            "Energy",
            overrides,
            default_split_by="subsector",
            default_max_segments=5,
            default_feature_cols=["inflation_rate", "notional_gdp"],
            default_model_config_id=1,
            resolved_configs=self.RESOLVED_CONFIGS,
        )
        assert result["feature_cols"] == ["oil_price", "coal_price"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/server && pytest tests/test_e2e_pipeline.py::TestSectorOverrideResolution -v`
Expected: PASS — this is a self-contained replicated function, so it passes immediately once added (there's nothing in `tasks.py` yet to be "behind"). This step exists to confirm the replicated logic itself is correct and matches the assertions before wiring the real one into `tasks.py` in Step 3.

- [ ] **Step 3: Add `_resolve_sector_training_config` to `tasks.py`**

In `services/server/project/workers/tasks.py`, add this function immediately before `_fit_segment` (currently at line 201):

```python
def _resolve_sector_training_config(
    sector: str,
    overrides: dict,
    default_split_by: str,
    default_max_segments: int,
    default_feature_cols: list,
    default_model_config_id: int,
    resolved_configs: dict[int, tuple[str, dict, str]],
) -> dict:
    """Resolve one sector's effective training config from its override entry
    (if any) plus the run-level defaults. resolved_configs maps
    model_config_id -> (algorithm, raw_params, model_family), pre-fetched for
    every config id referenced anywhere (default + all overrides) so this
    function never touches the DB — call it only after that pre-fetch.
    """
    o = overrides.get(sector, {})
    split_by = o.get("split_by") or default_split_by
    max_segments = o.get("max_segments") or default_max_segments
    feature_cols = o.get("feature_cols") or default_feature_cols
    cfg_id = o.get("model_config_id") or default_model_config_id
    algorithm, raw_params, model_family = resolved_configs[cfg_id]
    # Hyperparameter search is tuned for the run's default algorithm's
    # parameter names; skip it for sectors overriding to a different model so
    # we never grid-search over parameter names that belong to a different
    # algorithm.
    use_search = cfg_id == default_model_config_id
    return {
        "split_by": split_by,
        "max_segments": max_segments,
        "feature_cols": feature_cols,
        "model_config_id": cfg_id,
        "algorithm": algorithm,
        "raw_params": dict(raw_params),
        "model_family": model_family,
        "use_search": use_search,
    }
```

- [ ] **Step 4: Wire it into `run_calibration`**

In `services/server/project/workers/tasks.py`, in the "grab foreign-key IDs" block (currently lines 315-326), add the new field:

```python
        dataset_id = initial.dataset_id
        model_config_id = initial.model_config_id
        search_config_json = initial.search_config_json
        train_split_ratio = (
            initial.train_split if initial.train_split is not None else 0.8
        )
        scaler_name = initial.scaler
        initial_target_col = initial.target_col
        initial_feature_cols_json = initial.feature_cols_json
        initial_seg_sectors_json = initial.seg_sectors_json
        initial_seg_split_by = initial.seg_split_by
        initial_seg_max_segments = initial.seg_max_segments
        initial_seg_sector_overrides_json = initial.seg_sector_overrides_json
```

Immediately after `cfg = ModelConfig.query.get(model_config_id)` / `model_family = cfg.family` (currently lines 339-340), and *before* any `_write_progress()` call (per the detached-instance pattern documented in `.claude/bugs/detached-instance-in-celery-tasks.md` — extract scalars before any call that closes `db.session`), pre-resolve every `ModelConfig` referenced by any sector override:

```python
            ds = Dataset.query.get(dataset_id)
            cfg = ModelConfig.query.get(model_config_id)
            model_family = cfg.family  # extract before session can close

            sector_overrides = json.loads(initial_seg_sector_overrides_json or "{}")
            override_cfg_ids = {
                v["model_config_id"]
                for v in sector_overrides.values()
                if v.get("model_config_id")
            }
            resolved_configs: dict[int, tuple[str, dict, str]] = {
                model_config_id: (cfg.algorithm, json.loads(cfg.hyperparams_json or "{}"), model_family)
            }
            for cid in override_cfg_ids - {model_config_id}:
                override_cfg = ModelConfig.query.get(cid)
                if not override_cfg:
                    raise ValueError(f"Model configuration {cid} not found")
                resolved_configs[cid] = (
                    override_cfg.algorithm,
                    json.loads(override_cfg.hyperparams_json or "{}"),
                    override_cfg.family,
                )
```

Then in the segmentation loop, replace the current per-sector resolution (currently lines 386-388):

```python
                for sector, df_sector in df_seg.groupby("sector"):
                    split_col = default_split
                    max_seg = default_max
```

with:

```python
                for sector, df_sector in df_seg.groupby("sector"):
                    sector_cfg = _resolve_sector_training_config(
                        sector,
                        sector_overrides,
                        default_split,
                        default_max,
                        feature_cols_json,
                        model_config_id,
                        resolved_configs,
                    )
                    split_col = sector_cfg["split_by"]
                    max_seg = sector_cfg["max_segments"]
```

Then update the `_fit_segment(...)` call (currently lines 438-455) to use the resolved per-sector values instead of the run-level `algorithm`/`raw_params`/`feature_cols_json`/`model_family`:

```python
                            try:
                                (
                                    seg_val_metrics,
                                    seg_train_metrics,
                                    seg_artifact_path,
                                ) = _fit_segment(
                                    df_group,
                                    sector_cfg["algorithm"],
                                    sector_cfg["raw_params"],
                                    search_cfg if sector_cfg["use_search"] else None,
                                    train_split_ratio,
                                    scaler_name,
                                    target_col,
                                    sector_cfg["feature_cols"],
                                    sector_cfg["model_family"],
                                    f"artifacts/{run_id}/segments/{seg_key}/model.pkl",
                                    run_id,
                                )
                            except Exception as seg_exc:
                                seg_status = "failed"
                                seg_error = str(seg_exc)
                                logger.warning(f"Segment {seg_key} failed: {seg_exc}")
```

Then update the `CalibrationRunSegment(...)` construction (currently lines 462-483) to record which model trained the segment:

```python
                        with app_session() as s:
                            seg_row = CalibrationRunSegment(
                                calibration_run_id=CalibrationRun.query.filter_by(
                                    run_id=run_id
                                )
                                .first()
                                .id,
                                segment_key=seg_key,
                                sector=sector,
                                split_by=split_col,
                                split_value=split_value,
                                row_count=len(df_group),
                                ead_total=seg_ead,
                                artifact_path=seg_artifact_path,
                                train_metrics_json=json.dumps(seg_train_metrics)
                                if seg_train_metrics
                                else None,
                                val_metrics_json=json.dumps(seg_val_metrics)
                                if seg_val_metrics
                                else None,
                                status=seg_status,
                                error_message=seg_error,
                                model_config_id=sector_cfg["model_config_id"],
                            )
                            s.add(seg_row)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd services/server && pytest tests/test_e2e_pipeline.py::TestSectorOverrideResolution -v`
Expected: 5 passed (unchanged from Step 2 — confirms the function was copied into `tasks.py` without behavior drift)

Run the full suite to confirm nothing else broke:

Run: `cd services/server && pytest tests/ -q`
Expected: all passing (baseline was 123 passed before this task)

- [ ] **Step 6: Lint and format**

Run: `cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations`

- [ ] **Step 7: Commit**

```bash
git add services/server/project/workers/tasks.py services/server/tests/test_e2e_pipeline.py
git commit -m "feat(worker): resolve per-sector segmentation overrides in run_calibration

Each sector's split_by/max_segments/model/features now resolve through
_resolve_sector_training_config (pure function, unit tested) before
_fit_segment runs — sectors with no override behave exactly as before.
A sector overriding to a different model skips hyperparameter search
rather than grid-searching over the wrong algorithm's parameter names."
```

---

### Task 4: Frontend redesign — `CalibrateNew.vue`

**Files:**
- Modify: `services/client/src/views/calibrate/CalibrateNew.vue` (full file — `<script setup>` state additions, `Segmentation` card template replacement)
- Modify: `services/client/src/assets/layout/_brand.scss:224-253` (fix `SelectButton` unselected-option contrast — app-wide theme bug, not scoped to this component)

**Interfaces:**
- Consumes: `POST /calibrations/` body shape `segmentation.sector_overrides` from Task 2. `configOptions`/`featureOptions` (existing computed refs, unchanged).
- Produces: none (leaf UI component).

- [ ] **Step 1: Add per-sector override state**

In the `<script setup>` block, after the existing `watch(selectedSectors, ...)` handler (currently lines 48-53):

```javascript
watch(selectedSectors, (v) => {
  if (!v || v.length === 0) {
    splitBy.value = 'subsector'
    maxSegments.value = 5
  }
})

// Per-sector overrides: keyed by sector name. `customized: false` means the
// sector inherits splitBy/maxSegments/selectedConfig/featureCols live (read
// at submit time, not copied in) — only `customized: true` sectors carry
// their own values.
const sectorOverrides = ref({})

watch(selectedSectors, (sectors, prevSectors) => {
  const prev = prevSectors || []
  for (const sector of sectors) {
    if (!(sector in sectorOverrides.value)) {
      sectorOverrides.value[sector] = {
        customized: false,
        split_by: splitBy.value,
        max_segments: maxSegments.value,
        model_config_id: selectedConfig.value,
        feature_cols: [...featureCols.value],
      }
    }
  }
  for (const sector of prev) {
    if (!sectors.includes(sector)) {
      delete sectorOverrides.value[sector]
    }
  }
})

function resetSectorOverride(sector) {
  sectorOverrides.value[sector] = {
    customized: false,
    split_by: splitBy.value,
    max_segments: maxSegments.value,
    model_config_id: selectedConfig.value,
    feature_cols: [...featureCols.value],
  }
}

function sectorSummary(sector) {
  const o = sectorOverrides.value[sector]
  if (!o?.customized) return 'Default'
  const cfgName = configs.value.find(c => c.id === o.model_config_id)?.name ?? '—'
  const splitLabel = o.split_by === 'country' ? 'Country' : 'Subsector'
  return `${splitLabel} · ${cfgName} · ${o.feature_cols.length || 'all'} features`
}
```

- [ ] **Step 2: Update the submit payload**

Replace the `launch` function's payload construction (currently lines 100-108):

```javascript
const launch = async () => {
  if (!canLaunch.value) {
    toast.add({ severity: 'warn', summary: 'Validation', detail: 'Select a dataset, model config, and target column', life: 3000 })
    return
  }
  submitting.value = true
  try {
    const sectorOverridesPayload = {}
    for (const sector of selectedSectors.value) {
      const o = sectorOverrides.value[sector]
      if (!o?.customized) continue
      const diff = {}
      if (o.split_by !== splitBy.value) diff.split_by = o.split_by
      if (o.max_segments !== maxSegments.value) diff.max_segments = o.max_segments
      if (o.model_config_id !== selectedConfig.value) diff.model_config_id = o.model_config_id
      const sameFeatures =
        o.feature_cols.length === featureCols.value.length &&
        o.feature_cols.every(c => featureCols.value.includes(c))
      if (!sameFeatures) diff.feature_cols = o.feature_cols
      if (Object.keys(diff).length) sectorOverridesPayload[sector] = diff
    }

    const payload = {
      dataset_id:     selectedDatasetId.value,
      model_config_id: selectedConfig.value,
      target_col:     targetCol.value,
      feature_cols:   featureCols.value,
      segmentation:   selectedSectors.value.length > 0
        ? {
            sectors: selectedSectors.value,
            split_by: splitBy.value,
            max_segments: maxSegments.value,
            ...(Object.keys(sectorOverridesPayload).length
              ? { sector_overrides: sectorOverridesPayload }
              : {}),
          }
        : null,
    }
    const { data } = await calibrationsAPI.create(payload)
    toast.add({ severity: 'success', summary: 'Queued', detail: `Run ${data.run_id}`, life: 3000 })
    router.push({ name: 'calibrate_run', params: { run_id: data.run_id }, query: { tab: 'overview' } })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Launch failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    submitting.value = false
  }
}
```

- [ ] **Step 3: Replace the Segmentation card template**

Replace the current "Segmentation settings" card (currently lines 171-192):

```html
    <!-- 3. Segmentation settings (shown only when at least one sector is selected) -->
    <div v-if="selectedSectors.length > 0" class="surface-card border-round shadow-1 p-4 mb-4">
      <h3 class="text-base font-semibold m-0 mb-1">Segmentation</h3>
      <p class="text-xs text-color-secondary m-0 mb-3">
        Set the defaults applied to every selected sector, then optionally customize
        individual sectors below.
      </p>
      <div class="flex flex-column gap-4 mb-4">
        <div class="flex flex-column gap-2">
          <label class="text-xs font-semibold uppercase text-color-secondary">Split By</label>
          <SelectButton
            v-model="splitBy"
            :options="[{ label: 'Subsector', value: 'subsector' }, { label: 'Country', value: 'country' }]"
            optionLabel="label"
            optionValue="value"
            aria-labelledby="split-by-label"
          />
        </div>
        <div class="flex flex-column gap-2" style="max-width: 14rem">
          <label class="text-xs font-semibold uppercase text-color-secondary">Max Segments per Sector</label>
          <InputNumber v-model="maxSegments" :min="2" :max="20" showButtons class="w-full" />
        </div>
      </div>

      <div class="text-xs font-semibold uppercase text-color-secondary mb-2">Per-Sector Overrides</div>
      <Accordion>
        <AccordionTab v-for="sector in selectedSectors" :key="sector">
          <template #header>
            <div class="flex align-items-center justify-content-between w-full pr-3">
              <span>{{ sector }}</span>
              <Tag
                :value="sectorSummary(sector)"
                :severity="sectorOverrides[sector]?.customized ? 'info' : 'secondary'"
                class="text-xs ml-2"
              />
            </div>
          </template>

          <div v-if="sectorOverrides[sector]" class="flex flex-column gap-3">
            <div class="flex align-items-center gap-2">
              <Checkbox
                v-model="sectorOverrides[sector].customized"
                :binary="true"
                :inputId="`customize-${sector}`"
              />
              <label :for="`customize-${sector}`" class="text-sm">Customize this sector</label>
              <Button
                v-if="sectorOverrides[sector].customized"
                label="Reset to default"
                link
                size="small"
                class="ml-auto text-xs"
                @click="resetSectorOverride(sector)"
              />
            </div>

            <div v-if="!sectorOverrides[sector].customized" class="surface-ground border-round p-3 text-xs text-color-secondary">
              Split by <strong>{{ splitBy }}</strong>, max <strong>{{ maxSegments }}</strong> segments,
              model <strong>{{ configs.find(c => c.id === selectedConfig)?.name ?? '—' }}</strong>,
              <strong>{{ featureCols.length || 'all' }}</strong> feature(s).
            </div>

            <div v-else class="flex flex-column gap-4">
              <div class="flex flex-column gap-2">
                <label class="text-xs font-semibold uppercase text-color-secondary">Split By</label>
                <SelectButton
                  v-model="sectorOverrides[sector].split_by"
                  :options="[{ label: 'Subsector', value: 'subsector' }, { label: 'Country', value: 'country' }]"
                  optionLabel="label"
                  optionValue="value"
                />
              </div>
              <div class="flex flex-column gap-2" style="max-width: 14rem">
                <label class="text-xs font-semibold uppercase text-color-secondary">Max Segments</label>
                <InputNumber v-model="sectorOverrides[sector].max_segments" :min="2" :max="20" showButtons class="w-full" />
              </div>
              <div class="flex flex-column gap-2">
                <label class="text-xs font-semibold uppercase text-color-secondary">Model Configuration</label>
                <Dropdown
                  v-model="sectorOverrides[sector].model_config_id"
                  :options="configOptions"
                  optionLabel="label"
                  optionValue="value"
                  placeholder="Select model configuration"
                  class="w-full"
                />
              </div>
              <div class="flex flex-column gap-2">
                <label class="text-xs font-semibold uppercase text-color-secondary">Feature Columns</label>
                <MultiSelect
                  v-model="sectorOverrides[sector].feature_cols"
                  :options="featureOptions"
                  placeholder="All non-target columns"
                  display="chip"
                  class="w-full"
                  filter
                />
              </div>
            </div>
          </div>
        </AccordionTab>
      </Accordion>
    </div>
```

- [ ] **Step 4: Fix the Split By blank-box rendering bug**

Root cause (found by reading `services/client/src/assets/layout/_brand.scss:234-237`): this app-wide rule

```css
.p-button:not(.p-button-text):not(.p-button-outlined):not(.p-button-link):not(.p-button-secondary):not(.p-button-success):not(.p-button-info):not(.p-button-warning):not(.p-button-danger):not(.p-button-help) {
  background: var(--button-primary-bg);
  border: 1px solid var(--button-primary-bg);
  color: var(--button-primary-text);
}
```

forces the solid-charcoal/white-text "primary button" look onto *every* `.p-button` that isn't one of the excluded variants — including `SelectButton`'s individual option buttons. `SelectButton` renders each option as a plain `.p-button` and only adds `.p-highlight` to the *selected* one, so unselected options match this broad selector too: they get `color: var(--button-primary-text)` (white) forced on, while PrimeVue's own base theme renders an unselected `SelectButton` option's background as light/white — white text on a white background is the "blank box" in the screenshot. This is a global theme bug (affects every `SelectButton` in the app, not just this one), so the fix belongs in `_brand.scss`, not a component-scoped style.

This codebase's own convention for a non-primary button state — `.p-button-outlined` at `_brand.scss:244-248` — already solves exactly this: `color: var(--text-color); background: transparent;`. Add the equivalent for `SelectButton`'s unselected state, and make the selected state explicit rather than relying on incidental base-theme behavior. In `services/client/src/assets/layout/_brand.scss`, immediately after the existing `.p-button.p-button-text:hover` block (currently ending around line 253), add:

```css
/* SelectButton: unselected options must not inherit the primary button's
 * forced white text — otherwise they render as a blank box on this theme's
 * light unselected background (see .claude/bugs/ for other theme gotchas). */
.p-selectbutton .p-button:not(.p-highlight) {
  background: transparent;
  border: 1px solid var(--surface-border);
  color: var(--text-color);
}
.p-selectbutton .p-button:not(.p-highlight):hover {
  background: var(--surface-hover);
  border-color: var(--text-color-muted);
  color: var(--text-color);
}
.p-selectbutton .p-button.p-highlight {
  background: var(--button-primary-bg);
  border: 1px solid var(--button-primary-bg);
  color: var(--button-primary-text);
}
```

Start the dev server (`cd services/client && npm run dev`), navigate to New Calibration Run, select a dataset with sectors and a sector, and confirm both Split By options are now legible — the unselected one shows dark text on a light/transparent background, the selected one shows white text on the dark primary background.

- [ ] **Step 5: Manual verification via dev server**

With `npm run dev` running, verify:
1. Selecting 2+ sectors shows both in the Per-Sector Overrides accordion, collapsed, each tagged "Default".
2. Expanding a sector and checking "Customize this sector" reveals editable Split By / Max Segments / Model Configuration / Feature Columns, pre-filled from current defaults.
3. Changing a default (e.g. global Max Segments) updates the read-only summary text for *non-customized* sectors live, but does not change an already-customized sector's values.
4. "Reset to default" un-customizes a sector and its badge returns to "Default".
5. Open browser devtools Network tab, click Launch (or inspect the request without submitting by checking `payload` via a temporary `console.log` if easier), confirm the POST body's `segmentation.sector_overrides` only contains sectors that were actually customized, with only the fields that differ from the default.
6. Confirm the Split By control's unselected option is legible (not a blank box) in both the Defaults section and inside an expanded sector override.

- [ ] **Step 6: Commit**

```bash
git add services/client/src/views/calibrate/CalibrateNew.vue \
  services/client/src/assets/layout/_brand.scss
git commit -m "feat(ui): redesign Segmentation card with per-sector overrides

Defaults (Split By / Max Segments) apply to every selected sector unless
customized; a collapsed-by-default accordion below lets each sector
override split-by, max segments, model configuration, and feature columns
individually. Also fixes a theme-wide bug where SelectButton's unselected
option rendered as a blank box (_brand.scss's primary-button rule forced
white text onto it regardless of selection state)."
```

---

### Task 5: End-to-end verification against the live dev stack

**Files:** none (verification only — no code changes)

**Interfaces:**
- Consumes: everything from Tasks 1–4.

- [ ] **Step 1: Apply the new migration to the dev database**

```bash
docker cp services/server/migrations/versions/y0z2a4b6c8d0_add_seg_sector_overrides.py mst-backend-1:/usr/src/app/migrations/versions/y0z2a4b6c8d0_add_seg_sector_overrides.py
docker cp services/server/project/db_models/calibration_models.py mst-backend-1:/usr/src/app/project/db_models/calibration_models.py
docker cp services/server/project/api/calibrations/routes.py mst-backend-1:/usr/src/app/project/api/calibrations/routes.py
docker cp services/server/project/workers/tasks.py mst-backend-1:/usr/src/app/project/workers/tasks.py
docker exec mst-backend-1 sh -c "cd /usr/src/app && python3 manage.py db upgrade"
```

Expected: migration applies cleanly, ends at `y0z2a4b6c8d0 (head)`.

- [ ] **Step 2: Sync code into the worker container and restart it**

```bash
docker cp services/server/project/db_models/calibration_models.py mst-worker-1:/usr/src/app/project/db_models/calibration_models.py
docker cp services/server/project/workers/tasks.py mst-worker-1:/usr/src/app/project/workers/tasks.py
docker restart mst-worker-1
```

- [ ] **Step 3: Drive a real segmented calibration with a per-sector override, in-process**

Write a script mirroring the pattern used earlier this session (`run_calibration.apply(args=(run_id,))`, direct DB construction, `triggered_by="admin"`) that creates one `CalibrationRun` segmented on 2 sectors (e.g. `Financials`, `Energy`) where `Financials` overrides `split_by="country"` and `Energy` uses defaults, using the live `financials_macro_merged` dataset and two different `ModelConfig` rows (ElasticNet default + one other, e.g. Ridge or RandomForest if one exists — check `ModelConfig.query.all()` first via `docker exec mst-backend-1`).

- [ ] **Step 4: Verify the results**

Query `CalibrationRunSegment` rows for the new run and confirm:
- `Financials` segments have `split_by == "country"` and `model_config_id` matching the override (if one was set).
- `Energy` segments have `split_by == "subsector"` (the run-level default) and `model_config_id` matching the run's own top-level `model_config_id`.
- All segments have `status == "success"`.

- [ ] **Step 5: Report results to the user**

Summarize: migration applied, segments trained with correct per-sector routing, no regressions in the existing (non-overridden) segmentation path.

---

## Self-Review Notes

- **Spec coverage:** Data model (Task 1) ✓, backend validation (Task 2) ✓, backend execution/resolution (Task 3) ✓, frontend Defaults + accordion + bug fix (Task 4) ✓, testing (unit tests in Tasks 1–3, manual frontend verification in Task 4, live E2E in Task 5) ✓. Target-stays-global constraint is enforced structurally — no task touches `target_col` per sector.
- **Type consistency:** `_resolve_sector_training_config`'s return dict keys (`split_by`, `max_segments`, `feature_cols`, `model_config_id`, `algorithm`, `raw_params`, `model_family`, `use_search`) are used identically in the Task 3 Step 4 wiring and the Task 3 Step 1 test.
- **No placeholders:** every step has complete, runnable code.

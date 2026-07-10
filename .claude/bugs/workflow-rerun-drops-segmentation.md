# Workflow re-run silently drops segmentation

**Area:** `project/services/workflows.py` — `rerun_workflow`.

## Symptom

A fresh workflow run is correctly segmented, but **re-running** the same
workflow produces a non-segmented pipeline: no sector/segment in the
calibration logs or forecast results, no sector/segment filters in
Diagnosis & Backtesting, no per-segment models table on each target page, and
no segment breakdown in the credit result.

## Root cause

Segmentation config (`seg_sectors_json`, `seg_split_by`, `seg_max_segments`,
`seg_sector_overrides_json`) is persisted **per child `CalibrationRun`**, not on
`WorkflowRun` (which only stores `targets_json` + `analysis_params_json`).
`rerun_workflow` rebuilt the launch from the workflow row alone and called
`launch_workflow(...)` **without `parsed_seg`**, which defaults to all-`None` —
so the relaunched calibration runs were non-segmented, and every downstream
sector/segment view (which keys off `CalibrationRun.seg_sectors_json`)
disappeared.

Standalone `calibrations /recalibrate` is unaffected: it mutates the existing
run in place and never touches the `seg_*` columns. Forecast/credit reruns reuse
the existing calibration run, so they keep segmentation too. Only the
**workflow** rerun, which recreates calibration runs, lost it.

## Fix

`_original_segmentation(workflow_pk)` recovers the config from the workflow's
first segmented child `CalibrationRun` (a workflow applies one uniform seg
config to all targets) and passes it to `launch_workflow`. Returns `None` for a
non-segmented workflow, preserving existing behaviour.

## Lesson

When state lives on **child** rows rather than the parent, any "relaunch from
parent" path must re-hydrate that state from the children — the parent row is
not a complete snapshot. Check what `create_*` persists where, then make sure
`rerun_*` reads from the same place.

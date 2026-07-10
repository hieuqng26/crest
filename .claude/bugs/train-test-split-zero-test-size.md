# train_test_split InvalidParameterError: test_size 0.0

## Symptom

Calibration fails with:

```
sklearn.utils._param_validation.InvalidParameterError: The 'test_size' parameter
of train_test_split must be a float in the range (0.0, 1.0), an int in the range
[1, inf) or None. Got 0.0 instead.
```

Raised from `project/workers/calibration.py` (both the single-model path and the
`_fit_segment` path) at the `train_test_split(idx, test_size=..., random_state=42)`
calls.

## Root cause

`test_size` was computed as `round(1.0 - train_split_ratio, 4)`. When
`train_split == 1.0` (a 100% train split, no validation holdout) this is `0.0`,
which sklearn rejects.

The trigger was the config form: `ModelConfigurations.vue` defaulted `trainPct`
to **100** (inconsistent with the API's `0.8` fallback), and `SplitSlider` allowed
up to 100%. So the *default* new config was unrunnable.

## Fix (defense in depth, 3 layers)

1. **UI source** — `SplitSlider.vue` max `100 → 95`; `ModelConfigurations.vue`
   default `trainPct 100 → 80` (both `form` init sites). A validation holdout
   always exists.
2. **API boundary** — `api/model_configs/routes.py` `_validate_train_split()`
   rejects anything outside `0.5–0.95` on create + update (400), so no bad row
   is ever persisted.
3. **Worker** — `workers/calibration.py` `_val_test_size()` clamps
   `1 - train_split_ratio` into `(0.05, 0.95)`, so **legacy rows** already stored
   with `train_split == 1.0` no longer crash; they get a 95/5 split.

## Lesson

A slider/percentage input that maps to a `1 - x` fraction must exclude the
endpoints that make the fraction 0 or 1. Validate at the input, at the API, and
keep the worker robust to pre-existing bad data.

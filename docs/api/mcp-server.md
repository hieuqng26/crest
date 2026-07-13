# MCP Server Reference

This document describes the Model Context Protocol (MCP) server in
`packages/scenario-api`. The MCP surface is the agent-facing adapter for
scenario modeling workflows. It runs in parallel with the REST service over the
same database-backed application services and repositories.

The MCP server is intended for trusted AI assistant integrations. It does not
add end-user authentication, authorization, ownership checks, or role
management. Protect remote transports with deployment-level controls.

## Server Identity

FastMCP server name:

```text
Scenario Modeling MCP Server v3.0.0
```

Python entry point:

```bash
cd packages/scenario-api
python -m scenario_api.mcp
```

## Transports

Transport is selected with `MCP_TRANSPORT`.

| Transport | `MCP_TRANSPORT` | Use case |
|-----------|-----------------|----------|
| stdio | `stdio` or unset | Local desktop or CLI assistant integration |
| SSE | `sse` | HTTP-accessible MCP clients using Server-Sent Events |
| Streamable HTTP | `streamable-http` | HTTP MCP clients that support streamable HTTP |

SSE mode also reads `MCP_MOUNT_PATH`, defaulting to `/sse`.

Examples:

```bash
# Local stdio transport
python -m scenario_api.mcp

# SSE transport
MCP_TRANSPORT=sse MCP_MOUNT_PATH=/sse python -m scenario_api.mcp

# Streamable HTTP transport
MCP_TRANSPORT=streamable-http python -m scenario_api.mcp
```

Logs are written to stderr so stdout remains available for MCP protocol traffic.

## Runtime Settings

The MCP server uses the same `ScenarioApiSettings` object as REST for storage
and shared adapter behavior.

| Setting | Default | Purpose |
|---------|---------|---------|
| `DATABASE_URL` | derived from `POSTGRES_*` | Preferred async PostgreSQL URL |
| `POSTGRES_HOST` | `localhost` | PostgreSQL host when `DATABASE_URL` is absent |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_DB` | `scenario_db` | PostgreSQL database |
| `POSTGRES_USER` | `postgres` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `postgres` | PostgreSQL password |
| `SCENARIO_API_PAGE_DEFAULT_LIMIT` | `50` | Shared default page size for adapter use cases |
| `SCENARIO_API_PAGE_MAX_LIMIT` | `200` | Shared maximum page size |
| `SCENARIO_API_STRUCTURED_LOGGING` | `true` | Structured stderr logging |
| `MCP_TRANSPORT` | `stdio` | MCP transport mode |
| `MCP_MOUNT_PATH` | `/sse` | SSE advertised mount path |
| `LOG_LEVEL` | `INFO` | Runtime log level |

The same required storage settings are mirrored in `.env.example`,
`docker-compose.yml`, `docker-compose.dev.yml`, and `docker-compose.test.yml`.
MCP services should use the same database settings as REST when cross-interface
persistence is required.

## Common Response Rules

- Tools accept Pydantic-validated parameters exposed to MCP clients as JSON
  schemas.
- Most mutating and data-discovery tools return JSON strings.
- `get_scenario` returns a structured JSON object.
- `compute_irf` returns a structured JSON object.
- Tool errors are generally returned as JSON payloads with an `error` field,
  `detail` when available, and an actionable `suggestion` when the tool can
  identify one.
- Scenario IDs and workflow IDs are UUID strings.
- Full Monte Carlo draws and posterior payloads are excluded by default unless
  the relevant include flag is set.
- REST and MCP parity is required for persisted state and core fields, not
  byte-for-byte payload shape.

## Tool Summary

| Tool | Purpose | Persistence |
|------|---------|-------------|
| `generate_baseline` | Create BVAR or BVARX baseline scenarios | Creates scenario records |
| `get_scenario` | Retrieve scenario data by UUID | Read-only |
| `apply_overlay` | Create stressed overlay scenarios from a baseline | Creates scenario records |
| `apply_entropy_pooling` | Create constrained pooled scenarios | Creates scenario records when calibration is sufficient |
| `run_quality_gates` | Validate stressed scenarios against baseline | Persists compact validation when shared use cases are active |
| `create_workflow` | Create a multi-step workflow | Creates workflow records |
| `fork_workflow` | Fork a workflow into branch workflows | Creates child workflow records |
| `merge_workflows` | Merge multiple workflows into a scenario | Creates merged scenario records |
| `create_checkpoint` | Save workflow state checkpoint | Creates checkpoint records |
| `rollback_workflow` | Restore workflow state from checkpoint | Updates workflow state |
| `get_workflow_status` | Retrieve workflow state, scenarios, checkpoints, and children | Read-only |
| `fetch_mev_data` | Fetch historical macroeconomic variable records | Read-only |
| `fetch_market_data` | Fetch market instrument records | Read-only |
| `list_countries` | List countries present in MEV data | Read-only |
| `list_variables` | List MEV variables, optionally by country | Read-only |
| `list_market_data` | List market instruments with metadata | Read-only |
| `get_seed_data_stats` | Report loaded seed-data counts and date ranges | Read-only |
| `get_seed_load_summary` | Retrieve latest persisted seed load summary | Read-only |
| `compute_irf` | Compute BVARX impulse response functions | Read-only |
| MEV pipeline tools | See **MEV Expansion Pipeline** section below | Appendix A.2–A.10 |
| `ingest_core_scenario` | Ingest a prescribed core scenario (A.2) | Creates core-scenario records (idempotent on request_id) |
| `align_jump_off` | Align a core scenario's jump-off to internal actuals (A.3) | Read/derive-only |
| `build_mev_ontology` | Load or inspect an MEV ontology (A.4) | Load persists an ontology (idempotent on content) |
| `build_dependency_structures` | Derive driver DAG, aggregation hierarchy, cycle report (A.5) | Read/derive-only |
| `assign_expansion_models` | Assign a model family per target MEV (A.6) | Read/derive-only |
| `fit_expansion_models` | Fit satellites per target (A.6) | Constrained in MVP (unsupported_in_mvp, #68) |
| `expand_mevs` | Run Mode B MEV expansion (A.7) | Constrained in MVP (unsupported_in_mvp, #68) |
| `reconcile_expansion` | Reconcile an expansion under the unified QP (A.8) | Constrained in MVP (unsupported_in_mvp, #68) |
| `validate_expansion` | Run the expansion gate battery (A.9) | Constrained in MVP (unsupported_in_mvp, #68) |
| `package_mevs` | Package a gate-passing expansion run (A.10) | Constrained in MVP (unsupported_in_mvp, #68) |
| `validate_calibration` | Run the probabilistic calibration suite (A.9) | Constrained in MVP (unsupported_in_mvp, #68) |
| `propagate_override` | Propagate governed path overrides through the driver DAG (#25) | Constrained in MVP (unsupported_in_mvp, #68) |
| `propagate_overlay` | Propagate core overlay shocks through the driver DAG (#25) | Constrained in MVP (unsupported_in_mvp, #68) |

`expand_mevs` accepts the full Appendix A.7 parameter surface: the Mode B fields plus the Mode A parameters
`propagate_uncertainty`, `mc_precision_check` (`{percentiles, max_se}`), `model_assignments`, and the
`entropy_pooling_views` list (probability/mean views, #24). Setting `conditional_on_fixed_anchors=false`
selects Mode A. The Mode A / entropy-pooling / override / calibration EXECUTION remains #68-constrained
(their un-rehydratable in-memory bundles are not reconstructable from persisted state), so those ops return
the honest `unsupported_in_mvp` envelope — never a fake success. `propagate_override` / `propagate_overlay`
are named distinctly from the classic-scenario `apply_overlay` tool (a different domain).

## Scenario Tools

### `generate_baseline`

Creates and persists a BVAR or BVARX baseline scenario.

Required fields:

| Field | Type | Notes |
|-------|------|-------|
| `variables` | `string[]` | Non-empty endogenous variable list |
| `horizon` | `integer` | Forecast horizon from `1` to `40` |

Common optional fields:

| Field | Default | Notes |
|-------|---------|-------|
| `name` | `null` | Scenario name |
| `description` | `null` | Scenario description |
| `seed` | `42` | Reproducibility seed |
| `n_draws` | `8000` | Posterior simulation draws, from `10` to `50000` |
| `lags` | `2` | BVAR lag order, from `1` to `8` |
| `prior_type` | `independent_normal_wishart` | `minnesota`, `ridge`, or `independent_normal_wishart` |
| `use_historical_data` | `false` | Use database-backed historical MEV data |
| `country_name` | `null` | Required when historical data is enabled |
| `date_start` | `1990-03-31` | Historical start date |
| `date_end` | `2022-06-30` | Historical end date |
| `store_draws` | `false` | Persist the large raw trajectory draw array for later retrieval via `get_scenario` with `include_draws=true` or `include_fan_chart=true`. Controls ONLY this raw-draw payload — default baseline generation always persists the posterior package (coefficient draws, covariance draws, initial state) needed by `apply_overlay`'s default ensemble mode, regardless of this flag. |

BVARX optional fields:

| Field | Default | Notes |
|-------|---------|-------|
| `exogenous_variables` | `null` | Market data variables used as drivers |
| `endogenous_market_vars` | `null` | Market variables modeled bidirectionally |
| `exogenous_paths` | `null` | Custom future paths, length at least `horizon + exog_lags` |
| `exog_lags` | `1` | Exogenous lag order, from `0` to `4` |
| `projection_methods` | `null` | Per-variable method: `constant`, `ar1`, `drift`, `trend`, `seasonal` |
| `prior_settings` | `null` | Stability and structural-prior overrides |

Example:

```json
{
  "variables": ["Real GDP", "CPI", "Unemployment"],
  "exogenous_variables": ["Crude Oil WTI", "SOFR"],
  "projection_methods": {
    "Crude Oil WTI": "ar1",
    "SOFR": "ar1"
  },
  "horizon": 12,
  "lags": 2,
  "exog_lags": 1,
  "seed": 42,
  "store_draws": true,
  "use_historical_data": true,
  "country_name": "United States",
  "name": "US Macro Baseline"
}
```

Response shape:

```json
{
  "scenario_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "US Macro Baseline",
  "scenario_type": "baseline",
  "model_type": "BVARX",
  "horizon": 12,
  "variables": ["Real GDP", "CPI", "Unemployment"],
  "seed": 42,
  "data_shape": [12, 3],
  "data_source": "historical",
  "exogenous_variables": ["Crude Oil WTI", "SOFR"],
  "n_exog": 2,
  "exog_lags": 1,
  "is_stable": true,
  "fitting_method": "gibbs",
  "warnings": [],
  "message": "Successfully generated BVARX baseline scenario"
}
```

Baseline generation also discloses (retrievable via `get_scenario` or, for
REST, directly on the creation response):

- `posterior_readiness`: whether the stored baseline supports default
  ensemble overlay (`ensemble_ready`), the posterior draw count, and which
  prerequisites (`coefficient_draws`, `covariance_draws`, `initial_state`,
  `exogenous_forecast_paths`) are missing when it does not.
- `prior_disclosure`: the effective prior family, coefficient/covariance
  prior descriptions, effective vs. requested hyperparameters, and whether
  requested settings were applied, partially applied, or defaulted.
- `forecast_assumptions`: precise distribution language — covariance draws
  are **inverse-Wishart covariance draws**, not normal draws; forecast
  innovations are **Gaussian conditional on each covariance draw**, a model
  assumption rather than an empirical guarantee.

### `get_scenario`

Retrieves a persisted scenario by UUID.

| Field | Default | Values |
|-------|---------|--------|
| `scenario_id` | required | Scenario UUID |
| `format` | `records` | `records`, `columns`, `table` |
| `mode` | `mean` | `mean`, `median`, `p5`, `p10`, `p25`, `p50`, `p75`, `p90`, `p95` |
| `include_draws` | `false` | Include full draws and posterior payloads |
| `include_fan_chart` | `false` | Include percentile bands when draws are available |

Example:

```json
{
  "scenario_id": "550e8400-e29b-41d4-a716-446655440000",
  "format": "columns",
  "mode": "p95",
  "include_fan_chart": true
}
```

Default retrieval omits the large raw `draws`, `draws_shape`, and `posterior`
arrays from `parameters` unless `include_draws=true`. Compact audit metadata —
`posterior_readiness` (baseline scenarios), `prior_disclosure`,
`forecast_assumptions`, and pre-computed `fan_chart`/`tail_risk` summaries
(overlay scenarios) — remains in the response regardless of `include_draws`,
so reviewers can determine an overlay's production mode, inputs, and
uncertainty from stored metadata alone without requesting the full draw
arrays.

### `apply_overlay`

Creates and persists a stressed overlay scenario from a baseline.

Required fields:

| Field | Type | Notes |
|-------|------|-------|
| `baseline_id` | UUID string | Existing baseline scenario |
| `shocks` | object array | Non-empty list of shock definitions |

Common optional fields:

| Field | Default | Notes |
|-------|---------|-------|
| `name` | `null` | Overlay name |
| `description` | `null` | Overlay description |
| `use_feedback` | `true` | Resolve bounded feedback loops in standard mode |
| `ensemble` | `true` | Re-project posterior draws for Bayesian stress testing |
| `seed` | `null` | Ensemble reproducibility seed |
| `return_draws` | `false` | Include full ensemble draws in response |

Shaped shock fields:

| Field | Default | Notes |
|-------|---------|-------|
| `variable` | required | Variable to shock |
| `shock_size` | `null` | Percentage or absolute magnitude |
| `shape` | `v_shaped` | `v_shaped`, `u_shaped`, `l_shaped`, `w_shaped` |
| `is_percentage` | `true` | Whether `shock_size` is a percent shock |
| `start_period` | `0` | Zero-based shock start period |
| `duration` | `null` | Number of periods affected |
| `elasticities` | `null` | Cross-variable propagation coefficients |
| `shape_params` | `null` | Advanced shape-specific controls |

Example standard overlay:

```json
{
  "baseline_id": "550e8400-e29b-41d4-a716-446655440000",
  "ensemble": false,
  "name": "GDP downside overlay",
  "shocks": [
    {
      "variable": "Real GDP",
      "shock_size": -5.0,
      "shape": "v_shaped",
      "start_period": 0,
      "duration": 4,
      "elasticities": {
        "Unemployment": -0.5,
        "CPI": 0.3
      },
      "is_percentage": true
    }
  ]
}
```

Ensemble mode requires a posterior-ready baseline. Default baseline
generation always persists the posterior package (coefficient draws,
covariance draws, initial state) regardless of `store_draws`, so ensemble
overlay is available by default; a baseline missing posterior data (e.g. a
legacy record predating this feature) returns a structured
`missing_prerequisite_data` error and creates no overlay scenario.

The response's `mode` field is one of:

- `"ensemble"` — true Bayesian re-projection using posterior draws. Includes
  `valid_draws`, `excluded_draws`, `total_draws`, `valid_draw_ratio`,
  `fan_chart`, `tail_risk`, and `forecast_assumptions`.
- `"deterministic"` — explicit path adjustment on the median baseline path
  (selected via `"ensemble": false`). Contains no ensemble-only fields.

Each entry in `shocks_applied` also reports `target_type`
(`endogenous`/`exogenous`) and `dynamic_semantics`:

- `"state_intervention"` — the shock was applied inside the projection so
  later periods reflect it through the model's own lag dynamics.
- `"exogenous_conditioning"` — the shock conditioned the exogenous path
  before projection so endogenous variables respond through model
  coefficients.
- `"path_adjustment"` — the shock could not be represented dynamically (for
  example, an endogenous variable transformed with `log_diff`/`first_diff`/
  `ratio`) and was applied as a post-projection adjustment instead; this is
  never presented as true ensemble re-projection.

### `apply_entropy_pooling`

Creates a pooled scenario by applying probability constraints to a baseline.

Required fields:

| Field | Type | Notes |
|-------|------|-------|
| `baseline_id` | UUID string | Existing baseline scenario |
| `constraints` | object array | Non-empty list of constraints |

Constraint types:

| Type | Typical parameters |
|------|--------------------|
| `level_at` | `variable`, `quarter`, `level`, optional `tolerance` |
| `peak_by` | `variable`, `quarter`, `min_value`, optional `threshold` |
| `trough_by` | `variable`, `quarter`, `max_value`, optional `threshold` |
| `band` | `variable`, `start_quarter`, `end_quarter`, `lower_bound`, `upper_bound` |

Example:

```json
{
  "baseline_id": "550e8400-e29b-41d4-a716-446655440000",
  "constraints": [
    {
      "constraint_type": "trough_by",
      "parameters": {
        "variable": "Real GDP",
        "quarter": 4,
        "max_value": -2.0,
        "threshold": 0.75
      },
      "description": "GDP contraction by Q4"
    }
  ],
  "seed": 42,
  "name": "Recession Stress Scenario"
}
```

The response includes solver diagnostics, effective sample size, per-constraint
calibration analysis, and `scenario_id`. When effective sample size is too low,
the response may return `scenario_id: null` with calibration guidance instead of
persisting an unreliable pooled scenario.

### `run_quality_gates`

Runs quality gates against a stressed scenario relative to a baseline.

Required fields:

| Field | Type | Notes |
|-------|------|-------|
| `baseline_id` | UUID string | Baseline scenario |
| `stressed_id` | UUID string | Scenario to validate |
| `gates` | object array | Non-empty gate definitions |

Example:

```json
{
  "baseline_id": "550e8400-e29b-41d4-a716-446655440000",
  "stressed_id": "660e8400-e29b-41d4-a716-446655440001",
  "gates": [
    {
      "gate_type": "severity_index",
      "parameters": {
        "max_severity": 3.0
      },
      "description": "Stress severity limit"
    },
    {
      "gate_type": "phillips_curve",
      "parameters": {
        "tolerance": 0.5
      },
      "description": "Inflation and unemployment coherence"
    }
  ]
}
```

## Workflow Tools

Workflow tools are available for agent-led multi-step exploration and checkpoint
management.

| Tool | Required input | Output |
|------|----------------|--------|
| `create_workflow` | `name`, `steps` | `workflow_id`, state, step count |
| `fork_workflow` | `workflow_id`, at least two `branches` | Parent and child workflow IDs |
| `merge_workflows` | At least two `workflow_ids` | Merged scenario ID |
| `create_checkpoint` | `workflow_id`, `checkpoint_name` | Checkpoint ID and scenario count |
| `rollback_workflow` | `workflow_id`, `checkpoint_name` | Restored workflow state |
| `get_workflow_status` | `workflow_id` string | Workflow status, scenarios, checkpoints, children |

Example workflow:

```json
{
  "name": "Q4 Stress Test",
  "description": "Baseline plus downside overlay",
  "steps": [
    {
      "id": "step_baseline",
      "step_type": "baseline",
      "parameters": {
        "variables": ["Real GDP", "CPI"],
        "horizon": 12,
        "seed": 42
      }
    },
    {
      "id": "step_overlay",
      "step_type": "overlay",
      "parameters": {
        "shock_size": -3.0,
        "variable": "Real GDP"
      },
      "depends_on": ["step_baseline"]
    }
  ],
  "merge_strategy": "average",
  "checkpoint_frequency": 0
}
```

## Historical And Market Data Tools

Historical discovery includes modeling metadata by default. Set
`include_metadata=false` for compact discovery. `metadata_level="modeling"`
keeps unit, scale, measurement, and modeling eligibility fields.
`metadata_level="full"` also includes source provider, source indicator, source
file, source category, and year type inside `metadata`. Set
`include_provenance=true` only when source diagnostics are needed.

These metadata controls are shared by `fetch_mev_data`, `fetch_market_data`,
`list_variables`, and `list_market_data`, matching the REST API behavior.
`source_provider` and `source_category` are not default top-level response
fields.

### `fetch_mev_data`

Fetches historical macroeconomic variable records by source-native names or
canonical aliases. A request for `Real GDP` can resolve to the configured Oxford
source indicator while preserving the requested name in the returned records.

```json
{
  "mev_names": ["Real GDP"],
  "country_names": ["Singapore"],
  "date_start": "2015-01-01",
  "date_end": "2022-12-31",
  "frequency": "Q",
  "include_metadata": true,
  "metadata_level": "modeling",
  "include_provenance": false
}
```

### `fetch_market_data`

Fetches historical market instrument records. Oxford commodity-price workbooks
are discoverable as `commodity_price` market data.

```json
{
  "instrument_names": ["Crude oil, Brent"],
  "instrument_types": ["commodity_price"],
  "date_start": "2015-01-01",
  "include_metadata": true,
  "metadata_level": "modeling",
  "include_provenance": false
}
```

### Discovery Tools

| Tool | Parameters | Returns |
|------|------------|---------|
| `list_countries` | none | Country names with MEV data |
| `list_variables` | `country_name`, `source_category`, `modeling_eligible`, `include_metadata`, `metadata_level`, `include_provenance`, `limit`, `offset` | MEV source-series catalog entries |
| `list_market_data` | `instrument_type`, `source_category`, `modeling_eligible`, `include_metadata`, `metadata_level`, `include_provenance`, `limit`, `offset` | Market source-series catalog entries |
| `get_seed_data_stats` | none | MEV and market counts plus date ranges |
| `get_seed_load_summary` | none | Latest seed source mode, status, counts, and issues |

Example compact discovery:

```json
{
  "country_name": "Singapore",
  "include_metadata": false,
  "limit": 20
}
```

Example full metadata request:

```json
{
  "country_name": "Singapore",
  "metadata_level": "full",
  "include_provenance": true,
  "limit": 20
}
```

Latest load summary:

```json
{
  "tool": "get_seed_load_summary",
  "arguments": {}
}
```

## Diagnostic Tool

### `compute_irf`

Computes impulse response functions for a BVARX scenario.

Required fields:

| Field | Type | Notes |
|-------|------|-------|
| `scenario_id` | UUID string | Scenario generated with BVARX model results |
| `shock_variable` | string | Must be one of the scenario's exogenous variables |

Optional fields:

| Field | Default | Notes |
|-------|---------|-------|
| `shock_type` | `std_dev` | `std_dev`, `percent`, `absolute` |
| `shock_size` | `1.0` | Interpreted according to `shock_type` |
| `horizon` | `20` | IRF horizon from `1` to `40` |
| `include_bands` | `true` | Include Bayesian credible bands |
| `confidence_level` | `0.95` | Between `0.5` and `0.99` |
| `n_posterior_draws` | `8000` | From `100` to `20000` |
| `cumulative` | `false` | Return cumulative response |
| `include_fevd` | `false` | Include forecast error variance decomposition |

Example:

```json
{
  "scenario_id": "550e8400-e29b-41d4-a716-446655440000",
  "shock_variable": "Crude Oil WTI",
  "shock_type": "percent",
  "shock_size": 50.0,
  "horizon": 20,
  "include_fevd": true
}
```

## Resources

Resources provide read-only URI access to persisted scenario data.

| URI | Purpose |
|-----|---------|
| `scenario://{scenario_id}` | Retrieve complete scenario data as JSON |
| `scenario://list` | List available scenario summaries |

The currently registered MCP resource handlers expose scenario resources only.
Workflow status is available through the `get_workflow_status` tool.

## Prompts

The MCP server registers guided prompts for common agent workflows.

| Prompt | Purpose |
|--------|---------|
| `comprehensive_stress_test` | End-to-end BVARX stress workflow with entropy pooling and quality gates |
| `quick_baseline_generation` | Short guide for creating BVAR or BVARX baselines |
| `interest_rate_stress_test` | Interest-rate stress workflow using overnight or swap rates |

## REST And MCP Parity

REST and MCP share the same application use cases and PostgreSQL-backed
repositories for core scenario operations. A scenario created by MCP can be
retrieved by REST, and a scenario created by REST can be retrieved by MCP when
both services use the same database settings.

The MCP server also exposes agent-oriented workflow, seed-data discovery, prompt,
and diagnostic tools that are broader than the first-class REST adapter
milestone.

## Validation Commands

From `packages/scenario-api`:

```bash
./.venv/bin/ruff check src/scenario_api
./.venv/bin/pytest -q --tb=short
```

The current full package validation passes the configured coverage gate:

```text
457 passed, 6 skipped
Total coverage: 80.49%
```

## MEV Expansion Pipeline Tools (Appendix A)

The MEV pipeline tools (issue #16 + the M2 completion #31) are thin adapters over the same application
use cases the REST `/api/v1/mev/pipeline` routes call, so both surfaces return an equivalent response.
The full surface is the ten #16 ops plus `validate_calibration` (A.9), `propagate_override` and
`propagate_overlay` (#25). For the engine these operations drive end-to-end (Mode A vs Mode B, the model
families, and the spec-section → module map), see
[MEV Expansion Engine — Capabilities & Traceability](../architecture/mev-expansion-engine.md). Each tool
takes a Pydantic-validated request and returns the **common response envelope** (spec Appendix A.1):

```json
{
  "status": "ok" | "error",
  "request_id": "<uuid, echoed idempotency key>",
  "engine_version": "<scenario-kit-core version>",
  "result": { "...": "..." } ,
  "error": { "code": "...", "detail": "...", "items": [] }
}
```

`status="ok"` implies a non-null `result` and null `error`; `status="error"` implies null `result`
and a non-null `error`. Mutating tools (`ingest_core_scenario`, `build_mev_ontology` load,
`expand_mevs`, `package_mevs`, `propagate_override`, `propagate_overlay`) accept a client `request_id`
and are idempotent. Diagnostics are logged to stderr; tools never write to stdout (the JSON-RPC channel).

### Error Taxonomy (shared with REST)

`error.code` is one of the full Appendix A.1 domain codes:

| Code | Raised when |
|------|-------------|
| `validation_error` | Malformed request, unknown variable/metric, unit mismatch |
| `vintage_mismatch` | Inputs reference different data vintages |
| `anchor_conflict` | Prescribed anchors mutually inconsistent |
| `cycle_detected` | Driver DAG contains an uncollapsed cycle |
| `insufficient_history` | Training window below the required minimum |
| `reconciliation_infeasible` | QP constraint set infeasible (irreducible subset in `items`) |
| `gate_blocked` | MODEL REVIEW / red KPI blocks packaging |
| `ess_collapse` | Entropy-pooling ESS below floor (#24) |
| `gibbs_nonconvergence` | Mode B Student-t Gibbs chains fail R-hat (#29) |
| `nonlinear_residual_exceeded` | Post-projection nonlinear residual above tolerance (registered; A.1 v4.2) |
| `mc_precision` | Monte Carlo standard error exceeds the reporting-precision target (#23) |
| `override_coherence` | Override splice breaks a binding QP equality (#25); violated rows in `items` |
| `double_counting` | A pooling view duplicates a belief already imposed by an overlay/override (#24) |

…or the adapter-level `unsupported_in_mvp` (bundle-heavy operations constrained in the MVP; tracked by
#68 — a DISTINCT capability code, not a domain code). The domain-error → code mapping lives once in
`scenario_api.application.error_taxonomy` and is used identically by both surfaces (per-code MCP≡REST
parity is proven in `tests/contract/test_mev_error_taxonomy.py`).

### Wiring status

- **Fully wired** (real use-case execution, result payload): `ingest_core_scenario`,
  `align_jump_off`, `build_mev_ontology`, `build_dependency_structures`, `assign_expansion_models`.
- **Constrained** (`unsupported_in_mvp`, naming the un-rehydratable in-memory bundle):
  `fit_expansion_models`, `expand_mevs` (incl. the Mode A parameter surface), `reconcile_expansion`,
  `validate_expansion`, `package_mevs`, `validate_calibration`, `propagate_override`, `propagate_overlay`.
  These never fake success; the constrained response is identical on MCP and REST and is parity-covered.
  Stateless artifact persistence is tracked by **#68**.
- **Ontology (§25.6)**: `build_mev_ontology` accepts the per-block `innovation_family`
  (`gaussian`|`student_t`) and `student_t_spec` (`nu > 4`) fields (#29).

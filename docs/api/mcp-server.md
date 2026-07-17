# MCP Server Reference

This document describes the Model Context Protocol (MCP) server in
`services/server/project/mcp_server`. The MCP surface is the agent-facing
adapter for the CREST calibration → forecast → credit-risk workflow. It runs in
parallel with the REST API over the same transport-agnostic application
services (`project/services/*`), so a run launched by MCP is identical to one
launched from the web app.

The MCP server is intended for trusted AI-assistant integrations (it powers the
New Model **Auto** mode). It does **not** add its own end-user authentication,
authorization, ownership checks, or role management — it runs as a single
configured service identity. Protect it with deployment-level controls.

## Server Identity

FastMCP server name:

```text
crest_mcp
```

Python entry point (run from `services/server/`):

```bash
python -m project.mcp_server
```

The process calls `create_app()` for config/DB/cache wiring. Logs go to stderr
so stdout stays clean for stdio protocol traffic; the runtime force-disables
`SQLALCHEMY_ECHO` for the same reason (see
`.claude/bugs/mcp-stdio-sqlalchemy-echo.md`).

## Transports

Transport is selected with `MCP_TRANSPORT`.

| Transport | `MCP_TRANSPORT` | Use case |
|-----------|-----------------|----------|
| stdio | `stdio` (default, or unset) | Local desktop/CLI assistant; the client spawns the process as a subprocess |
| Streamable HTTP | `streamable-http` | A **remote** networked service that clients reach by URL (e.g. the New Model "Auto" mode, or the Claude API MCP connector) |

### stdio

Launched by the MCP client as a subprocess over stdin/stdout. Because the
backend runs in Docker (`./build_debug.sh up`) and the host usually lacks the
native DB deps (`pyodbc`/unixodbc), run it **inside the backend container**,
which already has the deps, `env/.env.dev`, and DB/Redis/MinIO network access:

```bash
docker compose -f docker-compose.debug.yml exec -T backend python3 -m project.mcp_server
```

### Streamable HTTP (remote)

A long-lived HTTP service (stateless JSON). The debug stack runs it as the
`mcp` compose service on port `8090`, path `/mcp`. Every request must carry
`Authorization: Bearer <MCP_AUTH_TOKEN>`; an unauthenticated `GET /healthz` is
provided for liveness probes. See **Security** below — the server has no
per-user auth, so the token + TLS + network controls are the boundary.

```bash
# Bring it up (debug)
docker compose -f docker-compose.debug.yml up -d mcp

# Health (no auth)
curl http://localhost:8090/healthz            # -> ok

# Missing/invalid token -> 401
curl -X POST http://localhost:8090/mcp        # -> 401
```

The server **fails closed**: with `MCP_TRANSPORT=streamable-http` and no
`MCP_AUTH_TOKEN`, it refuses to start.

### Production

`docker-compose.prod.yml` runs the same `mcp` service from `Dockerfile.prod`
(which installs the MCP SDK). Unlike debug it is **not** published on a host
port — the nginx/Caddy ingress terminates TLS and reverse-proxies `/mcp` to
`mcp:8090` over the internal network. The in-repo reference block is in
`services/client/nginx.conf`; prod overrides that file with the host-mounted
`/opt/crest/nginx/nginx.conf`, so **keep that copy in sync**.

Set in `env/.env.prod`:

- `MCP_AUTH_TOKEN` — a strong secret (fails closed without it).
- `MCP_IDENTITY` — an existing `users.email`.
- `MCP_ALLOWED_HOSTS` — the public hostname(s) the ingress forwards as `Host`
  (DNS-rebinding protection stays **on** in prod; a mismatch returns `421`).

Clients then connect to `https://<host>/mcp` with the bearer header.

## Registration (Claude Code / Desktop)

Copy `.mcp.json.example` (repo root) to `.mcp.json` (gitignored).

**stdio (local)** — container form needs no extra env except an identity:

```json
{
  "mcpServers": {
    "crest": {
      "command": "docker",
      "args": [
        "compose", "-f", "docker-compose.debug.yml", "exec", "-T",
        "-e", "MCP_IDENTITY=admin",
        "backend", "python3", "-m", "project.mcp_server"
      ]
    }
  }
}
```

**Streamable HTTP (remote)** — clients that connect by URL send the bearer
token as a header:

```json
{
  "mcpServers": {
    "crest": {
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer <MCP_AUTH_TOKEN>" }
    }
  }
}
```

## Runtime Settings

The MCP server uses the same config classes as REST (`project/config.py`),
selected by `CONFIG_NAME`. It needs the same environment as the API process.

| Setting | Default | Purpose |
|---------|---------|---------|
| `CONFIG_NAME` | base `Config` | Config class: `development` / `production` / `testing` |
| `JWT_SECRET_KEY` | — | **Required** by `create_app()` even though MCP mints no JWTs |
| `MCP_IDENTITY` | `mcp-agent` | Acting user recorded as `triggered_by` on launched runs. **Must be an existing `users.email`** (it is a foreign key) or launches fail |
| `APP_DB_SERVER` / `APP_DB_*` | env | MSSQL connection (pyodbc + ODBC Driver 18) |
| `REDIS_HOST` / `CELERY_BROKER_URL` | env | Redis for Celery dispatch |
| `MINIO_ENDPOINT` / `MINIO_*` | env | MinIO for artifact/dataset reads |
| `APP_DB_ECHO` | `false` | Keep off — echo writes to stdout and corrupts the stdio JSON-RPC stream |

Streamable-http adds:

| Setting | Default | Purpose |
|---------|---------|---------|
| `MCP_TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `MCP_AUTH_TOKEN` | — | **Required** for streamable-http (fails closed). Bearer secret shared with clients |
| `MCP_HOST` / `MCP_PORT` | `0.0.0.0` / `8090` | Bind address |
| `MCP_STREAMABLE_PATH` | `/mcp` | HTTP path |
| `MCP_ALLOWED_HOSTS` | — | Comma-separated public hostname(s) for DNS-rebinding protection (SDK returns `421` for any other `Host`) |
| `MCP_ALLOWED_ORIGINS` | = `MCP_ALLOWED_HOSTS` | Comma-separated allowed origins |
| `MCP_DISABLE_DNS_REBINDING_PROTECTION` | `false` | Set `true` only when a trusted ingress already validates `Host` |

Celery + Redis must be running for a launched run to progress past `queued`;
the MCP server only enqueues.

## Security

The MCP server has **no per-user authentication or RBAC** — it runs as a single
service identity (`MCP_IDENTITY`) and every tool is reachable by any caller that
gets in. Over stdio, "getting in" means being able to spawn the process (e.g.
`docker compose exec`). Over streamable-http, the controls are:

- **Bearer token** (`MCP_AUTH_TOKEN`) — the app-level trust boundary. Anyone
  holding it can launch and read everything. Rotate/revoke out-of-band; supply
  it from a secret, never commit it. The server refuses to start without it.
- **TLS + rate limiting at the ingress** — terminate TLS and rate-limit in
  nginx/your load balancer in front of the server; do not expose the raw port
  publicly.
- **DNS-rebinding protection** — on by default; set `MCP_ALLOWED_HOSTS` to your
  public hostname(s) in production. Disable it only when the ingress validates
  `Host`.

Per-user identity + RBAC is a possible future enhancement; today the token is
the boundary.

## Common Response Rules

- Tools accept Pydantic-validated parameters exposed to MCP clients as JSON
  schemas. Launch tools reuse the same request schemas as the REST API
  (`project/schemas/*`).
- Tools return **JSON objects** (or JSON arrays for the ref listings). There is
  no separate markdown rendering.
- **Launches are asynchronous.** A launch tool returns a `queued` run
  immediately; the Celery worker does the compute. Poll the matching
  `crest_get_*` tool until `status` is `success` or `failed`.
- `run_id` values are **immutable UUID strings**. A rerun creates new runs; no
  run is mutated in place.
- Runs launched via MCP are tagged **`origin: "auto"`** (New Model "Auto"
  mode), distinct from the `manual` wizard — surfaced as the AUTO/MANUAL tag in
  job history.
- **Errors** propagate as `ToolError` with a coded message
  `"[<code>] <message>"` — e.g. `[not_found]`, `[bad_request]`, `[conflict]`
  (dependency lists appended), `[validation_failed]`, `[unprocessable_entity]`.
  Unexpected exceptions are logged to stderr and returned as a generic
  `"Internal server error"` — internals never leak, mirroring the REST error
  boundary (`project/api/error_handlers.py`).
- **Pagination is capped** so results stay within an agent's context budget —
  100 items per list, 200 result rows, 500 log lines. There is no "all rows"
  path.
- REST and MCP parity is required for persisted state and core fields; both
  transports call the same services and read/write the same MSSQL database.

## Tool Summary

Server name `crest_mcp`; every tool is prefixed `crest_`.

| Tool | Purpose | Persistence |
|------|---------|-------------|
| `crest_create_calibration_run` | Launch a model-training run for a dataset + config | Creates a calibration run |
| `crest_create_forecast_run` | Forecast a successful calibration against a dataset | Creates a forecast run |
| `crest_create_credit_risk_run` | Launch an IFRS 9 KMV PD/LGD + ECL analysis | Creates a credit-risk run |
| `crest_create_workflow` | Launch the full train → forecast → analysis pipeline | Creates a workflow + child runs |
| `crest_rerun_workflow` | Relaunch a workflow from its stored config | Creates new runs |
| `crest_list_calibration_runs` | List calibration runs (paged, status filter) | Read-only |
| `crest_get_calibration_run` | One calibration run's status/detail | Read-only |
| `crest_list_forecast_runs` | List forecast runs (paged, status filter) | Read-only |
| `crest_get_forecast_run` | One forecast run's status/detail | Read-only |
| `crest_list_credit_risk_runs` | List credit-risk runs (paged) | Read-only |
| `crest_get_credit_risk_run` | One credit-risk run (omit id → active run) | Read-only |
| `crest_list_workflows` | List workflows (paged) | Read-only |
| `crest_get_workflow` | One workflow with per-target status (`light` default) | Read-only |
| `crest_get_run_logs` | Cursor-paginated run logs | Read-only |
| `crest_get_workflow_logs` | Unified workflow logs (step/level filters) | Read-only |
| `crest_get_forecast_results` | Paged forecast result rows | Read-only |
| `crest_get_credit_risk_results` | Paged per-client PD/LGD/ECL/stage summary | Read-only |
| `crest_get_credit_risk_client_result` | One client's KMV + ECL year×scenario detail | Read-only |
| `crest_get_calibration_diagnostics` | Slim validation metrics for a run/segment | Read-only |
| `crest_list_datasets` | Uploaded datasets (id/name/kind/status/schema) | Read-only |
| `crest_list_model_configs` | Saved model configurations | Read-only |
| `crest_get_model_registry` | Available algorithms + hyperparameter schemas | Read-only |
| `crest_list_pd_ratings` | Rating→PD curve table | Read-only |
| `crest_resolve_workflow_datasets` | Newest ready dataset per workflow slot | Read-only |
| `crest_get_analysis_meta` | Sectors/companies/metrics for a run's Analysis screens | Read-only |
| `crest_get_analysis_heatmap` | Year×(sector\|client) financial-metric heatmap | Read-only |
| `crest_get_analysis_forecast` | Historical + scenario forecast series | Read-only |

**Not exposed in v1** (transport-bound or out of scope): dataset upload / raw
SQL query / column stats, model-config CRUD, cancel / delete / bulk-delete,
segment recalibrate, set-active, the transitions matrix, and the client list.

## Launch Tools

All launch tools are asynchronous and return the `queued` run dict (with its
immutable `run_id`, `status`, `triggered_by`, and `origin: "auto"`). Redis and a
Celery worker must be running or the run stays `queued`.

### `crest_create_calibration_run`

Input (`CreateCalibrationRun`):

| Field | Type | Notes |
|-------|------|-------|
| `dataset_id` | integer | Calibration dataset (kind `calibration`); see `crest_list_datasets` |
| `model_config_id` | integer | Saved config; see `crest_list_model_configs` |
| `target_col` | string \| null | Target column (defaults from the config) |
| `feature_cols` | string[] | Feature columns (default `[]` → config/auto) |
| `name` | string \| null | Run label |
| `segmentation` | object \| null | Optional per-sector/segment config |

Poll `crest_get_calibration_run`; then read `crest_get_calibration_diagnostics`.

### `crest_create_forecast_run`

Input (`CreateForecastRun`): `calibration_run_id` (string, must be a **success**
run), `dataset_id` (forecast dataset), `segment_key` (string \| null), `name`
(string \| null). Poll `crest_get_forecast_run`; read `crest_get_forecast_results`.

### `crest_create_credit_risk_run`

Input (`CreateCreditRiskRun`):

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `dataset_id` | integer | — | Credit dataset (kind `credit`) |
| `financial_portfolio_dataset_id` | integer \| null | `null` | Sector/subsector/country meta |
| `cal_inputs` | object (slot → forecast run UUID) | `{}` | `total_assets`, `short_term_debts`, `long_term_debts` are **required**; `total_revenue` / `total_cogs` unlock the analysis screens |
| `exposure` | number | `1000000` | EAD |
| `discount_rate` | number | `0.05` | |
| `lifetime_horizon` | integer | `5` | |
| `curve` | string | `moodys` | PD curve |

### `crest_create_workflow`

Input (`CreateWorkflow`): `name`, `targets` (list of `{target_col,
model_config_id?, feature_cols?}`), `model_config_id` (default config),
`feature_cols` (default features), `segmentation`, and `analysis` (`{exposure,
discount_rate, lifetime_horizon, curve}`). Datasets are auto-resolved to the
newest ready upload per kind (preview with `crest_resolve_workflow_datasets`).
Returns the workflow plus its created child runs; stages advance automatically.

Example:

```json
{
  "params": {
    "name": "Q4 pipeline",
    "model_config_id": 1,
    "targets": [{ "target_col": "total_assets" }],
    "analysis": { "exposure": 1000000, "discount_rate": 0.05, "lifetime_horizon": 5, "curve": "moodys" }
  }
}
```

### `crest_rerun_workflow`

Input: `run_id` (string). Relaunches from the stored targets/analysis params
against the current latest datasets, creating **new** runs.

## Monitoring Tools

List tools take `page` (1-based, default 1) and `per_page` (1–100, default 20)
and return the envelope `{ items, total, page, pages }`; calibration/forecast
lists also accept a `status` filter (`queued`/`running`/`success`/`failed`).

| Tool | Input | Output |
|------|-------|--------|
| `crest_get_calibration_run` | `run_id` | Run detail (+ `retraining_segment_count`, `workflow_run_uuid`) |
| `crest_get_forecast_run` | `run_id` | Run detail |
| `crest_get_credit_risk_run` | `run_id?` (omit → active run) | Run detail + result `client_ids` |
| `crest_get_workflow` | `run_id`, `light` (default `true`) | Per-target calibration/forecast status; `light=false` adds full per-run detail |

### `crest_get_run_logs`

Input: `run_type` (`calibration` \| `forecast` \| `credit_risk`), `run_id`,
`after_id` (cursor, optional), `limit` (1–500, default 200). Returns
`{ logs, next_after_id, has_more }`, oldest→newest within the page. Without
`after_id` the most recent `limit` lines are returned (log tail); pass the
returned `next_after_id` back to poll a live run for new lines.

### `crest_get_workflow_logs`

Input: `run_id`, `page` (0-based, default 0), `page_size` (1–200, default 50),
`step` (`Training` \| `Forecast` \| `Credit`, optional), `level` (`info` \|
`warn` \| `error`, optional). Returns `{ rows, total, columns }`.

## Result Tools

Table tools accept the CommonDataTable filter convention as a JSON string, e.g.
`{"sector": {"mode": "in", "value": ["Tech"]}}` or
`{"client_id": {"mode": "contains", "value": "ACME"}}`, plus `page` (0-based),
`page_size` (1–200), `sort_column`, `sort_order`.

| Tool | Input | Output |
|------|-------|--------|
| `crest_get_forecast_results` | `run_id`, page/size/sort/filters | `{ rows, total, columns }` |
| `crest_get_credit_risk_results` | `run_id`, page/size/sort/filters | `{ rows, total }` — per-client `stage`, `pd`, `lgd`, lifetime `ecl`, `scenario`, `year` (baseline, latest meaningful year) |
| `crest_get_credit_risk_client_result` | `run_id`, `client_id` | `{ kmv, ecl }` full year×scenario detail |
| `crest_get_calibration_diagnostics` | `run_id`, `segment_key?` | Validation metrics — **always slim** (the multi-MB `val_obs`/`train_obs` arrays are dropped) |

## Reference Tools

Everything needed to construct a launch payload.

| Tool | Input | Returns |
|------|-------|---------|
| `crest_list_datasets` | `kind?`, `limit` (1–100, default 50) | Datasets, newest first (reference by integer `id`) |
| `crest_list_model_configs` | `limit` (1–100, default 50) | Saved configs with a usage label |
| `crest_get_model_registry` | none | Algorithms with family + hyperparameter schema |
| `crest_list_pd_ratings` | `curve` (default `moodys`) | Rating→PD rows |
| `crest_resolve_workflow_datasets` | none | Newest ready dataset per slot (`calibration`, `forecast`, `credit`, `financial_portfolio`); `null` where none |

## Analysis Tools

These read a credit-risk run's **materialised** level series. If the series is
not computed yet, the tool returns `{ "status": "materializing", ... }` and
dispatches the backfill — retry after a short wait (needs a running worker).

| Tool | Input | Notes |
|------|-------|-------|
| `crest_get_analysis_meta` | `run_id?` (omit → active) | Sectors, companies-by-sector, available metrics, forecast targets — call first |
| `crest_get_analysis_heatmap` | `metric` (`revenue_growth` \| `cogs_margin` \| `leverage`), `run_id?`, `sector?`, `clients?`, `scenario?` | Sector overview, or a client drill-down when `sector` is given |
| `crest_get_analysis_forecast` | `sector`, `run_id?`, `client_id?`, `targets?`, `indexed` (default `false`) | Historical + multi-scenario level series; `indexed` rebases to base year = 100 |

## REST and MCP Parity

REST routes and MCP tools share the same application services
(`project/services/*`) and MSSQL database. A run created by MCP is visible to
REST (and the web app's job history) and vice versa. The launch surface,
run/log/result reads, and the credit-risk analysis reads are all common; the
MCP tools additionally slim/paginate for agent context budgets. See
`.claude/docs/backend.md` for the layering and the reuse rule.

## Validation Commands

From `services/server/`:

```bash
ruff check . --exclude migrations
python -m pytest tests/mcp_server tests/services -q
```

`tests/mcp_server/` covers tool registration + annotations, the
`DomainError → ToolError` mapping, launch tools (Celery mocked), read-tool
pagination/log cursoring, and a non-main-thread app-context guard.
`tests/services/` exercises the shared services that the tools call (they double
as the MCP contract).

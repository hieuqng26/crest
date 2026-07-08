// Shared CommonDataTable column defs for forecast / credit-risk analysis
// results, used by both JobDetail.vue (standalone runs) and
// WorkflowDetail.vue (runs launched as part of a workflow).
// Numeric columns are right-aligned tabular mono per design.md — magnitudes
// must be scannable down a column. Widths are raw px (never rem).
export const forecastResultColumns = [
  { field: 'date', header: 'Date', width: '128px', mono: true },
  { field: 'predicted', header: 'Predicted', width: '128px', align: 'right', mono: true, formatter: (v) => (v != null ? v.toFixed(4) : '—') }
]

export const analysisResultColumns = [
  { field: 'client_id', header: 'Client ID', width: '128px', mono: true },
  { field: 'sector', header: 'Sector', width: '128px' },
  { field: 'segment_key', header: 'Segment', width: '156px' },
  { field: 'scenario', header: 'Scenario', width: '128px' },
  { field: 'year', header: 'Year', width: '88px', align: 'right', mono: true },
  { field: 'stage', header: 'Stage', width: '96px' },
  { field: 'pd', header: 'PD', width: '100px', align: 'right', mono: true, formatter: (v) => (v != null ? (v * 100).toFixed(3) + '%' : '—') },
  { field: 'lgd', header: 'LGD', width: '100px', align: 'right', mono: true, formatter: (v) => (v != null ? (v * 100).toFixed(1) + '%' : '—') },
  { field: 'ecl', header: 'ECL', width: '128px', align: 'right', mono: true, formatter: (v) => (v != null ? v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—') }
]

// Unified workflow log table (Overview tab). Step/Target/Sector/Segment/Level are
// categorical → CommonDataTable turns them into dropdown filters via fetchDistinct;
// Time isn't filterable and Message is covered by the toolbar's global search.
export const workflowLogColumns = [
  { field: 'step', header: 'Step', width: '7rem' },
  { field: 'target', header: 'Target', width: '9rem', mono: true },
  { field: 'sector', header: 'Sector', width: '9rem' },
  { field: 'segment', header: 'Segment', width: '9rem', mono: true },
  { field: 't', header: 'Time', width: '6rem', mono: true, sortable: false, filterable: false },
  { field: 'level', header: 'Level', width: '6rem' },
  { field: 'message', header: 'Message', width: '30rem', sortable: false, filterable: false }
]

// Forecast/backtest result schemas vary by dataset (sector/subsector/country/
// segment_key are present only when the calibration was segmented on that
// dimension), so the workflow's Forecast and Diagnosis & Backtesting tabs
// build their CommonDataTable columns from the backend's actual `columns`
// list instead of a fixed schema — that's also what makes per-column
// sector/segment filtering "just work" via CommonDataTable's own filters.
const NUMERIC_FIELDS = new Set(['actual', 'predicted', 'residual'])

export function columnsFromNames(names) {
  return names.map((f) => {
    if (f === 'correct') return { field: f, header: 'CORRECT', width: '100px', align: 'center', formatter: (v) => (v ? '✓' : '✗') }
    if (NUMERIC_FIELDS.has(f)) {
      return { field: f, header: f.toUpperCase(), width: '128px', align: 'right', mono: true, formatter: (v) => (v != null ? Number(v).toFixed(4) : '—') }
    }
    return { field: f, header: f.replace(/_/g, ' ').toUpperCase() }
  })
}

// One-off pageSize:1 fetch purely to read the backend's `columns` list before
// mounting CommonDataTable (which needs its `columns` prop synchronously).
export async function probeColumns(fetchPage) {
  try {
    const { data } = await fetchPage({ page: 0, pageSize: 1 })
    return columnsFromNames(data.columns ?? [])
  } catch {
    return []
  }
}

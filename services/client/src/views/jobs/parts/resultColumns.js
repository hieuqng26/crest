// Shared CommonDataTable column defs for forecast / credit-risk analysis
// results, used by both JobDetail.vue (standalone runs) and
// WorkflowDetail.vue (runs launched as part of a workflow).
export const forecastResultColumns = [
  { field: 'date', header: 'Date', width: '9rem' },
  { field: 'predicted', header: 'Predicted', width: '9rem', formatter: (v) => (v != null ? v.toFixed(4) : '—') }
]

export const analysisResultColumns = [
  { field: 'client_id', header: 'Client ID', width: '9rem' },
  { field: 'sector', header: 'Sector', width: '9rem' },
  { field: 'segment_key', header: 'Segment', width: '11rem' },
  { field: 'scenario', header: 'Scenario', width: '9rem' },
  { field: 'year', header: 'Year', width: '6rem' },
  { field: 'stage', header: 'Stage', width: '5rem' },
  { field: 'pd', header: 'PD', width: '7rem', formatter: (v) => (v != null ? (v * 100).toFixed(3) + '%' : '—') },
  { field: 'lgd', header: 'LGD', width: '7rem', formatter: (v) => (v != null ? (v * 100).toFixed(1) + '%' : '—') },
  { field: 'ecl', header: 'ECL', width: '9rem', formatter: (v) => (v != null ? v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—') }
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
    if (f === 'correct') return { field: f, header: 'CORRECT', width: '7rem', formatter: (v) => (v ? '✓' : '✗') }
    if (NUMERIC_FIELDS.has(f)) {
      return { field: f, header: f.toUpperCase(), width: '9rem', formatter: (v) => (v != null ? Number(v).toFixed(4) : '—') }
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

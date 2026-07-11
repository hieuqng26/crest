// Shared chart theming — every chart reads the CSS design tokens at call time
// (not module load) so it tracks the active theme. See design.md: series
// colors come from --chart-1…8, never hardcoded hex.

export function cssVar(name, fallback = '') {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

/** Ordered series palette (--chart-1…8). Slot 1 is the darkened chart yellow. */
export function chartPalette() {
  return [1, 2, 3, 4, 5, 6, 7, 8].map((i) => cssVar(`--chart-${i}`))
}

/** Colors for scenarios NOT covered by scenarioStyle() (slots 4+). */
export function fallbackSeriesColors() {
  return chartPalette().slice(3)
}

/**
 * Fixed scenario → Plotly line style for Baseline / Adverse / Severely Adverse.
 * The single source of truth so every chart in the app draws the scenarios
 * identically. All three are solid; colors come from the `--scenario-*` tokens.
 * Unknown scenario names cycle through `fallbackSeriesColors()` via `fallbackIndex`.
 */
export function scenarioStyle(name, fallbackIndex = 0) {
  const known = {
    Baseline: { color: cssVar('--scenario-baseline'), width: 2.6, dash: 'solid' },
    Adverse: { color: cssVar('--scenario-adverse'), width: 1.8, dash: 'solid' },
    'Severely Adverse': { color: cssVar('--scenario-severe'), width: 1.8, dash: 'solid' },
  }
  if (known[name]) return known[name]
  const fb = fallbackSeriesColors()
  return { color: fb[fallbackIndex % fb.length], width: 1.8, dash: 'solid' }
}

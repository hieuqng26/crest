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

/**
 * Fixed scenario → line style mapping for the Baseline / Adverse / Severely
 * Adverse forecast scenarios. Unknown scenario names should fall back to
 * `chartPalette()` slots 4+ (the first three are reserved here).
 */
export function scenarioLineStyles() {
  return {
    Baseline: { color: cssVar('--chart-1'), width: 2.6, dash: [] },
    Adverse: { color: cssVar('--chart-2'), width: 1.6, dash: [] },
    'Severely Adverse': { color: cssVar('--chart-3'), width: 1.6, dash: [5, 4] },
  }
}

/** Colors for the scenarios NOT covered by scenarioLineStyles(). */
export function fallbackSeriesColors() {
  return chartPalette().slice(3)
}

/** chart.js scale defaults: muted ticks, hairline y-grid, no x-grid. */
export function axisDefaults() {
  const tick = cssVar('--text-color-muted-2')
  return {
    x: { ticks: { color: tick, font: { size: 10 } }, grid: { display: false } },
    y: {
      ticks: { color: tick, font: { size: 10 } },
      grid: { color: 'rgba(155, 155, 166, 0.15)' },
      border: { display: false },
    },
  }
}

<script setup>
// Shared Plotly distribution plot (histogram + Gaussian KDE overlay) — the
// residual-distribution equivalent of LinePlot.vue. Plotly.js has no built-in
// "distplot" (that's a Python-only plotly.figure_factory helper), so this
// reproduces its look: a density-normalised histogram plus a smoothed density
// curve, both computed from the same raw values already loaded client-side.
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { cssVar } from '@/utils/chartTheme'

const props = defineProps({
  values: { type: Array, default: () => [] }, // raw numeric observations
  name: { type: String, default: 'Distribution' },
  color: { type: String, default: '' },        // histogram bar color
  kdeColor: { type: String, default: '' },      // density curve color
  height: { type: Number, default: 280 },
  bins: { type: Number, default: null },        // initial bin count; null = auto (Sturges' rule)
  showKde: { type: Boolean, default: true },
  xTickFormat: { type: String, default: '' },
  pngFilename: { type: String, default: 'distribution' },
})

const el = ref(null)
const menu = ref(null)
const menuOpen = ref(false)
let Plotly = null
let ro = null

// ── bin-count slider ──────────────────────────────────────────────────────────
// Purely client-side: the full values array is already in memory, so dragging
// this only re-bins the histogram and re-renders — no server round trip.
// The max scales with the sample size (more than ~1 bin/point is meaningless
// noise), capped at a hard ceiling so the slider stays usable for large n.
const BIN_MIN = 5
const BIN_MAX_CEILING = 100
const binMax = computed(() => Math.max(BIN_MIN + 1, Math.min(BIN_MAX_CEILING, props.values.length)))
function sturgesDefault(n) {
  if (n < 2) return BIN_MIN
  return Math.min(binMax.value, Math.max(BIN_MIN, Math.ceil(Math.log2(n) + 1)))
}
const binCount = ref(props.bins ?? sturgesDefault(props.values.length))

const menuItems = computed(() => [
  { separator: true },
  { label: 'Download PNG', icon: 'pi pi-download', command: downloadPng },
])

function toggleMenu(e) { menu.value.toggle(e) }

// ── Gaussian KDE ──────────────────────────────────────────────────────────────
// Silverman's rule of thumb for bandwidth; evaluated on a 128-point grid
// spanning the data range plus 10% padding. Pure client-side math — no
// server round trip, so it stays cheap even if a bin-count slider is added
// later (it only needs to re-run this + the histogram binning locally).
function stdev(xs) {
  const n = xs.length
  const mean = xs.reduce((s, v) => s + v, 0) / n
  const variance = xs.reduce((s, v) => s + (v - mean) ** 2, 0) / (n - 1 || 1)
  return Math.sqrt(variance)
}
function gaussianKernel(u) { return Math.exp(-0.5 * u * u) / Math.sqrt(2 * Math.PI) }
function kde(values, gridPoints = 128) {
  const n = values.length
  if (n < 2) return { x: [], y: [] }
  const sd = stdev(values) || 1
  const bandwidth = 1.06 * sd * Math.pow(n, -1 / 5) || 1
  const min = Math.min(...values), max = Math.max(...values)
  const pad = (max - min) * 0.1 || 1
  const x0 = min - pad, x1 = max + pad
  const step = (x1 - x0) / (gridPoints - 1)
  const x = Array.from({ length: gridPoints }, (_, i) => x0 + i * step)
  const y = x.map((xi) => values.reduce((s, v) => s + gaussianKernel((xi - v) / bandwidth), 0) / (n * bandwidth))
  return { x, y }
}

// ── Plotly figure ─────────────────────────────────────────────────────────────
function buildTraces() {
  const barColor = props.color || cssVar('--ink-2')
  const lineColor = props.kdeColor || cssVar('--yellow-chart')
  const traces = [{
    type: 'histogram',
    name: props.name,
    x: props.values,
    histnorm: 'probability density',
    nbinsx: binCount.value,
    marker: { color: barColor, opacity: 0.85 },
    hovertemplate: 'x: %{x}<br>density: %{y:.4f}<extra>' + props.name + '</extra>',
  }]
  if (props.showKde) {
    const { x, y } = kde(props.values)
    if (x.length) {
      traces.push({
        type: 'scatter',
        mode: 'lines',
        name: 'Density',
        x, y,
        line: { color: lineColor, width: 2.2, shape: 'spline' },
        hovertemplate: 'density: %{y:.4f}<extra>Density</extra>',
      })
    }
  }
  return traces
}

function buildLayout() {
  const muted = cssVar('--text-color-muted-2') || cssVar('--text-color-muted')
  const monoFont = { family: 'IBM Plex Mono, ui-monospace, monospace', size: 10, color: muted }
  const traces = buildTraces()
  return {
    margin: { l: 44, r: 16, t: 10, b: 34 },
    dragmode: 'zoom',
    bargap: 0.04,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    hovermode: 'closest',
    showlegend: traces.length > 1,
    legend: {
      orientation: 'h', y: 1.15, x: 0.5, xanchor: 'center',
      font: { family: 'IBM Plex Mono, monospace', size: 11, color: cssVar('--text-color-secondary') },
    },
    xaxis: {
      tickfont: monoFont,
      showgrid: false,
      zeroline: false,
      ...(props.xTickFormat ? { tickformat: props.xTickFormat } : {}),
    },
    yaxis: {
      tickfont: monoFont,
      gridcolor: cssVar('--surface-border-row'),
      zeroline: false,
    },
  }
}

const config = {
  displaylogo: false,
  displayModeBar: false, // hidden — the top-right button is the only chrome
  responsive: true,
  scrollZoom: false,
  doubleClick: 'reset',
}

async function render() {
  if (!Plotly || !el.value) return
  await Plotly.react(el.value, buildTraces(), buildLayout(), config)
}

function downloadPng() {
  if (!Plotly || !el.value) return
  Plotly.downloadImage(el.value, {
    format: 'png',
    width: el.value.clientWidth || 900,
    height: props.height,
    scale: 3, // hi-res
    filename: props.pngFilename,
  })
}

onMounted(async () => {
  const mod = await import('plotly.js-dist')
  Plotly = mod.default || mod
  await render()
  ro = new ResizeObserver(() => { if (Plotly && el.value) Plotly.Plots.resize(el.value) })
  ro.observe(el.value)
})

onBeforeUnmount(() => {
  if (ro) { ro.disconnect(); ro = null }
  if (Plotly && el.value) Plotly.purge(el.value)
})

// Re-clamp if a data change (e.g. switching target/segment) shrinks binMax
// below the current slider position.
watch(binMax, (max) => { if (binCount.value > max) binCount.value = max })

watch(() => [props.values, binCount.value, props.showKde, props.xTickFormat], render, { deep: true })
</script>

<template>
  <div class="distplot" :style="{ height: height + 'px' }">
    <Button
      class="distplot__menu-btn"
      :class="{ 'is-open': menuOpen }"
      icon="pi pi-ellipsis-v"
      text
      rounded
      size="small"
      aria-label="Chart options"
      @click="toggleMenu"
    />
    <Menu ref="menu" :model="menuItems" :popup="true" @show="menuOpen = true" @hide="menuOpen = false">
      <template #start>
        <div class="distplot__bins" @click.stop>
          <span class="distplot__bins-label">Bins</span>
          <Slider v-model="binCount" :min="BIN_MIN" :max="binMax" :step="1" class="distplot__bins-slider" />
          <span class="distplot__bins-value">{{ binCount }}</span>
        </div>
      </template>
    </Menu>
    <div ref="el" class="distplot__canvas" />
  </div>
</template>

<style scoped>
.distplot { position: relative; width: 100%; }
.distplot__canvas { width: 100%; height: 100%; }

.distplot__menu-btn {
  position: absolute;
  top: 2px;
  right: 2px;
  z-index: 2;
  width: 1.75rem;
  height: 1.75rem;
  opacity: 0;
  transition: opacity 0.15s ease;
  color: var(--text-color-secondary);
}
.distplot:hover .distplot__menu-btn,
.distplot__menu-btn.is-open,
.distplot__menu-btn:focus-visible { opacity: 1; }
</style>

<style>
/* Not scoped: the #start slot renders inside PrimeVue's teleported popup,
 * outside this component's DOM subtree — scoped selectors can't reach it. */
.distplot__bins {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
}
.distplot__bins-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-color-muted);
}
.distplot__bins-slider { width: 90px; }
.distplot__bins-value {
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: 11px;
  color: var(--text-color-secondary);
  min-width: 1.4em;
  text-align: right;
}
</style>

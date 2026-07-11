<script setup>
// Shared Plotly line plot. Every line chart in the app (PD/LGD, ECL, Financial
// Forecast, Backtesting) renders through this so interactions and styling stay
// identical. Plotly is code-split (dynamic import) — it only downloads on pages
// that actually mount a chart.
//
// Features:
//  • clickable native legend (click a series to hide its line)
//  • drag-to-zoom + double-click reset — disabled while the range slider is on
//  • hover-only kebab menu (top-left): toggle range slider, download hi-res PNG
// The Plotly modebar itself is hidden; the kebab is the only chrome.
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { cssVar } from '@/utils/chartTheme'

const props = defineProps({
  // [{ name, x:[], y:[], color?, width?, dash?, mode? }]
  series: { type: Array, default: () => [] },
  height: { type: Number, default: 300 },
  yTickFormat: { type: String, default: '' },   // d3 format, e.g. '.1%' or '.2s'
  yHoverFormat: { type: String, default: '' },  // defaults to yTickFormat
  xTickFormat: { type: String, default: '' },
  xDtick: { type: [Number, String], default: undefined },
  curve: { type: String, default: 'spline' },   // 'spline' | 'linear'
  markers: { type: Boolean, default: false },
  legend: { type: Boolean, default: true },
  rangeslider: { type: Boolean, default: false }, // initial state (toggled via menu)
  pngFilename: { type: String, default: 'chart' },
  // Extra PrimeVue MenuItem[] prepended to the kebab menu (page-specific actions).
  extraMenuItems: { type: Array, default: () => [] },
})

const el = ref(null)
const menu = ref(null)
const menuOpen = ref(false)
const rsOn = ref(props.rangeslider)
let Plotly = null
let ro = null

const menuItems = computed(() => [
  ...props.extraMenuItems,
  {
    label: rsOn.value ? 'Hide range slider' : 'Show range slider',
    icon: rsOn.value ? 'pi pi-arrows-h' : 'pi pi-sliders-h',
    command: () => { rsOn.value = !rsOn.value },
  },
  {
    label: 'Download PNG',
    icon: 'pi pi-download',
    command: downloadPng,
  },
])

function toggleMenu(e) { menu.value.toggle(e) }

// ── Plotly figure ─────────────────────────────────────────────────────────────
function buildTraces() {
  const mode = props.markers ? 'lines+markers' : 'lines'
  const shape = props.curve === 'linear' ? 'linear' : 'spline'
  const hoverFmt = props.yHoverFormat || props.yTickFormat
  const yTok = hoverFmt ? `%{y:${hoverFmt}}` : '%{y}'
  return props.series.map((s) => ({
    type: 'scatter',
    mode: s.mode || mode,
    name: s.name,
    x: s.x,
    y: s.y,
    line: { color: s.color, width: s.width ?? 1.8, dash: s.dash || 'solid', shape },
    marker: { size: 5, color: s.color },
    hovertemplate: `${yTok}<extra>${s.name}</extra>`,
  }))
}

function buildLayout() {
  const muted = cssVar('--text-color-muted-2') || cssVar('--text-color-muted')
  const monoFont = { family: 'IBM Plex Mono, ui-monospace, monospace', size: 10, color: muted }
  // Integer x axes (years, observation indexes) must not auto-tick to fractions
  // like "2025.5" — force an integer step capped at ~8 ticks and integer labels.
  const xs = props.series.flatMap((s) => s.x || []).filter((v) => v != null)
  const allInt = xs.length > 0 && xs.every((v) => Number.isInteger(v))
  const xAxisTicks = {}
  if (props.xDtick != null) xAxisTicks.dtick = props.xDtick
  else if (allInt) xAxisTicks.dtick = Math.max(1, Math.ceil((Math.max(...xs) - Math.min(...xs)) / 8))
  const xFmt = props.xTickFormat || (allInt ? 'd' : '')
  return {
    margin: { l: 56, r: 16, t: 10, b: rsOn.value ? 12 : 34 },
    dragmode: rsOn.value ? false : 'zoom',
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    hovermode: 'x unified',
    showlegend: props.legend,
    legend: {
      orientation: 'h', y: 1.15, x: 0.5, xanchor: 'center',
      font: { family: 'IBM Plex Mono, monospace', size: 11, color: cssVar('--text-color-secondary') },
    },
    xaxis: {
      tickfont: monoFont,
      showgrid: false,
      zeroline: false,
      ...xAxisTicks,
      ...(xFmt ? { tickformat: xFmt } : {}),
      rangeslider: { visible: rsOn.value, thickness: 0.12 },
    },
    yaxis: {
      tickfont: monoFont,
      ...(props.yTickFormat ? { tickformat: props.yTickFormat } : {}),
      gridcolor: cssVar('--surface-border-row'),
      zeroline: false,
    },
  }
}

const config = {
  displaylogo: false,
  displayModeBar: false, // hidden — the kebab menu is the only chrome
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

// Re-render on data / format / range-slider changes.
watch(
  () => [props.series, rsOn.value, props.yTickFormat, props.xTickFormat, props.curve, props.markers],
  render,
  { deep: true },
)
</script>

<template>
  <div class="lineplot" :style="{ height: height + 'px' }">
    <Button
      class="lineplot__menu-btn"
      :class="{ 'is-open': menuOpen }"
      icon="pi pi-ellipsis-v"
      text
      rounded
      size="small"
      aria-label="Chart options"
      @click="toggleMenu"
    />
    <Menu ref="menu" :model="menuItems" :popup="true" @show="menuOpen = true" @hide="menuOpen = false" />
    <div ref="el" class="lineplot__canvas" />
  </div>
</template>

<style scoped>
.lineplot { position: relative; width: 100%; }
.lineplot__canvas { width: 100%; height: 100%; }

.lineplot__menu-btn {
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
.lineplot:hover .lineplot__menu-btn,
.lineplot__menu-btn.is-open,
.lineplot__menu-btn:focus-visible { opacity: 1; }
</style>

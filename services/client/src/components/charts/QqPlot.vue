<script setup>
// Shared Plotly normal Q–Q plot for residual normality. Given raw residuals it
// plots each ordered residual against its theoretical standard-normal quantile
// (rankit plotting position), plus the reference line whose slope/intercept are
// the residual sd/mean — points hugging the line ⇒ approximately normal. All
// math is client-side (the residuals array is already loaded), matching the
// DistPlot pattern so interactions and styling stay identical.
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { cssVar } from '@/utils/chartTheme'

const props = defineProps({
  values: { type: Array, default: () => [] }, // raw residuals
  height: { type: Number, default: 280 },
  pngFilename: { type: String, default: 'qq-plot' },
})

const el = ref(null)
const menu = ref(null)
const menuOpen = ref(false)
let Plotly = null
let ro = null

const menuItems = computed(() => [
  { label: 'Download PNG', icon: 'pi pi-download', command: downloadPng },
])
function toggleMenu(e) { menu.value.toggle(e) }

// Inverse standard-normal CDF (Acklam's rational approximation, |err| < 1.15e-9).
function normInv(p) {
  if (p <= 0) return -Infinity
  if (p >= 1) return Infinity
  const a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.38357751867269e2, -3.066479806614716e1, 2.506628277459239]
  const b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1]
  const c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783]
  const d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416]
  const plow = 0.02425, phigh = 1 - plow
  let q, r
  if (p < plow) {
    q = Math.sqrt(-2 * Math.log(p))
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
  }
  if (p <= phigh) {
    q = p - 0.5; r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
  }
  q = Math.sqrt(-2 * Math.log(1 - p))
  return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
}

const qq = computed(() => {
  const vals = props.values.filter((v) => v != null && Number.isFinite(v))
  const n = vals.length
  if (n < 2) return null
  const sorted = [...vals].sort((a, b) => a - b)
  const mean = sorted.reduce((s, v) => s + v, 0) / n
  const sd = Math.sqrt(sorted.reduce((s, v) => s + (v - mean) ** 2, 0) / (n - 1)) || 1
  // Blom plotting position (i − 3/8)/(n + 1/4) — the rankit convention.
  const theo = sorted.map((_, i) => normInv((i + 1 - 0.375) / (n + 0.25)))
  const xMin = theo[0], xMax = theo[n - 1]
  return {
    theo,
    sample: sorted,
    line: { x: [xMin, xMax], y: [mean + sd * xMin, mean + sd * xMax] },
  }
})

function buildTraces() {
  const q = qq.value
  if (!q) return []
  return [
    {
      type: 'scatter', mode: 'markers', name: 'Residuals',
      x: q.theo, y: q.sample,
      marker: { size: 5, color: cssVar('--ink-2'), opacity: 0.75 },
      hovertemplate: 'theoretical: %{x:.3f}<br>sample: %{y:.4f}<extra></extra>',
    },
    {
      type: 'scatter', mode: 'lines', name: 'Reference',
      x: q.line.x, y: q.line.y,
      line: { color: cssVar('--yellow-chart'), width: 2, dash: 'dash' },
      hoverinfo: 'skip',
    },
  ]
}

function buildLayout() {
  const muted = cssVar('--text-color-muted-2') || cssVar('--text-color-muted')
  const monoFont = { family: 'IBM Plex Mono, ui-monospace, monospace', size: 10, color: muted }
  const titleFont = { family: 'IBM Plex Mono, monospace', size: 10.5, color: muted }
  return {
    margin: { l: 52, r: 16, t: 10, b: 40 },
    dragmode: 'zoom',
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    hovermode: 'closest',
    showlegend: false,
    xaxis: {
      title: { text: 'Theoretical quantiles', font: titleFont, standoff: 8 },
      tickfont: monoFont, showgrid: false, zeroline: false,
    },
    yaxis: {
      title: { text: 'Sample quantiles', font: titleFont, standoff: 6 },
      tickfont: monoFont, gridcolor: cssVar('--surface-border-row'), zeroline: false,
    },
  }
}

const config = { displaylogo: false, displayModeBar: false, responsive: true, scrollZoom: false, doubleClick: 'reset' }

async function render() {
  if (!Plotly || !el.value) return
  await Plotly.react(el.value, buildTraces(), buildLayout(), config)
}

function downloadPng() {
  if (!Plotly || !el.value) return
  Plotly.downloadImage(el.value, {
    format: 'png', width: el.value.clientWidth || 900, height: props.height, scale: 3, filename: props.pngFilename,
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

watch(() => props.values, render, { deep: true })
</script>

<template>
  <div class="qqplot" :style="{ height: height + 'px' }">
    <Button
      class="qqplot__menu-btn"
      :class="{ 'is-open': menuOpen }"
      icon="pi pi-ellipsis-v"
      text
      rounded
      size="small"
      aria-label="Chart options"
      @click="toggleMenu"
    />
    <Menu ref="menu" :model="menuItems" :popup="true" @show="menuOpen = true" @hide="menuOpen = false" />
    <div ref="el" class="qqplot__canvas" />
  </div>
</template>

<style scoped>
.qqplot { position: relative; width: 100%; }
.qqplot__canvas { width: 100%; height: 100%; }

.qqplot__menu-btn {
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
.qqplot:hover .qqplot__menu-btn,
.qqplot__menu-btn.is-open,
.qqplot__menu-btn:focus-visible { opacity: 1; }
</style>

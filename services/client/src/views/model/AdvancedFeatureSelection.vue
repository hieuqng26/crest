<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import datasetsAPI from '@/api/datasetsAPI'
import { calibrationDataset, targetCols, featureCols, featureOptions } from './newModelStore'

const router = useRouter()
const toast = useToast()

const loading = ref(true)
const columns = ref([]) // [{name, type, missing_pct, distinct, mean, std}]
const checked = ref({}) // { [name]: bool }
const search = ref('')

onMounted(async () => {
  if (!calibrationDataset.value || !targetCols.value.length) {
    router.replace({ name: 'model_new' })
    return
  }
  loading.value = true
  try {
    // target arg is only used server-side for the (now-removed) single-corr
    // column; pass the first target for backwards-compatible stats.
    const { data } = await datasetsAPI.columnStats(calibrationDataset.value.id, targetCols.value[0] ?? null)
    const allowed = new Set(featureOptions.value)
    columns.value = (data.columns ?? []).filter((c) => allowed.has(c.name))
    const preselected = new Set(featureCols.value.length ? featureCols.value : columns.value.map((c) => c.name))
    checked.value = Object.fromEntries(columns.value.map((c) => [c.name, preselected.has(c.name)]))
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load column statistics', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    loading.value = false
  }
})

const filteredColumns = computed(() => {
  const q = search.value.trim().toLowerCase()
  return columns.value.filter((c) => !q || c.name.toLowerCase().includes(q))
})

const featCount = computed(() => Object.values(checked.value).filter(Boolean).length)
const allChecked = computed(() => columns.value.length > 0 && featCount.value === columns.value.length)

const toggleAll = () => {
  const next = !allChecked.value
  checked.value = Object.fromEntries(columns.value.map((c) => [c.name, next]))
}
const toggleOne = (name) => { checked.value[name] = !checked.value[name] }

const fmtNum = (v) => (v == null ? '—' : Number(v).toFixed(4))

// ── Selected sets ─────────────────────────────────────────────────────────────
const selectedFeatures = computed(() =>
  columns.value.filter((c) => checked.value[c.name]).map((c) => c.name)
)
// Targets are numeric calibration columns; they aren't in `columns` (which is
// features only), so take them straight from the wizard selection.
const selectedTargets = computed(() => [...targetCols.value])

// ── Correlation matrix (feature↔feature and feature↔target are sub-blocks) ─────
const corrLoading = ref(false)
const corrColumns = ref([])         // names, in matrix order
const corrMatrix = ref([])          // number|null[][]
const corrIndex = computed(() => {
  const m = {}
  corrColumns.value.forEach((name, i) => { m[name] = i })
  return m
})

const corrCell = (rowName, colName) => {
  // Look up by name so slicing is robust to matrix ordering.
  const ri = corrIndex.value[rowName]
  const ci = corrIndex.value[colName]
  if (ri == null || ci == null) return null
  return corrMatrix.value[ri]?.[ci] ?? null
}

// Diverging scale: positive → yellow ramp, negative → ink ramp (same language
// as the Sector Heatmap). |v| drives opacity so strong (±) correlations pop.
const cellStyle = (v) => {
  if (v == null) return { background: 'var(--surface-ground)', color: 'var(--text-color-muted)' }
  const a = Math.min(0.1 + Math.abs(v) * 0.85, 0.95)
  if (v >= 0) return { background: `rgba(255,214,0,${a.toFixed(2)})`, color: '#1A1A24' }
  return { background: `rgba(46,46,56,${a.toFixed(2)})`, color: a > 0.45 ? '#FFFFFF' : '#1A1A24' }
}
const cellText = (v) => (v == null ? '—' : (v >= 0 ? v.toFixed(2) : '−' + Math.abs(v).toFixed(2)))

const canFeatureMatrix = computed(() => selectedFeatures.value.length >= 2)
const canTargetMatrix = computed(() => selectedFeatures.value.length >= 1 && selectedTargets.value.length >= 1)

// Re-fetch only when the *set* of columns changes, debounced so rapid checkbox
// toggles don't spam the API.
const corrKey = computed(() => {
  const feats = [...selectedFeatures.value].sort()
  const targs = [...selectedTargets.value].sort()
  return JSON.stringify([feats, targs])
})

let debounceTimer = null
async function fetchCorrelations() {
  const feats = selectedFeatures.value
  const targs = selectedTargets.value
  const union = [...new Set([...feats, ...targs])]
  if (union.length < 2 || (!canFeatureMatrix.value && !canTargetMatrix.value)) {
    corrColumns.value = []
    corrMatrix.value = []
    return
  }
  corrLoading.value = true
  try {
    const { data } = await datasetsAPI.correlations(calibrationDataset.value.id, union)
    corrColumns.value = data.columns ?? []
    corrMatrix.value = data.matrix ?? []
  } catch (e) {
    corrColumns.value = []
    corrMatrix.value = []
    toast.add({ severity: 'error', summary: 'Failed to load correlations', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    corrLoading.value = false
  }
}

watch(corrKey, () => {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(fetchCorrelations, 300)
})

const apply = () => {
  featureCols.value = columns.value.filter((c) => checked.value[c.name]).map((c) => c.name)
  router.push({ name: 'model_new' })
}
const cancel = () => router.push({ name: 'model_new' })
</script>

<template>
  <div class="feature-sel">
    <button class="back-link" @click="cancel">&larr; New Model</button>

    <div class="header-row">
      <div class="header-text">
        <div class="eyebrow">MODEL</div>
        <h1>Advanced Feature Selection</h1>
        <div class="subtitle">
          Column statistics for <span class="font-mono">{{ calibrationDataset?.name }}</span>
          · <span class="font-mono">{{ featCount }}</span> features × <span class="font-mono">{{ selectedTargets.length }}</span> targets selected
        </div>
      </div>
      <div class="method-col">
        <label class="field-label">Selection method</label>
        <div class="method-select">Manual<i class="pi pi-chevron-down" /></div>
      </div>
    </div>

    <div class="info-panel">
      <span class="info-bar" />
      <div class="info-text">Select features manually using the column statistics below. The heatmaps update live as you toggle features — use them to drop redundant (highly inter-correlated) features and keep those that correlate with your targets.</div>
    </div>

    <!-- ── Correlation heatmaps ─────────────────────────────────────────────── -->
    <div class="heatmaps">
      <!-- Feature ↔ Feature -->
      <div class="panel heatmap-panel">
        <div class="heatmap-head">
          <div>
            <div class="table-title">Feature ↔ Feature correlation</div>
            <div class="heatmap-sub">Pearson r among selected features — spot redundant, collinear pairs</div>
          </div>
          <div class="legend-row">
            <span class="legend-item"><span class="legend-swatch" style="background: rgba(46,46,56,0.75)" />Negative</span>
            <span class="legend-item"><span class="legend-swatch" style="background: rgba(255,214,0,0.85)" />Positive</span>
          </div>
        </div>

        <div v-if="corrLoading" class="loading-line"><i class="pi pi-spin pi-spinner" /> Computing…</div>
        <div v-else-if="!canFeatureMatrix" class="hm-empty">Select at least two features to compare.</div>
        <div v-else class="hm-scroll">
          <div class="hm-grid" :style="{ gridTemplateColumns: `var(--hm-label) repeat(${selectedFeatures.length}, minmax(48px, 1fr))` }">
            <!-- header row -->
            <div class="hm-corner" />
            <div v-for="f in selectedFeatures" :key="`fh-${f}`" class="hm-colhead font-mono" :title="f">{{ f }}</div>
            <!-- body rows -->
            <template v-for="rf in selectedFeatures" :key="`fr-${rf}`">
              <div class="hm-rowhead font-mono" :title="rf">{{ rf }}</div>
              <div
                v-for="cf in selectedFeatures" :key="`fc-${rf}-${cf}`"
                class="hm-cell font-mono"
                :style="cellStyle(corrCell(rf, cf))"
              >{{ cellText(corrCell(rf, cf)) }}</div>
            </template>
          </div>
        </div>
      </div>

      <!-- Feature ↔ Target -->
      <div class="panel heatmap-panel">
        <div class="heatmap-head">
          <div>
            <div class="table-title">Feature ↔ Target correlation</div>
            <div class="heatmap-sub">Pearson r of each feature against each selected target</div>
          </div>
        </div>

        <div v-if="corrLoading" class="loading-line"><i class="pi pi-spin pi-spinner" /> Computing…</div>
        <div v-else-if="!canTargetMatrix" class="hm-empty">Select at least one feature and one target.</div>
        <div v-else class="hm-scroll">
          <div class="hm-grid" :style="{ gridTemplateColumns: `var(--hm-label) repeat(${selectedTargets.length}, minmax(70px, 1fr))` }">
            <div class="hm-corner" />
            <div v-for="t in selectedTargets" :key="`th-${t}`" class="hm-colhead font-mono" :title="t">{{ t }}</div>
            <template v-for="rf in selectedFeatures" :key="`tr-${rf}`">
              <div class="hm-rowhead font-mono" :title="rf">{{ rf }}</div>
              <div
                v-for="t in selectedTargets" :key="`tc-${rf}-${t}`"
                class="hm-cell font-mono"
                :style="cellStyle(corrCell(rf, t))"
              >{{ cellText(corrCell(rf, t)) }}</div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <div class="panel">
      <div class="table-header">
        <div class="table-title">Columns</div>
        <div class="table-count"><span class="font-mono">{{ featCount }} of {{ columns.length }}</span> selected</div>
        <div class="spacer" />
        <InputText v-model="search" placeholder="Search columns…" class="search-input" />
      </div>

      <div class="fs-grid fs-grid--head">
        <div class="checkbox-cell" @click="toggleAll">
          <span class="checkbox" :class="{ 'is-checked': allChecked }"><i v-if="allChecked" class="pi pi-check" /></span>
        </div>
        <div>FEATURE</div><div>TYPE</div><div class="ta-right">MISSING</div><div class="ta-right">DISTINCT</div>
        <div class="ta-right">MEAN</div><div class="ta-right">STD</div>
      </div>

      <div v-if="loading" class="loading-line"><i class="pi pi-spin pi-spinner" /> Loading column statistics…</div>

      <div v-for="c in filteredColumns" :key="c.name" class="fs-grid fs-grid--row" :style="{ opacity: checked[c.name] ? 1 : 0.6 }">
        <div class="checkbox-cell" @click="toggleOne(c.name)">
          <span class="checkbox" :class="{ 'is-checked': checked[c.name] }"><i v-if="checked[c.name]" class="pi pi-check" /></span>
        </div>
        <div class="font-mono fs-name" :class="{ 'is-unchecked': !checked[c.name] }">{{ c.name }}</div>
        <div><span class="type-tag">{{ c.type.toUpperCase() }}</span></div>
        <div class="font-mono ta-right fs-muted">{{ c.missing_pct.toFixed(1) }}%</div>
        <div class="font-mono ta-right fs-muted">{{ c.distinct.toLocaleString() }}</div>
        <div class="font-mono ta-right">{{ fmtNum(c.mean) }}</div>
        <div class="font-mono ta-right fs-muted">{{ fmtNum(c.std) }}</div>
      </div>
    </div>

    <div class="footer-bar">
      <Button label="Cancel" outlined @click="cancel" />
      <Button class="btn-cta" @click="apply">Apply selection ({{ featCount }})</Button>
    </div>
  </div>
</template>

<style scoped>
.feature-sel { max-width: 1240px; margin: 0 auto; padding-bottom: 24px; }

.back-link { display: inline-flex; align-items: center; gap: 6px; background: none; border: 0; padding: 4px 0; font-size: 13px; color: var(--text-color-muted); cursor: pointer; margin-bottom: 16px; }
.back-link:hover { color: var(--text-color); }

.header-row { display: flex; align-items: flex-end; gap: 16px; margin-bottom: 20px; }
.header-text { display: flex; flex-direction: column; gap: 4px; flex: 1; }
.subtitle { font-size: 13px; color: var(--text-color-muted); }
.method-col { display: flex; flex-direction: column; gap: 5px; }
.field-label { font-size: 10.5px; font-weight: 700; letter-spacing: 0.08em; color: var(--text-color-muted); text-transform: uppercase; }
.method-select { display: flex; align-items: center; gap: 10px; height: 36px; background: var(--surface-card); border: 1px solid var(--surface-border-input); border-radius: 2px; padding: 0 12px; font-size: 13px; font-weight: 600; }
.method-select i { font-size: 10px; color: var(--text-color-muted); }

.info-panel { display: flex; gap: 12px; background: var(--surface-inset); border: 1px solid var(--surface-border-row); border-radius: 2px; padding: 12px 16px; margin-bottom: 16px; }
.info-bar { width: 4px; flex: none; background: var(--yellow); border-radius: 1px; }
.info-text { font-size: 12.5px; color: var(--text-color-secondary); line-height: 1.6; }

.panel { background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 2px; }

/* ── Heatmaps ─────────────────────────────────────────────────────────────── */
.heatmaps { display: flex; flex-direction: column; gap: 16px; margin-bottom: 16px; }
.heatmap-panel { padding: 14px 16px; }
.heatmap-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.heatmap-sub { font-size: 12px; color: var(--text-color-muted); margin-top: 3px; }

.legend-row { display: flex; align-items: center; gap: 14px; }
.legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-color-secondary); }
.legend-swatch { width: 14px; height: 14px; display: inline-block; border-radius: 2px; }

.hm-scroll { overflow-x: auto; }
.hm-grid { --hm-label: minmax(150px, 220px); display: grid; column-gap: 3px; row-gap: 3px; align-items: stretch; min-width: min-content; }
.hm-corner { position: sticky; left: 0; background: var(--surface-card); z-index: 2; }
.hm-colhead {
  font-size: 10.5px; color: var(--text-color-muted); font-weight: 600;
  padding: 0 4px 8px; text-align: center; align-self: end;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.hm-rowhead {
  position: sticky; left: 0; z-index: 1; background: var(--surface-card);
  font-size: 12px; font-weight: 600; color: var(--text-color-secondary);
  display: flex; align-items: center; padding-right: 10px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.hm-cell {
  display: flex; align-items: center; justify-content: center;
  min-height: 34px; padding: 6px 4px; border-radius: 2px;
  font-size: 11.5px; font-weight: 600;
}
.hm-empty { padding: 24px 4px; font-size: 12.5px; color: var(--text-color-muted); }

.table-header { display: flex; align-items: center; gap: 12px; padding: 14px 16px; }
.table-title { font-size: 13.5px; font-weight: 700; }
.table-count { font-size: 12px; color: var(--text-color-muted); }
.spacer { flex: 1; }
.search-input { width: 220px; height: 34px; }

.fs-grid { display: grid; column-gap: 12px; grid-template-columns: 36px minmax(170px,1.4fr) 80px 100px 100px 110px 110px; align-items: center; padding: 0 16px; }
.fs-grid--head { height: 38px; border-bottom: 2px solid var(--ink); font-size: 11px; font-weight: 700; letter-spacing: 0.07em; color: var(--text-color-muted); }
.fs-grid--row { min-height: 46px; border-bottom: 1px solid var(--surface-border-row); }
.fs-grid--row:hover { background: var(--surface-hover); }
.fs-grid--row:last-child { border-bottom: none; }
.ta-right { text-align: right; }

.checkbox-cell { display: flex; align-items: center; cursor: pointer; }
.checkbox { width: 18px; height: 18px; border-radius: 2px; border: 1px solid var(--surface-border-input); display: flex; align-items: center; justify-content: center; background: var(--surface-card); }
.checkbox.is-checked { border: 2px solid var(--yellow); background: var(--yellow); }
.checkbox i { font-size: 10px; color: var(--ink); }

.fs-name { font-size: 12.5px; font-weight: 600; }
.fs-name.is-unchecked { color: var(--text-color-muted-2); font-weight: 400; }
.fs-muted { color: var(--text-color-secondary); font-size: 12px; }
.type-tag { font-family: 'IBM Plex Mono', monospace; font-size: 10px; font-weight: 600; border: 1px solid var(--surface-border-input); color: var(--text-color-secondary); padding: 2px 7px; border-radius: 2px; }

.loading-line { padding: 24px; text-align: center; color: var(--text-color-muted); font-size: 13px; }

.footer-bar { position: sticky; bottom: 0; margin-top: 20px; display: flex; justify-content: flex-end; gap: 12px; background: var(--surface-ground); padding: 14px 0; border-top: 1px solid var(--surface-border); }
</style>

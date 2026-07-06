<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import datasetsAPI from '@/api/datasetsAPI'
import { calibrationDataset, targetCols, featureCols, featureOptions } from './newModelStore'
import PageHeader from '@/components/ui/PageHeader.vue'

const router = useRouter()
const toast = useToast()

const loading = ref(true)
const columns = ref([]) // [{name, type, missing_pct, distinct, mean, std, corr}]
const checked = ref({}) // { [name]: bool }
const search = ref('')

// Column stats are computed against the first selected target — with several
// targets, feature columns are shared across all of them via Step 03's
// default set, so this screen picks one representative target for the
// correlation column.
const statsTarget = computed(() => targetCols.value[0] ?? null)

onMounted(async () => {
  if (!calibrationDataset.value || !statsTarget.value) {
    router.replace({ name: 'model_new' })
    return
  }
  loading.value = true
  try {
    const { data } = await datasetsAPI.columnStats(calibrationDataset.value.id, statsTarget.value)
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
const corrPct = (v) => (v == null ? 0 : Math.round(Math.abs(v) * 100))

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
          Column statistics for <span class="font-mono">{{ calibrationDataset?.name }}</span> · target <span class="font-mono">{{ statsTarget }}</span>
        </div>
      </div>
      <div class="method-col">
        <label class="field-label">Selection method</label>
        <div class="method-select">Manual<i class="pi pi-chevron-down" /></div>
      </div>
    </div>

    <div class="info-panel">
      <span class="info-bar" />
      <div class="info-text">Select features manually using the column statistics below. Automated selection methods (correlation filter, recursive feature elimination) are planned here.</div>
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
        <div class="ta-right">MEAN</div><div class="ta-right">STD</div><div>|CORR| W/ TARGET</div>
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
        <div class="corr-cell">
          <div class="corr-track"><div class="corr-fill" :style="{ width: corrPct(c.corr) + '%' }" /></div>
          <span class="font-mono corr-value">{{ c.corr != null ? c.corr.toFixed(2) : '—' }}</span>
        </div>
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
.table-header { display: flex; align-items: center; gap: 12px; padding: 14px 16px; }
.table-title { font-size: 13.5px; font-weight: 700; }
.table-count { font-size: 12px; color: var(--text-color-muted); }
.spacer { flex: 1; }
.search-input { width: 220px; height: 34px; }

.fs-grid { display: grid; column-gap: 12px; grid-template-columns: 36px minmax(170px,1.3fr) 70px 90px 90px 90px 90px minmax(150px,1fr); align-items: center; padding: 0 16px; }
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

.corr-cell { display: flex; align-items: center; gap: 10px; }
.corr-track { flex: 1; height: 6px; background: var(--surface-border-row); border-radius: 1px; overflow: hidden; }
.corr-fill { height: 100%; background: var(--yellow-chart); }
.corr-value { font-size: 12px; font-weight: 600; width: 36px; text-align: right; }

.loading-line { padding: 24px; text-align: center; color: var(--text-color-muted); font-size: 13px; }

.footer-bar { position: sticky; bottom: 0; margin-top: 20px; display: flex; justify-content: flex-end; gap: 12px; background: var(--surface-ground); padding: 14px 0; border-top: 1px solid var(--surface-border); }
</style>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import creditRiskAPI from '@/api/creditRiskAPI'
import PageHeader from '@/components/ui/PageHeader.vue'

const router = useRouter()

const loading      = ref(false)
const noActiveRun  = ref(false)
const errorMessage = ref(null)

const scenarios     = ref([])       // available scenario names
const scenario      = ref(null)     // selected
const ratings       = ref([])       // observed notches (best -> worst)
const matrix        = ref([])       // % rows
const counts        = ref([])       // raw transition counts
const rowTotals     = ref([])       // obs feeding each from-row
const nTransitions  = ref(0)
const nClients      = ref(0)
const years         = ref([])       // [minYear, maxYear]

const yearLabel = computed(() =>
  years.value.length === 2 ? `${years.value[0]}–${years.value[1]}` : ''
)

// Per-row max drives the off-diagonal alpha ramp: real rows are normalised to
// 100 %, so scaling against the row's own max keeps migration contrast readable
// whether a row is concentrated on the diagonal or spread out. Diagonal keeps
// the ink/yellow treatment.
function cellStyle(val, rowIdx, colIdx) {
  if (rowIdx === colIdx) {
    return { background: 'var(--ink)', color: 'var(--yellow)' }
  }
  const row = matrix.value[rowIdx] || []
  const rowMax = Math.max(1, ...row.filter((_, j) => j !== rowIdx))
  const alpha = Math.min(0.08 + (val / rowMax) * 0.8, 0.85)
  return {
    background: `rgba(46, 46, 56, ${alpha.toFixed(2)})`,
    color: alpha > 0.45 ? '#FFFFFF' : 'var(--text-color)',
  }
}

function cellTitle(rowIdx, colIdx) {
  const c = counts.value?.[rowIdx]?.[colIdx] ?? 0
  const t = rowTotals.value?.[rowIdx] ?? 0
  return `${c} of ${t} transitions`
}

async function fetchTransitions() {
  loading.value = true
  errorMessage.value = null
  try {
    const params = scenario.value ? { scenario: scenario.value } : {}
    const { data } = await creditRiskAPI.analysisTransitions(params)
    scenarios.value    = data.scenarios ?? []
    scenario.value     = data.scenario
    ratings.value      = data.ratings ?? []
    matrix.value       = data.matrix ?? []
    counts.value       = data.counts ?? []
    rowTotals.value    = data.row_totals ?? []
    nTransitions.value = data.n_transitions ?? 0
    nClients.value     = data.n_clients ?? 0
    years.value        = data.years ?? []
    noActiveRun.value  = false
  } catch (e) {
    ratings.value = []
    matrix.value = []
    if (e?.response?.status === 404) {
      noActiveRun.value = true
    } else {
      errorMessage.value = e?.response?.data?.error ?? e.message
    }
  } finally {
    loading.value = false
  }
}

function selectScenario(s) {
  if (s === scenario.value) return
  scenario.value = s
  fetchTransitions()
}

onMounted(fetchTransitions)
</script>

<template>
  <div>
    <PageHeader
      eyebrow="ANALYSIS"
      title="Transitions"
      subtitle="Forecast-implied 1-year credit-grade transition probabilities (%) from the active run's KMV rating paths. Ink diagonal = stable; gray intensity = migration size."
    >
      <template #actions>
        <span v-if="ratings.length" class="font-mono meta-caption">
          {{ nClients }} clients &middot; {{ nTransitions }} transitions
          <template v-if="yearLabel"> &middot; {{ yearLabel }}</template>
        </span>
      </template>
    </PageHeader>

    <!-- Scenario toggle -->
    <div v-if="scenarios.length" class="metric-row">
      <span class="metric-label">SCENARIO</span>
      <div
        v-for="s in scenarios"
        :key="s"
        class="metric-chip"
        :class="{ active: scenario === s }"
        @click="selectScenario(s)"
      >{{ s }}</div>
    </div>

    <!-- No active run -->
    <div v-if="noActiveRun && !loading" class="panel flex flex-column align-items-center justify-content-center gap-3" style="height: 22rem">
      <i class="pi pi-sitemap text-4xl text-color-secondary opacity-50" />
      <div class="text-center">
        <div class="text-sm font-medium mb-1">No active analysis run</div>
        <div class="text-xs text-color-secondary">Set an active run in Job History to view rating transitions.</div>
      </div>
      <Button label="Job History" icon="pi pi-list" size="small" @click="router.push({ name: 'jobs_history' })" />
    </div>

    <!-- Error / no transition data -->
    <div v-else-if="errorMessage && !loading" class="panel flex flex-column align-items-center justify-content-center gap-3" style="height: 22rem">
      <i class="pi pi-exclamation-circle text-4xl text-color-secondary opacity-50" />
      <div class="text-center" style="max-width: 28rem">
        <div class="text-sm font-medium mb-1">Transition data unavailable</div>
        <div class="text-xs text-color-secondary">{{ errorMessage }}</div>
      </div>
      <Button label="Job History" icon="pi pi-list" size="small" @click="router.push({ name: 'jobs_history' })" />
    </div>

    <!-- Loading -->
    <div v-else-if="loading" class="flex justify-content-center align-items-center" style="height: 12rem">
      <i class="pi pi-spin pi-spinner text-3xl text-color-secondary" />
    </div>

    <!-- Matrix -->
    <div v-else-if="ratings.length" class="panel">
      <div class="matrix-grid matrix-grid--head">
        <div>FROM &#8594; TO</div>
        <div v-for="r in ratings" :key="r" class="ta-center">{{ r }}</div>
      </div>
      <div v-for="(row, ri) in matrix" :key="ri" class="matrix-grid matrix-grid--row">
        <div class="row-label">{{ ratings[ri] }}</div>
        <div
          v-for="(val, ci) in row" :key="ci"
          class="font-mono cell"
          :style="cellStyle(val, ri, ci)"
          :title="cellTitle(ri, ci)"
        >{{ val.toFixed(1) }}%</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
  padding: 16px;
}

.meta-caption { font-size: 11.5px; color: var(--text-color-muted); }

.metric-row { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.metric-label { font-size: 11px; font-weight: 700; letter-spacing: 0.08em; color: var(--text-color-muted); }
.metric-chip {
  padding: 7px 12px;
  border-radius: 2px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid var(--surface-border-input);
  background: #FFFFFF;
  color: var(--text-color-secondary);
}
.metric-chip:hover { border-color: var(--ink); }
.metric-chip.active { background: var(--ink); color: #FFFFFF; border-color: var(--ink); }

.matrix-grid {
  display: grid;
  grid-template-columns: 90px repeat(v-bind('ratings.length || 8'), 1fr);
  column-gap: 8px;
  align-items: center;
}
.matrix-grid--head {
  height: 36px;
  border-bottom: 2px solid var(--ink);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--text-color-muted);
}
.matrix-grid--row { padding: 2px 0; }
.ta-center { text-align: center; }
.row-label { font-size: 13px; font-weight: 600; }
.cell {
  margin: 2px 0;
  padding: 11px 0;
  text-align: center;
  font-size: 12px;
  font-weight: 600;
  border-radius: 2px;
}
</style>

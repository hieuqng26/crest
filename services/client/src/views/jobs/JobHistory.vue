<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import jobsAPI, { KIND } from '@/api/jobs'
import creditRiskAPI from '@/api/creditRiskAPI'
import { fmtDate } from '@/utils/datetime'

import PageHeader from '@/components/ui/PageHeader.vue'
import StatusDot from '@/components/ui/StatusDot.vue'

const router = useRouter()

const jobs = ref([])
const loading = ref(true)

const fetchJobs = async () => {
  jobs.value = await jobsAPI.listJobs()
}

// Mirrors the old CreditRiskJobs.vue behaviour: if no analysis run is marked
// active, promote the most recently finished successful one so PD/LGD and ECL
// have data to show by default.
const autoSetActiveAnalysisRun = async () => {
  const analysisJobs = jobs.value.filter((j) => j.kind === KIND.ANALYSIS)
  if (analysisJobs.some((j) => j.raw.is_active)) return
  const latest = analysisJobs
    .filter((j) => j.status === 'success')
    .sort((a, b) => new Date(b.finished_at ?? b.started_at ?? 0) - new Date(a.finished_at ?? a.started_at ?? 0))[0]
  if (!latest) return
  try {
    await creditRiskAPI.setActiveRun(latest.run_id)
  } catch {
    // best-effort — not critical to page function
  }
}

let pollTimer = null
const hasActive = computed(() => jobs.value.some((j) => j.status === 'running' || j.status === 'queued'))
const startPolling = () => {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    if (!hasActive.value) { stopPolling(); return }
    await fetchJobs()
  }, 5000)
}
const stopPolling = () => { clearInterval(pollTimer); pollTimer = null }

onMounted(async () => {
  loading.value = true
  await fetchJobs()
  loading.value = false
  await autoSetActiveAnalysisRun()
  if (hasActive.value) startPolling()
})
onUnmounted(stopPolling)

const TYPE_CHIPS = ['All', 'Training', 'Forecast', 'Analysis']
const activeType = ref('All')

const typeCounts = computed(() => {
  const c = { All: jobs.value.length, Training: 0, Forecast: 0, Analysis: 0 }
  for (const j of jobs.value) {
    const label = j.kind === KIND.TRAINING ? 'Training' : j.kind === KIND.FORECAST ? 'Forecast' : 'Analysis'
    c[label]++
  }
  return c
})

const search = ref('')

const filtered = computed(() => {
  const kindOf = { Training: KIND.TRAINING, Forecast: KIND.FORECAST, Analysis: KIND.ANALYSIS }
  const q = search.value.trim().toLowerCase()
  return jobs.value
    .filter((j) => activeType.value === 'All' || j.kind === kindOf[activeType.value])
    .filter((j) => !q || (j.name + j.ref + j.run_id).toLowerCase().includes(q))
    .sort((a, b) => new Date(b.started_at ?? 0) - new Date(a.started_at ?? 0))
})

const progressLabel = (j) =>
  j.status === 'success' ? 'Completed' : j.status === 'failed' ? `Failed at ${j.progress}%` : '—'

const openJob = (j) => router.push({ name: 'jobs_detail', params: { kind: j.kind, run_id: j.run_id } })
</script>

<template>
  <div>
    <PageHeader title="Job History" subtitle="Every training, forecast and analysis run">
      <template #actions>
        <Button class="btn-new-model" @click="router.push({ name: 'model_new' })">
          <span class="btn-plus">+</span>
          <span>New Model</span>
        </Button>
      </template>
    </PageHeader>

    <div class="toolbar">
      <button
        v-for="t in TYPE_CHIPS"
        :key="t"
        type="button"
        class="type-chip"
        :class="{ 'is-active': activeType === t }"
        @click="activeType = t"
      >
        <span>{{ t }}</span>
        <span class="font-mono chip-count">{{ typeCounts[t] }}</span>
      </button>
      <div class="toolbar-spacer" />
      <InputText v-model="search" placeholder="Search by run, model or dataset…" class="search-input" />
    </div>

    <div class="showing-line">Showing {{ filtered.length }} of {{ jobs.length }} runs</div>

    <div class="panel">
      <div class="table-scroll">
        <div class="jobs-grid jobs-grid--head">
          <div>RUN</div><div>TYPE</div><div>INPUT</div><div>STATUS</div><div>PROGRESS</div><div>STARTED</div><div>FINISHED</div><div>BY</div>
        </div>

        <div v-if="!loading && filtered.length === 0" class="empty-state">
          <i class="pi pi-inbox" />
          <p>No runs match your filters.</p>
        </div>

        <div v-for="j in filtered" :key="j.run_id" class="jobs-grid jobs-grid--row" @click="openJob(j)">
          <div class="run-name-cell">
            <div class="run-name">{{ j.name }}</div>
            <div class="font-mono run-id">{{ j.run_id }}</div>
          </div>
          <div><span class="type-tag">{{ j.kind === KIND.TRAINING ? 'TRAINING' : j.kind === KIND.FORECAST ? 'FORECAST' : 'ANALYSIS' }}</span></div>
          <div class="font-mono cell-ref">{{ j.ref }}</div>
          <div><StatusDot :status="j.status" /></div>
          <div class="progress-cell">
            <div v-if="j.status === 'running'" class="progress-row">
              <div class="progress-track"><div class="progress-fill" :style="{ width: j.progress + '%' }" /></div>
              <span class="font-mono progress-pct">{{ j.progress }}%</span>
            </div>
            <span v-else class="progress-label">{{ progressLabel(j) }}</span>
          </div>
          <div class="font-mono cell-mono">{{ j.started_at ? fmtDate(j.started_at) : '—' }}</div>
          <div class="font-mono cell-mono">{{ j.finished_at ? fmtDate(j.finished_at) : '—' }}</div>
          <div class="cell-by">{{ j.triggered_by ? j.triggered_by.split('@')[0] : '—' }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.btn-new-model {
  height: 38px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 18px;
}
.btn-plus {
  color: var(--yellow);
  font-weight: 700;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.toolbar-spacer { flex: 1; }

.type-chip {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 12px;
  border-radius: 2px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid var(--surface-border-input);
  background: var(--surface-card);
  color: var(--text-color-secondary);
  transition: border-color 0.15s ease;
}
.type-chip:hover { border-color: var(--ink); }
.type-chip.is-active {
  background: var(--ink);
  color: #fff;
  border-color: var(--ink);
}
.chip-count { color: var(--text-color-muted-2); }
.type-chip.is-active .chip-count { color: var(--yellow); }

.search-input {
  width: 280px;
  height: 36px;
}

.showing-line {
  font-size: 12px;
  color: var(--text-color-muted);
  margin-bottom: 8px;
}

.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
}

.table-scroll {
  overflow-x: auto;
}

.jobs-grid {
  display: grid;
  grid-template-columns: minmax(200px, 1.3fr) 110px minmax(190px, 1fr) 125px 150px 140px 140px 70px;
  column-gap: 12px;
  align-items: center;
  padding: 6px 16px;
  /* Fixed floor (not width:max-content) so every row resolves its fr tracks
     against the same total width — max-content would size each row to its own
     content, misaligning columns row-to-row when cell text lengths differ. */
  min-width: 1241px;
}
.jobs-grid--head {
  height: 40px;
  padding-top: 0;
  padding-bottom: 0;
  border-bottom: 2px solid var(--ink);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.07em;
  color: var(--text-color-muted);
}
.jobs-grid--row {
  min-height: 52px;
  border-bottom: 1px solid var(--surface-border-row);
  cursor: pointer;
  transition: background-color 0.1s ease;
}
.jobs-grid--row:hover { background: var(--surface-hover); }
.jobs-grid--row:last-child { border-bottom: none; }

.run-name-cell { display: flex; flex-direction: column; gap: 2px; padding-right: 12px; overflow: hidden; }
.run-name { font-size: 13.5px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.run-id { font-size: 10.5px; color: var(--text-color-muted-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.type-tag {
  display: inline-block;
  padding: 3px 7px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--text-color-secondary);
  border: 1px solid var(--surface-border-input);
  border-radius: 2px;
}

.cell-ref, .cell-mono { font-size: 11.5px; color: var(--text-color-secondary); }
.cell-by { font-size: 12.5px; color: var(--text-color-secondary); }

.progress-cell { padding-right: 20px; }
.progress-row { display: flex; align-items: center; gap: 8px; }
.progress-track { flex: 1; height: 5px; background: var(--surface-border-row); border-radius: 1px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--yellow); }
.progress-pct { font-size: 11px; color: var(--text-color-muted); }
.progress-label { font-size: 12px; color: var(--text-color-muted-2); }

.empty-state { text-align: center; padding: 40px 0; color: var(--text-color-muted); }
.empty-state i { font-size: 24px; display: block; margin-bottom: 8px; opacity: 0.6; }
.empty-state p { margin: 0; }
</style>

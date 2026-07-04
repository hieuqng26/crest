<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useStore } from 'vuex'

import datasetsAPI from '@/api/datasetsAPI'
import calibrationsAPI from '@/api/calibrationsAPI'
import forecastRunsAPI from '@/api/forecastRunsAPI'
import creditRiskAPI from '@/api/creditRiskAPI'
import { fmtDate } from '@/utils/datetime'

import PageHeader from '@/components/ui/PageHeader.vue'
import StatCard from '@/components/ui/StatCard.vue'
import StatusDot from '@/components/ui/StatusDot.vue'

const router = useRouter()
const store = useStore()

const currentUser = store.getters.getCurrentUser
const firstName = computed(() => {
  const name = (currentUser?.email || '').split('@')[0]
  return name.split(/[._-]/)[0] || 'there'
})
const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
})
const todayLabel = new Date().toLocaleDateString('en-GB', {
  weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
})

const loading = ref(true)
const datasets = ref([])
const calibrationRuns = ref([])
const forecastRuns = ref([])
const creditRiskRuns = ref([])

const daysAgo = (iso) => {
  if (!iso) return Infinity
  const s = iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? Infinity : (Date.now() - d.getTime()) / 86400000
}

const load = async () => {
  loading.value = true
  const [dRes, cRes, fRes, xRes] = await Promise.allSettled([
    datasetsAPI.list(),
    calibrationsAPI.list({ per_page: 200 }),
    forecastRunsAPI.list(),
    creditRiskAPI.listRuns()
  ])
  datasets.value = dRes.status === 'fulfilled' ? (dRes.value.data ?? []) : []
  calibrationRuns.value = cRes.status === 'fulfilled' ? (cRes.value.data.items ?? cRes.value.data ?? []) : []
  forecastRuns.value = fRes.status === 'fulfilled' ? (fRes.value.data ?? []) : []
  creditRiskRuns.value = xRes.status === 'fulfilled' ? (xRes.value.data ?? []) : []
  loading.value = false
}
onMounted(load)

const analysisRunsCount = computed(() => forecastRuns.value.length + creditRiskRuns.value.length)

const failedRuns = computed(() => {
  const all = [...calibrationRuns.value, ...forecastRuns.value, ...creditRiskRuns.value]
  return all
    .filter((r) => r.status === 'failed' && daysAgo(r.finished_at ?? r.created_at ?? r.started_at) <= 7)
    .sort((a, b) => new Date(b.finished_at ?? 0) - new Date(a.finished_at ?? 0))
})

const modelRunsCaption = computed(() => {
  const n = calibrationRuns.value.filter((r) => r.status === 'running').length
  return n > 0 ? `${n} running now` : null
})
const analysisRunsCaption = computed(() => {
  const latest = [...forecastRuns.value, ...creditRiskRuns.value]
    .filter((r) => r.finished_at)
    .sort((a, b) => new Date(b.finished_at) - new Date(a.finished_at))[0]
  return latest ? `last finished ${fmtDate(latest.finished_at)}` : null
})
const failedCaption = computed(() => {
  const r = failedRuns.value[0]
  return r ? (r.config_name || r.name || r.run_id?.slice(0, 8)) : null
})

// Unified recent-runs list — merges training (calibration) + analysis (forecast / credit risk)
const recentRuns = computed(() => {
  const training = calibrationRuns.value.map((r) => ({
    run_id: r.run_id,
    name: r.config_name || r.run_id.slice(0, 8),
    kind: 'TRAINING',
    status: r.status,
    finished_at: r.finished_at ?? r.started_at,
    triggered_by: r.triggered_by,
    routeName: 'calibrate_run'
  }))
  const forecast = forecastRuns.value.map((r) => ({
    run_id: r.run_id,
    name: r.name || r.target_col || r.run_id.slice(0, 8),
    kind: 'ANALYSIS',
    status: r.status,
    finished_at: r.finished_at ?? r.created_at,
    triggered_by: r.triggered_by,
    routeName: 'forecast_run'
  }))
  const creditRisk = creditRiskRuns.value.map((r) => ({
    run_id: r.run_id,
    name: r.run_id.slice(0, 8),
    kind: 'ANALYSIS',
    status: r.status,
    finished_at: r.finished_at ?? r.created_at,
    triggered_by: r.triggered_by,
    routeName: 'credit_risk_run'
  }))
  return [...training, ...forecast, ...creditRisk]
    .sort((a, b) => new Date(b.finished_at ?? 0) - new Date(a.finished_at ?? 0))
    .slice(0, 8)
})

const openRun = (r) => router.push({ name: r.routeName, params: { run_id: r.run_id } })

const quickActions = [
  { label: 'Upload dataset', desc: 'CSV upload or live query', to: { name: 'datasets' } },
  { label: 'Train new model', desc: 'Auto or manual mode', to: { name: 'model_new' } },
  { label: 'Explore heatmap', desc: 'Financial ratios by sector', to: { name: 'analysis_heatmap' } },
  { label: 'Review audit trail', desc: 'System activity records', to: { name: 'log' } }
]

const systemStatus = [
  { label: 'API', value: 'Operational' },
  { label: 'Task queue', value: 'Operational' },
  { label: 'Object storage', value: 'Operational' }
]
</script>

<template>
  <div>
    <PageHeader :title="`${greeting}, ${firstName}`" :subtitle="todayLabel">
      <template #actions>
        <Button class="btn-job-history" outlined label="Job History" @click="router.push({ name: 'jobs_history' })" />
        <Button class="btn-new-model" @click="router.push({ name: 'model_new' })">
          <span class="btn-plus">+</span>
          <span>New Model</span>
        </Button>
      </template>
    </PageHeader>

    <!-- KPI strip -->
    <div class="kpi-grid">
      <StatCard label="Datasets" :value="loading ? '—' : datasets.length" />
      <StatCard label="Model runs" :value="loading ? '—' : calibrationRuns.length" :caption="modelRunsCaption" />
      <StatCard label="Analysis runs" :value="loading ? '—' : analysisRunsCount" :caption="analysisRunsCaption" />
      <StatCard
        label="Failed · Last 7 days"
        :value="loading ? '—' : failedRuns.length"
        :caption="failedCaption"
        tone="error"
      />
    </div>

    <!-- Main content -->
    <div class="dashboard-grid">
      <!-- Recent runs -->
      <div class="panel recent-runs-card">
        <div class="recent-runs-header">
          <h3>Recent runs</h3>
          <a class="view-all-link" @click="router.push({ name: 'jobs_history' })">View all</a>
        </div>

        <div class="runs-grid runs-grid--head">
          <div>RUN</div><div>TYPE</div><div>STATUS</div><div>FINISHED</div><div>BY</div>
        </div>

        <div v-if="!loading && recentRuns.length === 0" class="empty-state">
          <i class="pi pi-inbox" />
          <p>No runs yet.</p>
        </div>

        <div
          v-for="r in recentRuns"
          :key="r.run_id"
          class="runs-grid runs-grid--row"
          @click="openRun(r)"
        >
          <div class="run-name-cell">
            <div class="run-name">{{ r.name }}</div>
            <div class="font-mono run-id">{{ r.run_id }}</div>
          </div>
          <div><span class="type-tag">{{ r.kind }}</span></div>
          <div><StatusDot :status="r.status" /></div>
          <div class="font-mono cell-finished">{{ r.finished_at ? fmtDate(r.finished_at) : '—' }}</div>
          <div class="cell-by">{{ r.triggered_by ? r.triggered_by.split('@')[0] : '—' }}</div>
        </div>
      </div>

      <!-- Side column: quick actions + system status -->
      <div class="side-column">
        <div class="panel quick-actions-card">
          <h3 class="quick-actions-title">Quick actions</h3>
          <a
            v-for="a in quickActions"
            :key="a.label"
            class="quick-action-row"
            @click="router.push(a.to)"
          >
            <div class="quick-action-text">
              <div class="quick-action-label">{{ a.label }}</div>
              <div class="quick-action-desc">{{ a.desc }}</div>
            </div>
            <span class="quick-action-arrow">&rarr;</span>
          </a>
        </div>

        <div class="system-card">
          <div class="eyebrow system-eyebrow">System</div>
          <div v-for="s in systemStatus" :key="s.label" class="system-row">
            <span class="system-dot" />
            <span class="system-label">{{ s.label }}</span>
            <span class="system-value font-mono">{{ s.value }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.btn-job-history,
.btn-new-model {
  height: 38px;
}
.btn-job-history {
  padding: 0 16px;
}
.btn-new-model {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 18px;
}
.btn-plus {
  color: var(--yellow);
  font-weight: 700;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: 1.7fr 1fr;
  gap: 16px;
  align-items: start;
}

.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
}

.recent-runs-header {
  display: flex;
  align-items: center;
  padding: 14px 16px;
}
.recent-runs-header h3 {
  flex: 1;
}
.view-all-link {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-color-secondary);
  cursor: pointer;
  border-bottom: 2px solid var(--yellow);
  padding-bottom: 1px;
  transition: color 0.15s ease;
}
.view-all-link:hover {
  color: var(--ink);
}

.runs-grid {
  display: grid;
  grid-template-columns: minmax(200px, 1.4fr) 120px 120px 150px 80px;
  column-gap: 12px;
  align-items: center;
  padding: 0 16px;
}
.runs-grid--head {
  height: 38px;
  border-bottom: 2px solid var(--ink);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.07em;
  color: var(--text-color-muted);
}
.runs-grid--row {
  height: 48px;
  border-bottom: 1px solid var(--surface-border-row);
  cursor: pointer;
  transition: background-color 0.1s ease;
}
.runs-grid--row:hover {
  background: var(--surface-hover);
}
.runs-grid--row:last-child {
  border-bottom: none;
}

.run-name-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-right: 12px;
  overflow: hidden;
}
.run-name {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.run-id {
  font-size: 10px;
  color: var(--text-color-muted-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cell-finished {
  font-size: 11.5px;
  color: var(--text-color-secondary);
}
.cell-by {
  font-size: 12.5px;
  color: var(--text-color-secondary);
}
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

.empty-state {
  text-align: center;
  padding: 40px 0;
  color: var(--text-color-muted);
}
.empty-state i {
  font-size: 24px;
  display: block;
  margin-bottom: 8px;
  opacity: 0.6;
}
.empty-state p {
  margin: 0;
}

.side-column {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.quick-actions-card {
  padding: 6px 0;
}
.quick-actions-title {
  padding: 10px 16px 6px;
}
.quick-action-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 16px;
  border-left: 3px solid transparent;
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}
.quick-action-row:hover {
  background: var(--surface-hover);
  border-left-color: var(--yellow);
}
.quick-action-text {
  flex: 1;
}
.quick-action-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-color);
}
.quick-action-desc {
  font-size: 11.5px;
  color: var(--text-color-muted-2);
  margin-top: 1px;
}
.quick-action-arrow {
  font-size: 14px;
  color: var(--text-color-muted);
}

.system-card {
  background: var(--ink);
  border-radius: 2px;
  padding: 16px 18px;
}
.system-eyebrow {
  color: var(--chrome-text-muted) !important;
  margin-bottom: 10px;
}
.system-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 0;
  border-bottom: 1px solid var(--chrome-hover);
}
.system-row:last-child {
  border-bottom: none;
}
.system-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--success-color);
  flex-shrink: 0;
}
.system-label {
  flex: 1;
  font-size: 12.5px;
  color: var(--chrome-item-muted);
}
.system-value {
  font-size: 11.5px;
  color: #fff;
}

@media (max-width: 1200px) {
  .kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}
</style>

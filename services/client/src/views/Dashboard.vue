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

const failedLast7Days = computed(() => {
  const all = [...calibrationRuns.value, ...forecastRuns.value, ...creditRiskRuns.value]
  return all.filter(
    (r) => r.status === 'failed' && daysAgo(r.finished_at ?? r.created_at ?? r.started_at) <= 7
  ).length
})

// Unified recent-runs list — merges training (calibration) + analysis (forecast / credit risk)
const recentRuns = computed(() => {
  const training = calibrationRuns.value.map((r) => ({
    run_id: r.run_id,
    name: r.config_name || r.run_id.slice(0, 8),
    kind: 'Training',
    status: r.status,
    finished_at: r.finished_at ?? r.started_at,
    triggered_by: r.triggered_by,
    routeName: 'calibrate_run'
  }))
  const forecast = forecastRuns.value.map((r) => ({
    run_id: r.run_id,
    name: r.name || r.target_col || r.run_id.slice(0, 8),
    kind: 'Analysis',
    status: r.status,
    finished_at: r.finished_at ?? r.created_at,
    triggered_by: r.triggered_by,
    routeName: 'forecast_run'
  }))
  const creditRisk = creditRiskRuns.value.map((r) => ({
    run_id: r.run_id,
    name: r.run_id.slice(0, 8),
    kind: 'Analysis',
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
  { label: 'Upload dataset', icon: 'pi pi-upload', to: { name: 'datasets' } },
  { label: 'Train new model', icon: 'pi pi-sparkles', to: { name: 'model_new' } },
  { label: 'Explore heatmap', icon: 'pi pi-th-large', to: { name: 'analysis_heatmap' } },
  { label: 'Review audit trail', icon: 'pi pi-shield', to: { name: 'log' } }
]

const systemStatus = [
  { label: 'API', ok: true },
  { label: 'Task queue', ok: true },
  { label: 'Object storage', ok: true }
]
</script>

<template>
  <div>
    <PageHeader :title="`${greeting}, ${firstName}`" :subtitle="todayLabel">
      <template #actions>
        <Button label="Job History" outlined @click="router.push({ name: 'jobs_history' })" />
        <Button label="New Model" icon="pi pi-plus" @click="router.push({ name: 'model_new' })" />
      </template>
    </PageHeader>

    <!-- KPI strip -->
    <div class="kpi-grid">
      <StatCard label="Datasets" :value="loading ? '—' : datasets.length" />
      <StatCard label="Model runs" :value="loading ? '—' : calibrationRuns.length" />
      <StatCard label="Analysis runs" :value="loading ? '—' : analysisRunsCount" />
      <StatCard
        label="Failed · Last 7 days"
        :value="loading ? '—' : failedLast7Days"
        tone="error"
      />
    </div>

    <!-- Main content -->
    <div class="dashboard-grid">
      <!-- Recent runs -->
      <div class="surface-card border-round shadow-1 recent-runs-card">
        <div class="recent-runs-header">
          <h3 class="m-0">Recent runs</h3>
          <a class="view-all-link" @click="router.push({ name: 'jobs_history' })">View all</a>
        </div>
        <DataTable :value="recentRuns" :loading="loading" size="small" rowHover @row-click="(e) => openRun(e.data)">
          <template #empty>
            <div class="empty-state">
              <i class="pi pi-inbox" />
              <p class="m-0">No runs yet.</p>
            </div>
          </template>
          <Column header="Run">
            <template #body="{ data }">
              <div>
                <div class="run-name">{{ data.name }}</div>
                <div class="font-mono run-id">{{ data.run_id }}</div>
              </div>
            </template>
          </Column>
          <Column header="Type" style="width: 7rem">
            <template #body="{ data }">
              <span class="type-tag">{{ data.kind }}</span>
            </template>
          </Column>
          <Column header="Status" style="width: 8rem">
            <template #body="{ data }">
              <StatusDot :status="data.status" />
            </template>
          </Column>
          <Column header="Finished" style="width: 9rem">
            <template #body="{ data }">
              <span class="font-mono cell-muted">{{ data.finished_at ? fmtDate(data.finished_at) : '—' }}</span>
            </template>
          </Column>
          <Column header="By" style="width: 7rem">
            <template #body="{ data }">
              <span class="cell-muted">{{ data.triggered_by ? data.triggered_by.split('@')[0] : '—' }}</span>
            </template>
          </Column>
        </DataTable>
      </div>

      <!-- Side column: quick actions + system status -->
      <div class="side-column">
        <div class="surface-card border-round shadow-1 quick-actions-card">
          <h3 class="m-0 mb-2">Quick actions</h3>
          <a
            v-for="a in quickActions"
            :key="a.label"
            class="quick-action-row"
            @click="router.push(a.to)"
          >
            <i :class="a.icon" />
            <span class="quick-action-label">{{ a.label }}</span>
            <i class="pi pi-arrow-right quick-action-arrow" />
          </a>
        </div>

        <div class="system-card">
          <div class="eyebrow system-eyebrow">System</div>
          <div v-for="s in systemStatus" :key="s.label" class="system-row">
            <span class="system-dot" />
            <span class="system-label">{{ s.label }}</span>
            <span class="system-value">Operational</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: 1.7fr 1fr;
  gap: 1.5rem;
  align-items: start;
}

.recent-runs-card {
  padding: 1.25rem;
}
.recent-runs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}
.view-all-link {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-color-secondary);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  padding-bottom: 1px;
  transition: border-color 0.15s ease, color 0.15s ease;
}
.view-all-link:hover {
  color: var(--text-color);
  border-bottom-color: var(--yellow);
}

.run-name {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-color);
}
.run-id {
  font-size: 0.75rem;
  color: var(--text-color-muted);
}
.cell-muted {
  font-size: 0.8125rem;
  color: var(--text-color-secondary);
}
.type-tag {
  display: inline-block;
  padding: 0.15rem 0.45rem;
  font-size: 0.6875rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-color-secondary);
  border: 1px solid var(--surface-border-input);
}

.empty-state {
  text-align: center;
  padding: 2.5rem 0;
  color: var(--text-color-muted);
}
.empty-state i {
  font-size: 1.5rem;
  display: block;
  margin-bottom: 0.5rem;
  opacity: 0.6;
}

.side-column {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.quick-actions-card {
  padding: 1.25rem;
}
.quick-action-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.625rem 0.625rem 0.625rem 0.5rem;
  border-left: 3px solid transparent;
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}
.quick-action-row:hover {
  background: var(--surface-hover);
  border-left-color: var(--yellow);
}
.quick-action-row i:first-child {
  color: var(--text-color-muted);
  width: 1.25rem;
  text-align: center;
}
.quick-action-label {
  flex: 1;
  font-size: 0.875rem;
  color: var(--text-color);
}
.quick-action-arrow {
  font-size: 0.75rem;
  color: var(--text-color-muted-2);
}

.system-card {
  background: var(--ink);
  padding: 1.125rem 1.25rem;
}
.system-eyebrow {
  color: var(--chrome-text-muted) !important;
  margin-bottom: 0.75rem;
}
.system-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0;
}
.system-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success-color);
  flex-shrink: 0;
}
.system-label {
  flex: 1;
  font-size: 0.8125rem;
  color: #fff;
}
.system-value {
  font-size: 0.75rem;
  font-family: 'IBM Plex Mono', monospace;
  color: var(--chrome-text-muted);
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

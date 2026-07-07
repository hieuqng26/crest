<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useConfirm } from 'primevue/useconfirm'
import { useToast } from 'primevue/usetoast'

import workflowsAPI from '@/api/workflowsAPI'
import { fmtDate, duration } from '@/utils/datetime'
import CommonDataTable from '@/components/Table/CommonDataTable.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import creditRiskAPI from '@/api/creditRiskAPI'
import { analysisResultColumns } from './parts/resultColumns.js'
import DiagnosisBacktestingTab from './parts/DiagnosisBacktestingTab.vue'
import ForecastResultsTab from './parts/ForecastResultsTab.vue'
import ScenarioChips from './parts/ScenarioChips.vue'
import BaseTable from '@/views/composables/BaseTable.vue'

const route = useRoute()
const router = useRouter()
const confirm = useConfirm()
const toast = useToast()

const runId = computed(() => route.params.run_id)
const wf = ref(null)
const loading = ref(false)
const actionBusy = ref(false)

const fetchWorkflow = async () => {
  try {
    const { data } = await workflowsAPI.get(runId.value)
    wf.value = data
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load workflow', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  }
}

let pollTimer = null
const isLive = () => wf.value?.status === 'running' || wf.value?.status === 'queued'
const startPolling = () => { if (!pollTimer) pollTimer = setInterval(fetchWorkflow, 3000) }
const stopPolling = () => { clearInterval(pollTimer); pollTimer = null }

onMounted(async () => {
  loading.value = true
  await fetchWorkflow()
  loading.value = false
  if (isLive()) startPolling()
})
onUnmounted(stopPolling)
watch(() => wf.value?.status, (s) => { if (s === 'running' || s === 'queued') startPolling(); else stopPolling() })

const STATUS_META = {
  success: { dot: 'var(--success-color)', text: 'var(--success-text-color)', label: 'SUCCESS' },
  failed: { dot: 'var(--error-color)', text: 'var(--error-text-color)', label: 'FAILED' },
  running: { dot: 'var(--running-color)', text: 'var(--running-text-color)', label: 'RUNNING' },
  queued: { dot: 'var(--queued-color)', text: 'var(--queued-text-color)', label: 'QUEUED' }
}
const statusMeta = computed(() => STATUS_META[wf.value?.status] || STATUS_META.queued)

// ── Tabs ──────────────────────────────────────────────────────────────────────
const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'diagnosis', label: 'Diagnosis & Backtesting' },
  { key: 'forecast', label: 'Forecast' },
  { key: 'credit', label: 'Credit Results' }
]
const activeTab = computed({
  get: () => TABS.find((t) => t.key === route.query.tab)?.key || 'overview',
  set: (v) => router.replace({ query: { ...route.query, tab: v } })
})

// ── Overview tab ──────────────────────────────────────────────────────────────
const runDetailRows = computed(() => {
  if (!wf.value) return []
  return [
    { k: 'Run ID', v: wf.value.run_id, mono: true },
    { k: 'Training dataset', v: wf.value.calibration_dataset_name ?? '—', mono: true },
    { k: 'Macro forecast dataset', v: wf.value.forecast_dataset_name ?? '—', mono: true },
    { k: 'Credit portfolio dataset', v: wf.value.credit_dataset_name ?? '—', mono: true },
    { k: 'Financial portfolio dataset', v: wf.value.financial_dataset_name ?? '—', mono: true },
    { k: 'Triggered by', v: wf.value.triggered_by?.split('@')[0] ?? '—' },
    { k: 'Started', v: wf.value.started_at ? fmtDate(wf.value.started_at) : '—', mono: true },
    { k: 'Finished', v: wf.value.finished_at ? fmtDate(wf.value.finished_at) : '—', mono: true }
  ]
})

const targetSegmentSummary = (cal) => (cal.is_segmented ? `${cal.seg_split_by} segmented` : 'Single model')
const goToTraining = (cal) => router.push({ name: 'jobs_detail', params: { kind: 'training', run_id: cal.run_id } })
const goToForecast = (fr) => router.push({ name: 'jobs_detail', params: { kind: 'forecast', run_id: fr.run_id } })

// ── Credit Results tab ────────────────────────────────────────────────────────
const analysisParamRows = computed(() => {
  const a = wf.value?.analysis
  if (!a) return []
  return [
    { k: 'Exposure (EAD)', v: a.exposure != null ? a.exposure.toLocaleString() : '—' },
    { k: 'Discount rate', v: a.discount_rate != null ? (a.discount_rate * 100).toFixed(2) + '%' : '—' },
    { k: 'Lifetime horizon', v: a.lifetime_horizon != null ? `${a.lifetime_horizon} years` : '—' },
    { k: 'Curve', v: a.curve ?? '—' }
  ]
})
const analysisResultsFetchPage = (params) => creditRiskAPI.getRunResults(wf.value.analysis.run_id, params)
const analysisResultsFetchDistinct = (col) => creditRiskAPI.getRunResultsDistinct(wf.value.analysis.run_id, col)

const creditScenario = ref('All')
const creditExternalFilters = computed(() => {
  if (creditScenario.value === 'All') return {}
  return { scenario: { mode: 'in', value: [creditScenario.value] } }
})

const TARGET_COLS = [
  { label: 'TARGET' },
  { label: 'ALGORITHM' },
  { label: 'SEGMENTATION' },
  { label: 'TRAINING' },
  { label: 'FORECAST' },
  { label: 'FINISHED' },
]

// ── actions ───────────────────────────────────────────────────────────────────
const cancelWorkflow = async () => {
  actionBusy.value = true
  try {
    await workflowsAPI.cancel(runId.value)
    await fetchWorkflow()
    stopPolling()
    toast.add({ severity: 'warn', summary: 'Workflow cancelled', life: 2500 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Cancel failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    actionBusy.value = false
  }
}
const rerunWorkflow = async () => {
  actionBusy.value = true
  try {
    const { data } = await workflowsAPI.rerun(runId.value)
    toast.add({ severity: 'success', summary: 'Re-run queued', life: 2500 })
    router.push({ name: 'jobs_workflow', params: { run_id: data.run_id } })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Re-run failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    actionBusy.value = false
  }
}
const confirmDelete = () => {
  confirm.require({
    message: 'Delete this workflow and all its runs? This cannot be undone.',
    header: 'Delete workflow',
    icon: 'pi pi-exclamation-triangle',
    acceptClass: 'p-button-danger',
    acceptLabel: 'Delete',
    accept: async () => {
      actionBusy.value = true
      try {
        const res = await workflowsAPI.delete(runId.value)
        if (res.status < 300) {
          toast.add({ severity: 'success', summary: 'Workflow deleted', life: 2000 })
          router.push({ name: 'jobs_history' })
          return
        }
        toast.add({ severity: 'error', summary: 'Cannot delete', detail: res.data?.error ?? 'This workflow has an active run.', life: 5000 })
      } catch (e) {
        toast.add({ severity: 'error', summary: 'Delete failed', detail: e?.response?.data?.error ?? e.message, life: 5000 })
      } finally {
        actionBusy.value = false
      }
    }
  })
}
</script>

<template>
  <div>
    <div v-if="loading && !wf" class="loading-state">
      <i class="pi pi-spin pi-spinner" />
    </div>

    <template v-else-if="wf">
      <a class="back-link" @click="router.push({ name: 'jobs_history' })">
        <i class="pi pi-arrow-left" /> Job history
      </a>

      <div class="job-header">
        <div class="job-header-text">
          <div class="job-status-line">
            <span class="status-dot" :style="{ backgroundColor: statusMeta.dot }" />
            <span class="status-label" :style="{ color: statusMeta.text }">{{ statusMeta.label }}</span>
            <span class="font-mono job-duration">· {{ duration(wf.started_at, wf.finished_at, wf.status) }}</span>
            <span class="type-tag">WORKFLOW</span>
          </div>
          <h1>{{ wf.name }}</h1>
        </div>
        <div class="job-header-actions">
          <Button v-if="wf.status === 'running' || wf.status === 'queued'"
                  label="Cancel" outlined class="btn-header" :loading="actionBusy" @click="cancelWorkflow" />
          <template v-else>
            <Button label="Delete" outlined class="btn-header" :disabled="actionBusy" @click="confirmDelete" />
            <Button label="Re-run workflow" class="btn-header" :loading="actionBusy" :disabled="actionBusy" @click="rerunWorkflow" />
          </template>
        </div>
      </div>

      <div v-if="wf.error_message" class="error-banner">{{ wf.error_message }}</div>

      <nav class="tab-bar">
        <button
          v-for="t in TABS" :key="t.key" type="button"
          class="tab-btn" :class="{ 'is-active': activeTab === t.key }"
          @click="activeTab = t.key"
        >{{ t.label }}</button>
      </nav>

      <!-- Overview -->
      <div v-if="activeTab === 'overview'" class="overview-tab">
        <div class="card--emphasis run-details">
          <div class="eyebrow">RUN DETAILS</div>
          <div v-for="row in runDetailRows" :key="row.k" class="detail-row">
            <div class="detail-key">{{ row.k }}</div>
            <div class="detail-value" :class="{ 'font-mono': row.mono }">{{ row.v }}</div>
          </div>
        </div>

        <div class="panel target-panel">
          <div class="target-panel-header">
            <div>
              <div class="chart-title">Target models</div>
              <div class="target-panel-caption">{{ wf.targets.length }} targets trained and forecast in this workflow</div>
            </div>
            <div class="target-panel-hint">Click a target to open its run</div>
          </div>
          <BaseTable :columns="TARGET_COLS" :bleed="20">
            <tr v-for="t in wf.targets" :key="t.target_col" class="target-row">
              <td class="font-mono target-name" @click="goToTraining(t.calibration)">{{ t.target_col }}</td>
              <td class="font-mono">{{ t.calibration.algorithm ?? '—' }}</td>
              <td>{{ targetSegmentSummary(t.calibration) }}</td>
              <td><StatusDot :status="t.calibration.status" /></td>
              <td>
                <span v-if="t.forecast" class="target-forecast-link" @click="goToForecast(t.forecast)"><StatusDot :status="t.forecast.status" /></span>
                <span v-else class="grid-caption">Pending</span>
              </td>
              <td class="font-mono cell-mono">{{ (t.forecast?.finished_at ?? t.calibration.finished_at) ? fmtDate(t.forecast?.finished_at ?? t.calibration.finished_at) : '—' }}</td>
            </tr>
          </BaseTable>
        </div>
      </div>

      <!-- Diagnosis & Backtesting -->
      <DiagnosisBacktestingTab v-else-if="activeTab === 'diagnosis'" :targets="wf.targets" />

      <!-- Forecast -->
      <ForecastResultsTab v-else-if="activeTab === 'forecast'" :targets="wf.targets" />

      <!-- Credit Results -->
      <div v-else-if="activeTab === 'credit'" class="credit-tab">
        <div v-if="wf.analysis_skipped_reason" class="panel empty-note">
          <i class="pi pi-info-circle" />
          <p>{{ wf.analysis_skipped_reason }}</p>
        </div>
        <div v-else-if="!wf.analysis" class="panel empty-note">
          <i class="pi pi-clock" />
          <p>Credit analysis will start automatically once all forecasts finish.</p>
        </div>
        <template v-else>
          <div class="inset-strip">
            <div v-for="row in analysisParamRows" :key="row.k" class="inset-field">
              <span class="inset-label">{{ row.k }}</span>
              <span class="font-mono inset-value">{{ row.v }}</span>
            </div>
          </div>
          <div class="credit-toolbar">
            <span class="credit-toolbar-label">SCENARIO</span>
            <ScenarioChips v-model="creditScenario" />
          </div>
          <div class="panel results-panel">
            <CommonDataTable
              :key="wf.analysis.run_id"
              :columns="analysisResultColumns"
              :fetch-page="analysisResultsFetchPage"
              :fetch-distinct="analysisResultsFetchDistinct"
              :external-filters="creditExternalFilters"
              empty-message="No results yet."
            >
              <template #cell-stage="{ data }">
                <span v-if="data.stage != null" class="stage-tag" :class="`stage-tag--${data.stage}`">STAGE {{ data.stage }}</span>
                <span v-else>—</span>
              </template>
            </CommonDataTable>
          </div>
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
.loading-state { text-align: center; padding: 4rem 0; font-size: 1.5rem; color: var(--text-color-muted); }

.back-link { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-color-muted); cursor: pointer; margin-bottom: 16px; transition: color 0.15s ease; }
.back-link:hover { color: var(--ink); }
.back-link i { font-size: 11px; }

.job-header { display: flex; align-items: flex-end; gap: 16px; margin-bottom: 22px; min-width: 0; }
.job-header-text { display: flex; flex-direction: column; gap: 6px; flex: 1; min-width: 0; }
.job-status-line { display: flex; align-items: center; gap: 8px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.status-label { font-size: 11.5px; font-weight: 700; letter-spacing: 0.08em; }
.job-duration { font-size: 11.5px; color: var(--text-color-muted-2); }
.type-tag { display: inline-block; margin-left: 4px; padding: 3px 7px; font-size: 10px; font-weight: 700; letter-spacing: 0.06em; color: var(--text-color-secondary); border: 1px solid var(--surface-border-input); border-radius: 2px; }
.job-header-actions { display: flex; gap: 8px; flex-shrink: 0; }
.btn-header { height: 38px; }

.error-banner { font-size: 12.5px; color: var(--error-text-color); background: rgba(196, 51, 29, 0.08); border: 1px solid rgba(196, 51, 29, 0.2); border-radius: 2px; padding: 10px 14px; margin-bottom: 16px; }

.tab-bar { display: flex; width: 100%; border-bottom: 2px solid var(--ink); margin-bottom: 24px; flex-wrap: wrap; }
.tab-btn { padding: 10px 18px; font-size: 13.5px; font-weight: 400; color: var(--text-color-muted); background: transparent; border: none; cursor: pointer; }
.tab-btn:hover { color: var(--ink); }
.tab-btn.is-active { font-weight: 700; color: var(--ink); background: var(--yellow); }

.overview-tab { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 20px; align-items: start; }
@media (max-width: 900px) { .overview-tab { grid-template-columns: 1fr; } }
.run-details { padding: 18px 20px 8px; }
.detail-row { display: flex; gap: 12px; padding: 9px 0; border-bottom: 1px solid #F0F0F3; font-size: 13px; }
.detail-key { flex: none; width: 200px; color: var(--text-color-muted); }
.detail-value { flex: 1; line-height: 1.5; word-break: break-word; }

.panel { background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 2px; }
.target-panel { padding: 18px 20px; min-width: 0; }
.target-table-scroll { overflow-x: auto; }
.chart-title { font-size: 13.5px; font-weight: 700; }
.target-panel-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.target-panel-caption { font-size: 12px; color: var(--text-color-muted-2); margin-top: 3px; }
.target-panel-hint { font-size: 11.5px; color: var(--text-color-muted-2); font-style: italic; flex-shrink: 0; margin-left: 16px; }

.target-name { cursor: pointer; font-weight: 600; }
.target-name:hover { color: var(--text-color-secondary); text-decoration: underline; }
.target-forecast-link { cursor: pointer; }
.grid-caption { font-size: 12px; color: var(--text-color-muted-2); }
.cell-mono { font-size: 11.5px; color: var(--text-color-secondary); }

.credit-tab { display: flex; flex-direction: column; gap: 16px; }
.inset-strip { display: flex; flex-wrap: wrap; gap: 22px; background: var(--surface-inset); border-radius: 2px; padding: 12px 16px; }
.inset-field { display: flex; flex-direction: column; gap: 2px; }
.inset-label { font-size: 10.5px; color: var(--text-color-muted); text-transform: uppercase; letter-spacing: 0.06em; }
.inset-value { font-size: 13px; font-weight: 600; }
.results-panel { overflow: hidden; }
.credit-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.credit-toolbar-label { font-size: 11px; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; color: var(--text-color-muted); }

.empty-note { text-align: center; color: var(--text-color-muted); padding: 32px 20px; }
.empty-note i { font-size: 22px; display: block; margin-bottom: 8px; opacity: 0.6; }
.empty-note p { margin: 0; font-size: 13px; }

.stage-tag { display: inline-block; padding: 3px 8px; font-size: 10px; font-weight: 600; letter-spacing: 0.04em; border-radius: 2px; font-family: 'IBM Plex Mono', monospace; }
.stage-tag--1 { background: #FFFFFF; color: var(--text-color-secondary); border: 1px solid var(--surface-border-input); }
.stage-tag--2 { background: var(--ink); color: var(--yellow); }
.stage-tag--3 { background: var(--error-color); color: #fff; }
</style>

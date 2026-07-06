<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useConfirm } from 'primevue/useconfirm'
import { useToast } from 'primevue/usetoast'

import jobsAPI, { KIND } from '@/api/jobs'
import { fmtDate, duration } from '@/utils/datetime'
import CommonDataTable from '@/components/Table/CommonDataTable.vue'
import RunDetailsCard from './parts/RunDetailsCard.vue'
import LogsPanel from './parts/LogsPanel.vue'
import SegmentModelsPanel from './parts/SegmentModelsPanel.vue'
import { forecastResultColumns, analysisResultColumns } from './parts/resultColumns.js'

const route = useRoute()
const router = useRouter()
const confirm = useConfirm()
const toast = useToast()

const kind = computed(() => route.params.kind)
const runId = computed(() => route.params.run_id)

const job = ref(null)
const loading = ref(false)
const actionBusy = ref(false)

const fetchJob = async () => {
  try {
    job.value = await jobsAPI.getJob(kind.value, runId.value)
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load run', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  }
}

let pollTimer = null
const isLive = () => job.value?.status === 'running' || job.value?.status === 'queued'
const startPolling = () => { if (!pollTimer) pollTimer = setInterval(fetchJob, 3000) }
const stopPolling = () => { clearInterval(pollTimer); pollTimer = null }

onMounted(async () => {
  loading.value = true
  await fetchJob()
  loading.value = false
  if (isLive()) startPolling()
})
onUnmounted(stopPolling)

watch(() => job.value?.status, (s) => { if (s === 'running' || s === 'queued') startPolling(); else stopPolling() })
watch([kind, runId], async () => { stopPolling(); job.value = null; loading.value = true; await fetchJob(); loading.value = false; if (isLive()) startPolling() })

const typeLabel = computed(() => ({ [KIND.TRAINING]: 'TRAINING', [KIND.FORECAST]: 'FORECAST', [KIND.ANALYSIS]: 'ANALYSIS' }[kind.value]))

const STATUS_META = {
  success: { dot: 'var(--success-color)', text: 'var(--success-text-color)', label: 'SUCCESS' },
  failed: { dot: 'var(--error-color)', text: 'var(--error-text-color)', label: 'FAILED' },
  running: { dot: 'var(--running-color)', text: 'var(--running-text-color)', label: 'RUNNING' },
  queued: { dot: 'var(--queued-color)', text: 'var(--queued-text-color)', label: 'QUEUED' }
}
const statusMeta = computed(() => STATUS_META[job.value?.status] || STATUS_META.queued)

const runDetailRows = computed(() => {
  if (!job.value) return []
  const r = job.value.raw
  if (kind.value === KIND.TRAINING) {
    const rows = [
      { k: 'Job ID', v: r.run_id, mono: true },
      { k: 'Type', v: 'Training' },
      { k: 'Algorithm', v: r.algorithm ?? '—', mono: true },
      { k: 'Dataset', v: r.dataset_name ?? '—', mono: true },
      { k: 'Target', v: r.target_col ?? '—', mono: true }
    ]
    if (r.is_segmented) {
      rows.push({ k: 'Split by', v: r.seg_split_by ?? '—' })
      rows.push({ k: 'Max segments', v: r.seg_max_segments ?? '—', mono: true })
    }
    rows.push({ k: 'Triggered by', v: r.triggered_by?.split('@')[0] ?? '—' })
    rows.push({ k: 'Started', v: r.started_at ? fmtDate(r.started_at) : '—', mono: true })
    rows.push({ k: 'Finished', v: r.finished_at ? fmtDate(r.finished_at) : '—', mono: true })
    return rows
  }
  if (kind.value === KIND.FORECAST) {
    return [
      { k: 'Run ID', v: r.run_id, mono: true },
      { k: 'Target', v: r.target_col ?? '—', mono: true },
      { k: 'Calibration model', v: r.config_name ?? '—' },
      { k: 'Dataset', v: r.dataset_name ?? '—', mono: true },
      { k: 'Triggered by', v: r.triggered_by?.split('@')[0] ?? '—' },
      { k: 'Created', v: r.created_at ? fmtDate(r.created_at) : '—', mono: true },
      { k: 'Started', v: r.started_at ? fmtDate(r.started_at) : '—', mono: true },
      { k: 'Finished', v: r.finished_at ? fmtDate(r.finished_at) : '—', mono: true }
    ]
  }
  // analysis (credit risk)
  const inputs = r.forecast_inputs && Object.keys(r.forecast_inputs).length
    ? Object.entries(r.forecast_inputs).map(([k, v]) => `${k}: ${v ? v.slice(0, 8) + '…' : '—'}`).join(' · ')
    : '—'
  return [
    { k: 'Run ID', v: r.run_id, mono: true },
    { k: 'Dataset', v: r.dataset_name ?? r.dataset_id ?? '—', mono: true },
    { k: 'Forecast inputs', v: inputs, mono: true },
    { k: 'Exposure (EAD)', v: r.exposure != null ? r.exposure.toLocaleString() : '—', mono: true },
    { k: 'Discount rate', v: r.discount_rate != null ? (r.discount_rate * 100).toFixed(2) + '%' : '—', mono: true },
    { k: 'Lifetime horizon', v: r.lifetime_horizon != null ? `${r.lifetime_horizon} years` : '—' },
    { k: 'Triggered by', v: r.triggered_by?.split('@')[0] ?? '—' },
    { k: 'Created', v: r.created_at ? fmtDate(r.created_at) : '—', mono: true },
    { k: 'Started', v: r.started_at ? fmtDate(r.started_at) : '—', mono: true },
    { k: 'Finished', v: r.finished_at ? fmtDate(r.finished_at) : '—', mono: true }
  ]
})

// ── analysis/forecast Results tab column defs (shared with WorkflowDetail.vue) ─
const resultColumns = computed(() => (kind.value === KIND.FORECAST ? forecastResultColumns : analysisResultColumns))
const resultsFetchPage = (params) => jobsAPI.resultsFetchPage(kind.value, runId.value, params)
const resultsFetchDistinct = (col) => jobsAPI.resultsFetchDistinct(kind.value, runId.value, col)

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'results', label: 'Results' }
]
const activeTab = computed({
  get: () => TABS.find((t) => t.key === route.query.tab)?.key || 'overview',
  set: (v) => router.replace({ query: { ...route.query, tab: v } })
})
const resultsDisabled = computed(() => job.value?.status !== 'success')

// ── actions ───────────────────────────────────────────────────────────────────
const cancelJob = async () => {
  actionBusy.value = true
  try {
    await jobsAPI.cancelJob(kind.value, runId.value)
    await fetchJob()
    stopPolling()
    toast.add({ severity: 'warn', summary: 'Run cancelled', life: 2500 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Cancel failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    actionBusy.value = false
  }
}
const rerunJob = async () => {
  actionBusy.value = true
  try {
    await jobsAPI.rerunJob(kind.value, runId.value)
    await fetchJob()
    startPolling()
    toast.add({ severity: 'info', summary: 'Re-run queued', life: 2500 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Re-run failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    actionBusy.value = false
  }
}
const confirmDelete = () => {
  confirm.require({
    message: 'Delete this run? This cannot be undone.',
    header: 'Delete run',
    icon: 'pi pi-exclamation-triangle',
    acceptClass: 'p-button-danger',
    acceptLabel: 'Delete',
    accept: async () => {
      actionBusy.value = true
      try {
        const res = await jobsAPI.deleteJob(kind.value, runId.value)
        if (res.status < 300) {
          toast.add({ severity: 'success', summary: 'Run deleted', life: 2000 })
          router.push({ name: 'jobs_history' })
          return
        }
        toast.add({ severity: 'error', summary: 'Cannot delete', detail: res.data?.error ?? 'This run is referenced elsewhere.', life: 5000 })
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
    <div v-if="loading && !job" class="loading-state">
      <i class="pi pi-spin pi-spinner" />
    </div>

    <template v-else-if="job">
      <a class="back-link" @click="router.push({ name: 'jobs_history' })">
        <i class="pi pi-arrow-left" /> Job history
      </a>

      <div class="job-header">
        <div class="job-header-text">
          <div class="job-status-line">
            <span class="status-dot" :style="{ backgroundColor: statusMeta.dot }" />
            <span class="status-label" :style="{ color: statusMeta.text }">{{ statusMeta.label }}</span>
            <span class="font-mono job-duration">· {{ duration(job.started_at, job.finished_at, job.status) }}</span>
            <span class="type-tag">{{ typeLabel }}</span>
          </div>
          <h1>{{ job.name }}</h1>
          <a v-if="job.raw.workflow_run_uuid" class="workflow-breadcrumb" @click="router.push({ name: 'jobs_workflow', params: { run_id: job.raw.workflow_run_uuid } })">
            Part of a workflow &rarr;
          </a>
        </div>
        <div class="job-header-actions">
          <Button
            v-if="job.status === 'running' || job.status === 'queued'"
            label="Cancel"
            outlined
            class="btn-header"
            :loading="actionBusy"
            @click="cancelJob"
          />
          <template v-else-if="job.raw.workflow_run_id">
            <span class="grid-caption">Re-run/Delete this run from its workflow</span>
          </template>
          <template v-else>
            <Button label="Delete" outlined class="btn-header" :disabled="actionBusy" @click="confirmDelete" />
            <Button :label="kind === KIND.TRAINING ? 'Re-run all' : 'Re-run'" class="btn-header" :loading="actionBusy" @click="rerunJob" />
          </template>
        </div>
      </div>

      <!-- Training: RUN DETAILS + Segment models (or logs if not segmented) -->
      <div v-if="kind === KIND.TRAINING" class="job-body">
        <RunDetailsCard :rows="runDetailRows" :progress="job.progress" :status="job.status" :error-message="job.raw.error_message" />
        <SegmentModelsPanel v-if="job.raw.is_segmented && job.status === 'success'" :run-id="runId" />
        <LogsPanel v-else :kind="kind" :run-id="runId" :status="job.status" />
      </div>
      <a v-if="kind === KIND.TRAINING" class="diagnostics-link" @click="router.push({ name: 'calibrate_run', params: { run_id: runId }, query: { tab: 'diagnostics' } })">
        View diagnostics &amp; backtesting &rarr;
      </a>

      <!-- Forecast / Analysis: Overview / Results tabs -->
      <template v-else>
        <nav class="tab-bar">
          <button
            v-for="t in TABS" :key="t.key" type="button"
            class="tab-btn" :class="{ 'is-active': activeTab === t.key, 'is-disabled': t.key === 'results' && resultsDisabled }"
            :disabled="t.key === 'results' && resultsDisabled"
            @click="activeTab = t.key"
          >{{ t.label }}</button>
        </nav>

        <div v-if="activeTab === 'overview'" class="job-body">
          <RunDetailsCard :rows="runDetailRows" :progress="job.progress" :status="job.status" :error-message="job.raw.error_message" :label-width="130" />
          <LogsPanel :kind="kind" :run-id="runId" :status="job.status" />
        </div>

        <div v-else class="panel results-panel">
          <CommonDataTable
            :key="runId"
            :columns="resultColumns"
            :fetch-page="resultsFetchPage"
            :fetch-distinct="resultsFetchDistinct"
            empty-message="No results yet."
          >
            <template v-if="kind === KIND.ANALYSIS" #cell-stage="{ data }">
              <span v-if="data.stage != null" class="stage-tag" :class="`stage-tag--${data.stage}`">STAGE {{ data.stage }}</span>
              <span v-else>—</span>
            </template>
          </CommonDataTable>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.loading-state { text-align: center; padding: 4rem 0; font-size: 1.5rem; color: var(--text-color-muted); }

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-color-muted);
  cursor: pointer;
  margin-bottom: 16px;
  transition: color 0.15s ease;
}
.back-link:hover { color: var(--ink); }
.back-link i { font-size: 11px; }

.job-header {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  margin-bottom: 22px;
}
.job-header-text { display: flex; flex-direction: column; gap: 6px; flex: 1; min-width: 0; }
.workflow-breadcrumb { font-size: 12px; font-weight: 600; color: var(--text-color-secondary); cursor: pointer; border-bottom: 2px solid var(--yellow); padding-bottom: 1px; width: fit-content; }
.workflow-breadcrumb:hover { color: var(--ink); }
.grid-caption { font-size: 12px; color: var(--text-color-muted-2); }
.job-status-line { display: flex; align-items: center; gap: 8px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.status-label { font-size: 11.5px; font-weight: 700; letter-spacing: 0.08em; }
.job-duration { font-size: 11.5px; color: var(--text-color-muted-2); }
.type-tag {
  display: inline-block;
  margin-left: 4px;
  padding: 3px 7px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--text-color-secondary);
  border: 1px solid var(--surface-border-input);
  border-radius: 2px;
}
.job-header-actions { display: flex; gap: 8px; flex-shrink: 0; }
.btn-header { height: 38px; }

.job-body {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 20px;
  align-items: start;
}

.diagnostics-link {
  display: inline-block;
  margin-top: 16px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-color-secondary);
  cursor: pointer;
  border-bottom: 2px solid var(--yellow);
  padding-bottom: 1px;
}
.diagnostics-link:hover { color: var(--ink); }

.tab-bar {
  display: flex;
  border-bottom: 2px solid var(--ink);
  margin-bottom: 24px;
}
.tab-btn {
  padding: 10px 18px;
  font-size: 13.5px;
  font-weight: 400;
  color: var(--text-color-muted);
  background: transparent;
  border: none;
  cursor: pointer;
}
.tab-btn:hover:not(.is-disabled) { color: var(--ink); }
.tab-btn.is-active { font-weight: 700; color: var(--ink); background: var(--yellow); }
.tab-btn.is-disabled { opacity: 0.4; cursor: not-allowed; }

.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
}
.results-panel { overflow: hidden; }

.stage-tag {
  display: inline-block;
  padding: 3px 8px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
  border-radius: 2px;
  font-family: 'IBM Plex Mono', monospace;
}
.stage-tag--1 { background: #FFFFFF; color: var(--text-color-secondary); border: 1px solid var(--surface-border-input); }
.stage-tag--2 { background: var(--ink); color: var(--yellow); }
.stage-tag--3 { background: var(--error-color); color: #fff; }
</style>

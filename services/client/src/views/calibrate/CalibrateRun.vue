<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useConfirm } from 'primevue/useconfirm'
import { useToast } from 'primevue/usetoast'
import calibrationsAPI from '@/api/calibrationsAPI'
import { getRun, statusSeverity, isTimeSeries } from './runUtils'
import { fmtDate, duration } from '@/utils/datetime'
import OverviewTab    from './runTabs/OverviewTab.vue'
import ProgressTab    from './runTabs/ProgressTab.vue'
import DiagnosticsTab from './runTabs/DiagnosticsTab.vue'
import ForecastTab    from './runTabs/ForecastTab.vue'

const route = useRoute()
const router = useRouter()
const confirm = useConfirm()
const toast = useToast()
const runId = computed(() => route.params.run_id)

const run = ref(null)
const loadRun = async () => { run.value = await getRun(runId.value) }

let pollTimer = null
const startPolling = () => {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    const fresh = await getRun(runId.value)
    run.value = fresh
    if (fresh.status !== 'running' && fresh.status !== 'queued') stopPolling()
  }, 3000)
}
const stopPolling = () => { if (pollTimer) { clearInterval(pollTimer); pollTimer = null } }

onMounted(async () => {
  await loadRun()
  if (run.value?.status === 'running' || run.value?.status === 'queued') startPolling()
})
onUnmounted(stopPolling)
watch(() => run.value?.status, (s) => {
  if (s === 'running' || s === 'queued') startPolling()
  else stopPolling()
})
watch(runId, async () => { stopPolling(); await loadRun() })

const TABS = [
  { key: 'overview',    label: 'Overview',    icon: 'pi pi-info-circle' },
  { key: 'progress',    label: 'Progress',    icon: 'pi pi-bolt' },
  { key: 'diagnostics', label: 'Diagnostics', icon: 'pi pi-chart-bar' },
  { key: 'forecast',    label: 'Backtesting', icon: 'pi pi-chart-line' }
]
const activeKey = computed({
  get: () => TABS.find(t => t.key === route.query.tab)?.key || 'overview',
  set: (v) => router.replace({ query: { ...route.query, tab: v } })
})

const diagnosticsDisabled = computed(() => run.value?.status !== 'success')
const forecastDisabled    = computed(() => run.value?.status !== 'success')
const tabDisabled = (key) =>
  (key === 'diagnostics' && diagnosticsDisabled.value) ||
  (key === 'forecast' && forecastDisabled.value)

const onRunUpdate = (next) => { run.value = next }

const cancel = async () => {
  try {
    const { data } = await calibrationsAPI.cancel(runId.value)
    run.value = { ...run.value, ...data }
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Cancel failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
    return
  }
  stopPolling()
  toast.add({ severity: 'warn', summary: 'Run cancelled', detail: run.value.run_id, life: 2500 })
}
const rerun = async () => {
  try {
    const { data } = await calibrationsAPI.recalibrate(runId.value, {})
    run.value = data
    toast.add({ severity: 'info', summary: 'Re-run queued', detail: data.run_id, life: 2500 })
    router.replace({ name: 'calibrate_run', params: { run_id: data.run_id }, query: { tab: 'progress' } })
    startPolling()
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Re-run failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  }
}
const copyRunId = () => {
  navigator.clipboard?.writeText(run.value.run_id)
  toast.add({ severity: 'info', summary: 'Copied', detail: run.value.run_id, life: 1500 })
}
const confirmDelete = () => {
  confirm.require({
    message: 'Delete this calibration run? This cannot be undone.',
    header: 'Delete run',
    icon: 'pi pi-exclamation-triangle',
    acceptClass: 'p-button-danger',
    acceptLabel: 'Delete',
    accept: doDelete,
  })
}
const doDelete = async () => {
  try {
    const res = await calibrationsAPI.delete(runId.value)
    if (res.status < 300) {
      toast.add({ severity: 'success', summary: 'Run deleted', life: 2000 })
      router.push({ name: 'calibrate_jobs' })
      return
    }
    toast.add({ severity: 'error', summary: 'Cannot delete', detail: res.data?.error ?? 'This run is referenced by forecast runs.', life: 5000 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Delete failed', detail: e?.response?.data?.error ?? e.message, life: 5000 })
  }
}

const STATUS_DOT = {
  success: '#34d399',
  running: '#facc15',
  queued:  '#60a5fa',
  failed:  '#f87171'
}
const statusDot = (s) => STATUS_DOT[s] ?? 'var(--surface-400)'
const statusLabel = (s) => ({ success: 'Success', running: 'Running', queued: 'Queued', failed: 'Failed' })[s] || s
</script>

<template>
  <div class="p-5 mx-auto" style="max-width: 1400px">
    <button class="back-link mb-3" @click="router.push({ name: 'calibrate_jobs' })">
      <i class="pi pi-arrow-left text-xs" />
      <span>All jobs</span>
    </button>

    <div v-if="!run" class="text-center py-8 text-color-secondary">
      <i class="pi pi-spin pi-spinner text-2xl block mb-2" />
      Loading run…
    </div>

    <template v-else>

    <!-- Run header -->
    <header class="run-header mb-4">
      <div class="flex flex-wrap align-items-start justify-content-between gap-3">
        <div class="flex-1 min-w-0">
          <div class="flex align-items-center gap-2 mb-2">
            <span class="status-dot-lg" :style="{ background: statusDot(run.status) }">
              <span v-if="run.status === 'running'" class="status-ping" :style="{ background: statusDot(run.status) }" />
            </span>
            <span class="text-xs uppercase tracking-wide font-medium" :style="{ color: statusDot(run.status) }">
              {{ statusLabel(run.status) }}
            </span>
            <span class="text-xs text-color-secondary">·</span>
            <span class="text-xs text-color-secondary font-mono">{{ duration(run.started_at, run.finished_at, run.status) }}</span>
          </div>

          <h1 class="text-3xl font-semibold m-0 tracking-tight">{{ run.config_name }}</h1>
        </div>

        <div class="flex gap-2 flex-shrink-0">
          <Button
            label="Cancel"
            icon="pi pi-times"
            severity="secondary"
            outlined
            size="small"
            :disabled="run.status !== 'running' && run.status !== 'queued'"
            @click="cancel"
          />
          <Button label="Re-run" icon="pi pi-refresh" size="small" @click="rerun" />
          <Button
            label="Delete"
            icon="pi pi-trash"
            severity="danger"
            outlined
            size="small"
            :disabled="run.status === 'running' || run.status === 'queued'"
            @click="confirmDelete"
          />
        </div>
      </div>

      <!-- Live progress strip (only while running) -->
      <div v-if="run.status === 'running'" class="mt-4">
        <div class="flex justify-content-between text-xs text-color-secondary mb-1">
          <span>Training</span><span class="font-mono">{{ run.progress }}%</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill" :style="{ width: run.progress + '%' }" />
        </div>
      </div>
    </header>

    <!-- Segmented tabs -->
    <nav class="tab-bar mb-4">
      <button
        v-for="t in TABS"
        :key="t.key"
        type="button"
        class="tab-btn"
        :class="{ 'is-active': activeKey === t.key, 'is-disabled': tabDisabled(t.key) }"
        :disabled="tabDisabled(t.key)"
        @click="activeKey = t.key"
      >
        <i :class="t.icon" class="text-sm" />
        <span>{{ t.label }}</span>
      </button>
    </nav>

    <!-- Tab body -->
    <div>
      <OverviewTab    v-if="activeKey === 'overview'"    :run="run" />
      <ProgressTab    v-else-if="activeKey === 'progress'"    :run="run" @update:run="onRunUpdate" />
      <DiagnosticsTab v-else-if="activeKey === 'diagnostics' && !diagnosticsDisabled" :run="run" />
      <ForecastTab    v-else-if="activeKey === 'forecast' && !forecastDisabled"        :run="run" />

      <div v-else-if="activeKey === 'diagnostics'" class="empty-state">
        <i class="pi pi-chart-bar text-3xl block mb-2 opacity-50" />
        <p class="m-0 text-color-secondary">Diagnostics will appear once the run completes successfully.</p>
      </div>
      <div v-else-if="activeKey === 'forecast'" class="empty-state">
        <i class="pi pi-chart-line text-3xl block mb-2 opacity-50" />
        <p class="m-0 text-color-secondary">
          <template v-if="run.status !== 'success'">Forecast becomes available once the run completes.</template>
          <template v-else>Forecasts are only generated for time-series algorithms.</template>
        </p>
      </div>
    </div>
    </template><!-- end v-else (run loaded) -->

    <ConfirmDialog />
  </div>
</template>

<style scoped>
.back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: 0;
  padding: 4px 0;
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
  cursor: pointer;
  transition: color 120ms ease;
}
.back-link:hover { color: var(--text-color); }

.run-header { padding: 0.5rem 0 1rem; border-bottom: 1px solid var(--surface-border); }

.separator { color: var(--surface-400); }

.run-id-copy {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: 0;
  padding: 0;
  color: var(--text-color-secondary);
  cursor: pointer;
  transition: color 120ms ease;
}
.run-id-copy:hover { color: var(--text-color); }

/* Status dot — bigger version of the table dot */
.status-dot-lg {
  position: relative;
  width: 10px; height: 10px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.status-ping {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  opacity: 0.6;
  animation: ping 1.6s cubic-bezier(0, 0, 0.2, 1) infinite;
}
@keyframes ping {
  75%, 100% { transform: scale(2.6); opacity: 0; }
}

/* Live progress */
.progress-track {
  height: 4px;
  background: var(--surface-border);
  border-radius: 999px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: var(--primary-color);
  border-radius: 999px;
  transition: width 300ms ease;
}

/* Segmented tab bar */
.tab-bar {
  display: inline-flex;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 4px;
  gap: 2px;
}
.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border: 0;
  background: transparent;
  border-radius: 8px;
  color: var(--text-color-secondary);
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease;
}
.tab-btn:hover:not(.is-disabled):not(.is-active) { color: var(--text-color); }
.tab-btn.is-active {
  background: var(--surface-100, var(--surface-ground));
  color: var(--text-color);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
}
.tab-btn.is-disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.empty-state {
  text-align: center;
  padding: 5rem 2rem;
  border: 1px dashed var(--surface-border);
  border-radius: 12px;
}
</style>

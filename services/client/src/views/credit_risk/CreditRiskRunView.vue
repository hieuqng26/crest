<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useConfirm } from 'primevue/useconfirm'
import { useToast } from 'primevue/usetoast'

import creditRiskAPI from '@/api/creditRiskAPI'
import { fmtDate, duration } from '@/utils/datetime'

const route   = useRoute()
const router  = useRouter()
const confirm = useConfirm()
const toast   = useToast()

const runId = computed(() => route.params.run_id)

// ── run data ──────────────────────────────────────────────────────────────────
const run     = ref(null)
const loading = ref(false)

const fetchRun = async () => {
  try {
    const { data } = await creditRiskAPI.getRun(runId.value)
    run.value = data
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load run', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  }
}

// ── results ───────────────────────────────────────────────────────────────────
const results        = ref([])
const resultsTotal   = ref(0)
const resultsLoading = ref(false)

const fetchResults = async () => {
  if (!run.value || run.value.status !== 'success') return
  resultsLoading.value = true
  try {
    const { data } = await creditRiskAPI.getRunResults(runId.value, 200)
    results.value      = data.rows ?? []
    resultsTotal.value = data.total ?? 0
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load results', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    resultsLoading.value = false
  }
}

// ── tabs ──────────────────────────────────────────────────────────────────────
const TABS = [
  { key: 'overview', label: 'Overview', icon: 'pi pi-info-circle' },
  { key: 'results',  label: 'Results',  icon: 'pi pi-table' },
]

const activeKey = computed({
  get: () => TABS.find(t => t.key === route.query.tab)?.key || 'overview',
  set: (v) => router.replace({ query: { ...route.query, tab: v } }),
})

const tabDisabled = (key) => key === 'results' && run.value?.status !== 'success'

// ── logs ──────────────────────────────────────────────────────────────────────
const logs       = ref([])
const search     = ref('')
const autoScroll = ref(true)
const logEl      = ref(null)
const enabled    = ref({ info: true, warn: true, error: true })

const SEVERITIES = ['info', 'warn', 'error']

const filteredLogs = computed(() => {
  const q = search.value.trim().toLowerCase()
  return logs.value.filter(l =>
    enabled.value[l.level] && (!q || l.message.toLowerCase().includes(q))
  )
})

const logCounts = computed(() => {
  const c = { info: 0, warn: 0, error: 0 }
  for (const l of logs.value) if (l.level in c) c[l.level]++
  return c
})

const fetchLogs = async () => {
  try {
    const { data } = await creditRiskAPI.getRunLogs(runId.value)
    logs.value = data
  } catch {
    // silent — logs are best-effort
  }
}

watch(filteredLogs, async () => {
  if (!autoScroll.value || !logEl.value) return
  await nextTick()
  logEl.value.scrollTop = logEl.value.scrollHeight
}, { flush: 'post' })

const copyLogs = () => {
  navigator.clipboard?.writeText(
    logs.value.map(l => `[${l.t}] ${l.level.toUpperCase()} ${l.message}`).join('\n')
  )
}

// ── polling ───────────────────────────────────────────────────────────────────
let pollTimer = null

const isLive = () => run.value?.status === 'running' || run.value?.status === 'queued'

const startPolling = () => {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    await Promise.all([fetchRun(), fetchLogs()])
    if (!isLive()) stopPolling()
  }, 3000)
}

const stopPolling = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

onMounted(async () => {
  loading.value = true
  await Promise.all([fetchRun(), fetchLogs()])
  loading.value = false
  if (isLive()) startPolling()
  else if (run.value?.status === 'success') fetchResults()
})

onUnmounted(stopPolling)

watch(() => run.value?.status, (s) => {
  if (s === 'running' || s === 'queued') startPolling()
  else { stopPolling(); fetchLogs(); if (s === 'success') fetchResults() }
})

// ── actions ───────────────────────────────────────────────────────────────────
const actionBusy = ref(false)

async function setActive() {
  actionBusy.value = true
  try {
    await creditRiskAPI.setActiveRun(runId.value)
    await fetchRun()
    toast.add({ severity: 'success', summary: 'Active run set', life: 3000 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    actionBusy.value = false
  }
}

async function rerun() {
  actionBusy.value = true
  try {
    await creditRiskAPI.rerunRun(runId.value)
    logs.value = []
    await fetchRun()
    startPolling()
    toast.add({ severity: 'info', summary: 'Rerun queued', life: 3000 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    actionBusy.value = false
  }
}

async function cancelRun() {
  actionBusy.value = true
  try {
    const { data } = await creditRiskAPI.cancelRun(runId.value)
    run.value = { ...run.value, ...data }
    stopPolling()
    toast.add({ severity: 'warn', summary: 'Run cancelled', life: 2500 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Cancel failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    actionBusy.value = false
  }
}

function confirmDelete() {
  confirm.require({
    message: 'Delete this run and all its results? This cannot be undone.',
    header: 'Delete run',
    icon: 'pi pi-exclamation-triangle',
    acceptClass: 'p-button-danger',
    acceptLabel: 'Delete',
    accept: doDelete,
  })
}

async function doDelete() {
  actionBusy.value = true
  try {
    await creditRiskAPI.deleteRun(runId.value)
    toast.add({ severity: 'success', summary: 'Run deleted', life: 2000 })
    router.push({ name: 'credit_risk_jobs' })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Delete failed', detail: e?.response?.data?.error ?? e.message, life: 5000 })
    actionBusy.value = false
  }
}

// ── helpers ───────────────────────────────────────────────────────────────────
const statusSeverity = (s) =>
  ({ queued: 'info', running: 'warning', success: 'success', failed: 'danger' }[s] ?? 'secondary')

const statusDot = {
  queued:  '#60a5fa',
  running: '#facc15',
  success: '#34d399',
  failed:  '#f87171',
}
const statusLabel = (s) => ({ success: 'Success', running: 'Running', queued: 'Queued', failed: 'Failed' })[s] || s

const levelColor = (level) =>
  ({ info: 'text-color-secondary', warn: 'text-yellow-700', error: 'text-red-500' }[level] ?? 'text-color-secondary')
</script>

<template>
  <div class="run-page">

    <div v-if="loading" class="flex justify-content-center align-items-center" style="height: 14rem">
      <i class="pi pi-spin pi-spinner text-3xl text-color-secondary" />
    </div>

    <template v-else-if="run">
      <button class="back-link mb-3" @click="router.push({ name: 'credit_risk_jobs' })">
        <i class="pi pi-arrow-left text-xs" />
        <span>All jobs</span>
      </button>

      <!-- Run header -->
      <header class="run-header mb-4">
        <div class="flex flex-wrap align-items-start justify-content-between gap-3">
          <div class="flex-1 min-w-0">
            <div class="flex align-items-center gap-2 mb-2">
              <span class="status-dot-lg" :style="{ background: statusDot[run.status] ?? 'var(--surface-400)' }">
                <span v-if="run.status === 'running'" class="status-ping" :style="{ background: statusDot[run.status] }" />
              </span>
              <span class="text-xs uppercase tracking-wide font-medium" :style="{ color: statusDot[run.status] ?? 'var(--surface-400)' }">
                {{ statusLabel(run.status) }}
              </span>
              <span v-if="run.is_active" class="text-xs text-color-secondary">·</span>
              <span v-if="run.is_active" class="text-xs font-medium" style="color:#34d399">Active</span>
              <span class="text-xs text-color-secondary">·</span>
              <span class="text-xs text-color-secondary font-mono">{{ duration(run.started_at, run.finished_at, run.status) }}</span>
            </div>

            <h1 class="text-3xl font-semibold m-0 tracking-tight">{{ run.dataset_name ?? run.run_id.slice(0, 8) }}</h1>
          </div>

          <div class="flex gap-2 flex-shrink-0">
            <Button
              label="Cancel"
              icon="pi pi-times"
              severity="secondary"
              outlined
              size="small"
              :disabled="run.status !== 'running' && run.status !== 'queued'"
              @click="cancelRun"
            />
            <Button label="Re-run" icon="pi pi-refresh" size="small" :loading="actionBusy" @click="rerun" />
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
            <span>Running</span><span class="font-mono">{{ run.progress ?? 0 }}%</span>
          </div>
          <div class="progress-track">
            <div class="progress-fill" :style="{ width: (run.progress ?? 0) + '%' }" />
          </div>
        </div>
      </header>

      <!-- Segmented tabs -->
      <nav class="tab-bar mb-4">
        <button
          v-for="t in TABS" :key="t.key" type="button"
          class="tab-btn"
          :class="{ 'is-active': activeKey === t.key, 'is-disabled': tabDisabled(t.key) }"
          :disabled="tabDisabled(t.key)"
          @click="!tabDisabled(t.key) && (activeKey = t.key)"
        >
          <i :class="t.icon" class="text-sm" />
          <span>{{ t.label }}</span>
        </button>
      </nav>

      <!-- Overview tab -->
      <div v-if="activeKey === 'overview'" class="run-body">

        <!-- Left: details + progress -->
        <div class="panel flex flex-column gap-0">
          <div class="panel-title mb-3">Run Details</div>

          <dl class="detail-list">
            <div class="detail-row">
              <dt>Status</dt>
              <dd class="flex align-items-center gap-2">
                <Tag :value="run.status" :severity="statusSeverity(run.status)" />
                <span v-if="run.is_active" class="active-badge">
                  <i class="pi pi-check-circle mr-1" />Active
                </span>
              </dd>
            </div>
            <div class="detail-row">
              <dt>Run ID</dt>
              <dd class="font-mono text-xs">{{ run.run_id }}</dd>
            </div>
            <div class="detail-row">
              <dt>Dataset</dt>
              <dd>{{ run.dataset_name ?? run.dataset_id }}</dd>
            </div>
            <div class="detail-row">
              <dt>Forecast Inputs</dt>
              <dd>
                <div v-if="run.forecast_inputs && Object.keys(run.forecast_inputs).length" class="flex flex-column gap-1">
                  <div v-for="(runId, key) in run.forecast_inputs" :key="key" class="flex align-items-center gap-2">
                    <span class="font-medium capitalize" style="min-width:9rem">{{ typeof key === 'string' ? key.replace(/_/g, ' ') : key }}</span>
                    <a
                      v-if="runId"
                      class="font-mono text-xs text-color-secondary cursor-pointer hover:text-primary"
                      style="text-decoration:none"
                      @click="router.push({ name: 'forecast_run', params: { run_id: runId } })"
                    >{{ runId.slice(0, 8) }}…</a>
                  </div>
                </div>
                <span v-else class="text-color-secondary text-sm">—</span>
              </dd>
            </div>
            <div class="detail-row">
              <dt>Exposure (EAD)</dt>
              <dd>{{ run.exposure?.toLocaleString() }}</dd>
            </div>
            <div class="detail-row">
              <dt>Discount Rate</dt>
              <dd>{{ (run.discount_rate * 100).toFixed(2) }}%</dd>
            </div>
            <div class="detail-row">
              <dt>Lifetime Horizon</dt>
              <dd>{{ run.lifetime_horizon }} years</dd>
            </div>
            <div class="detail-row">
              <dt>Triggered By</dt>
              <dd>{{ run.triggered_by?.split('@')[0] ?? '—' }}</dd>
            </div>
            <div class="detail-row">
              <dt>Created</dt>
              <dd>{{ run.created_at ? fmtDate(run.created_at) : '—' }}</dd>
            </div>
            <div class="detail-row">
              <dt>Started</dt>
              <dd>{{ run.started_at ? fmtDate(run.started_at) : '—' }}</dd>
            </div>
            <div class="detail-row" style="border-bottom:0">
              <dt>Finished</dt>
              <dd>{{ run.finished_at ? fmtDate(run.finished_at) : '—' }}</dd>
            </div>
          </dl>

          <!-- Progress -->
          <div class="section-divider" />
          <div class="panel-title mb-3">Progress</div>
          <div class="flex align-items-center justify-content-between mb-2">
            <span class="text-xs text-color-secondary flex align-items-center gap-1">
              <i v-if="run.status === 'running'" class="pi pi-spin pi-spinner" />
              <i v-else-if="run.status === 'success'" class="pi pi-check-circle text-green-400" />
              <i v-else-if="run.status === 'failed'" class="pi pi-times-circle text-red-400" />
              {{ { queued: 'Waiting in queue', running: 'Running…', success: 'Completed', failed: 'Failed' }[run.status] ?? run.status }}
            </span>
            <span class="text-sm font-mono font-semibold">{{ run.progress ?? 0 }}%</span>
          </div>
          <ProgressBar
            :value="run.progress ?? 0"
            style="height: 18px; font-size: 0.7rem"
            :class="run.status === 'failed' ? 'progress-failed' : ''"
          />

          <div v-if="run.error_message" class="error-box mt-3">
            <i class="pi pi-times-circle mr-2" />{{ run.error_message }}
          </div>

          <!-- Set Active -->
          <div v-if="run.status === 'success'" class="mt-auto pt-4 flex align-items-center justify-content-between">
            <span class="text-sm text-color-secondary">Set as active</span>
            <InputSwitch
              :modelValue="run.is_active"
              :disabled="run.is_active || actionBusy"
              v-tooltip.top="run.is_active ? 'Results shown in ECL / PD-LGD' : 'Set as active run'"
              @change="setActive"
            />
          </div>
        </div>

        <!-- Right: log viewer -->
        <div class="panel log-panel flex flex-column">
          <div class="flex flex-wrap align-items-center gap-2 mb-3">
            <span class="panel-title">Logs</span>
            <span class="text-xs text-color-secondary ml-1">{{ logs.length }} lines</span>

            <div class="flex gap-1 ml-2">
              <button
                v-for="lvl in SEVERITIES"
                :key="lvl"
                type="button"
                class="lvl-chip"
                :class="{ 'opacity-40': !enabled[lvl] }"
                @click="enabled[lvl] = !enabled[lvl]"
              >
                {{ lvl }} ({{ logCounts[lvl] }})
              </button>
            </div>

            <IconField class="flex-1 ml-2" style="min-width: 12rem">
              <InputIcon class="pi pi-search" />
              <InputText v-model="search" placeholder="Filter logs…" class="w-full" size="small" />
            </IconField>

            <div class="flex gap-1">
              <Button
                :icon="autoScroll ? 'pi pi-arrow-down' : 'pi pi-pause'"
                size="small" text rounded
                v-tooltip.top="autoScroll ? 'Auto-scroll on' : 'Auto-scroll off'"
                @click="autoScroll = !autoScroll"
              />
              <Button icon="pi pi-copy" size="small" text rounded v-tooltip.top="'Copy all'" @click="copyLogs" />
            </div>
          </div>

          <div ref="logEl" class="log-box flex-1">
            <div v-if="filteredLogs.length === 0" class="text-color-secondary text-center py-4 text-xs">
              {{ logs.length === 0 ? 'No logs yet.' : 'No log lines match your filter.' }}
            </div>
            <div v-for="(l, i) in filteredLogs" :key="i" :class="levelColor(l.level)" class="log-line">
              <span class="text-color-secondary">[{{ l.t }}]</span>
              <span class="font-bold mx-1 uppercase">{{ l.level }}</span>
              <span>{{ l.message }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Results tab -->
      <div v-if="activeKey === 'results'">
        <div class="panel overflow-hidden">
          <div class="panel-section-head flex align-items-center justify-content-between">
            <div class="text-xs uppercase font-semibold" style="letter-spacing: 0.06em">ECL Summary per Client</div>
            <div v-if="resultsTotal > 200" class="text-xs text-color-secondary">
              Showing first 200 of {{ resultsTotal.toLocaleString() }} clients
            </div>
          </div>
          <DataTable
            :value="results"
            :loading="resultsLoading"
            size="small"
            class="results-table"
            :paginator="results.length > 25"
            :rows="25"
          >
            <template #empty>
              <div class="text-center py-5 text-color-secondary text-sm">No results yet.</div>
            </template>
            <Column field="client_id" header="Client ID"  style="min-width: 9rem" />
            <Column field="scenario"  header="Scenario"   style="min-width: 9rem" />
            <Column field="year"      header="Year"        style="min-width: 6rem" />
            <Column field="stage"     header="Stage"       style="min-width: 5rem">
              <template #body="{ data }">
                <Tag v-if="data.stage != null"
                  :value="`Stage ${data.stage}`"
                  :severity="{ 1: 'success', 2: 'warning', 3: 'danger' }[data.stage] ?? 'secondary'"
                />
                <span v-else class="text-color-secondary">—</span>
              </template>
            </Column>
            <Column header="PD" style="min-width: 7rem">
              <template #body="{ data }">
                <span class="font-mono text-xs">{{ data.pd != null ? (data.pd * 100).toFixed(3) + '%' : '—' }}</span>
              </template>
            </Column>
            <Column header="LGD" style="min-width: 7rem">
              <template #body="{ data }">
                <span class="font-mono text-xs">{{ data.lgd != null ? (data.lgd * 100).toFixed(1) + '%' : '—' }}</span>
              </template>
            </Column>
            <Column header="ECL" style="min-width: 9rem">
              <template #body="{ data }">
                <span class="font-mono text-xs font-semibold">{{ data.ecl != null ? data.ecl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—' }}</span>
              </template>
            </Column>
          </DataTable>
        </div>
      </div>
    </template>

    <div v-else class="panel flex align-items-center justify-content-center gap-3" style="height: 12rem">
      <i class="pi pi-exclamation-circle text-3xl text-color-secondary" />
      <div>
        <div class="text-sm font-medium">Run not found</div>
        <Button label="Back to Jobs" text size="small" class="mt-2" @click="router.push({ name: 'credit_risk_jobs' })" />
      </div>
    </div>

    <ConfirmDialog />
  </div>
</template>

<style scoped>
.run-page {
  padding: 1.25rem 1.5rem;
  max-width: 1400px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.run-body {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 1.25rem;
  flex: 1;
  min-height: 0;
}

.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  padding: 1.25rem;
}

.log-panel {
  overflow: hidden;
}

.panel-title {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 600;
  color: var(--text-color-secondary);
}

.panel-section-head {
  padding: 0.75rem 1.25rem;
  background: var(--surface-ground);
  border-bottom: 1px solid var(--surface-border);
  color: var(--text-color-secondary);
}

/* Back link */
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

/* Run header */
.run-header { padding: 0.5rem 0 1rem; border-bottom: 1px solid var(--surface-border); }

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
@keyframes ping { 75%, 100% { transform: scale(2.6); opacity: 0; } }

/* Live progress strip */
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
  align-self: flex-start;
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
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}
.tab-btn.is-disabled { opacity: 0.4; cursor: not-allowed; }

/* Results table */
:deep(.results-table .p-datatable-thead > tr > th) {
  background: var(--surface-ground);
  color: var(--text-color-secondary);
  font-size: 0.7rem;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border: 0;
  border-bottom: 1px solid var(--surface-border);
  padding: 0.6rem 1rem;
}
:deep(.results-table .p-datatable-tbody > tr > td) {
  border: 0;
  border-bottom: 1px solid var(--surface-border);
  padding: 0.7rem 1rem;
}
:deep(.results-table .p-datatable-tbody > tr:last-child > td) { border-bottom: 0; }
:deep(.results-table .p-paginator) { border: 0; border-top: 1px solid var(--surface-border); background: transparent; }

.section-divider {
  margin: 1rem 0;
  border-top: 1px solid var(--surface-border);
}

.active-badge {
  display: inline-flex;
  align-items: center;
  font-size: 0.75rem;
  color: #34d399;
  font-weight: 500;
}

/* Detail list */
.detail-list { margin: 0; }
.detail-row {
  display: grid;
  grid-template-columns: 9rem 1fr;
  gap: 0.5rem;
  padding: 0.55rem 0;
  border-bottom: 1px solid var(--surface-border);
  font-size: 0.875rem;
  align-items: start;
}
dt { color: var(--text-color-secondary); font-size: 0.8rem; padding-top: 0.05rem; }
dd { margin: 0; word-break: break-all; }

.error-box {
  font-size: 0.8rem;
  color: #f87171;
  background: rgba(248, 113, 113, 0.08);
  border: 1px solid rgba(248, 113, 113, 0.2);
  border-radius: 8px;
  padding: 0.75rem 1rem;
}

:deep(.progress-failed .p-progressbar-value) { background: #f87171; }

/* Level chips */
.lvl-chip {
  font-size: 0.7rem;
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid var(--surface-border);
  background: var(--surface-ground);
  color: var(--text-color-secondary);
  cursor: pointer;
  transition: opacity 120ms;
}
.lvl-chip:hover { color: var(--text-color); }

/* Log viewer */
.log-box {
  background: var(--surface-ground);
  border-radius: 8px;
  padding: 0.75rem 1rem;
  overflow-y: auto;
  font-family: monospace;
  font-size: 0.75rem;
  min-height: 0;
}
.log-line { white-space: pre-wrap; word-break: break-all; line-height: 1.6; }
</style>

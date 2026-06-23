<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useConfirm } from 'primevue/useconfirm'
import { useToast } from 'primevue/usetoast'

import creditRiskAPI from '@/api/creditRiskAPI'
import { fmtDate } from '@/utils/datetime'

const router  = useRouter()
const confirm = useConfirm()
const toast   = useToast()

const runs        = ref([])
const listLoading = ref(false)
const actionBusy  = ref({})
const selectMode  = ref(false)
const selection   = ref([])
const bulkDeleting = ref(false)

const fetchRuns = async () => {
  listLoading.value = true
  try {
    const { data } = await creditRiskAPI.listRuns()
    runs.value = data ?? []
    const ids = new Set((data ?? []).map(r => r.run_id))
    selection.value = selection.value.filter(r => ids.has(r.run_id))
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    listLoading.value = false
  }
}

// ── polling ───────────────────────────────────────────────────────────────────
let pollTimer = null

const hasActive = computed(() =>
  runs.value.some(r => r.status === 'running' || r.status === 'queued')
)

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    if (!hasActive.value) { stopPolling(); return }
    await fetchRuns()
  }, 5000)
}

function stopPolling() { clearInterval(pollTimer); pollTimer = null }

async function autoSetLatest() {
  if (runs.value.some(r => r.is_active)) return
  const latest = [...runs.value]
    .filter(r => r.status === 'success')
    .sort((a, b) => new Date(b.finished_at ?? b.created_at) - new Date(a.finished_at ?? a.created_at))[0]
  if (latest) await setActive(latest, { silent: true })
}

onMounted(async () => {
  await fetchRuns()
  await autoSetLatest()
  if (hasActive.value) startPolling()
})
onUnmounted(stopPolling)

// ── filters ───────────────────────────────────────────────────────────────────
const STATUSES = [
  { key: 'all',     label: 'All',     dot: 'var(--surface-400)' },
  { key: 'running', label: 'Running', dot: '#facc15' },
  { key: 'queued',  label: 'Queued',  dot: '#60a5fa' },
  { key: 'success', label: 'Success', dot: '#34d399' },
  { key: 'failed',  label: 'Failed',  dot: '#f87171' },
]

const search        = ref('')
const activeStatus  = ref('all')
const userFilter    = ref([])
const dateRange     = ref('all')

const DATE_OPTIONS = [
  { label: 'Today',        value: '1' },
  { label: 'Last 7 days',  value: '7' },
  { label: 'Last 30 days', value: '30' },
  { label: 'All time',     value: 'all' },
]

const allUsers = computed(() => [...new Set(runs.value.map(r => r.triggered_by).filter(Boolean))])

const activeFilterCount = computed(() =>
  userFilter.value.length + (dateRange.value !== 'all' ? 1 : 0)
)

const daysAgo = (iso) => {
  if (!iso) return 0
  const s = iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? 0 : (Date.now() - d.getTime()) / 86400000
}

const preFiltered = computed(() =>
  runs.value
    .filter(r => userFilter.value.length === 0 || userFilter.value.includes(r.triggered_by))
    .filter(r => dateRange.value === 'all' || daysAgo(r.created_at) <= Number(dateRange.value))
    .filter(r => {
      const q = search.value.trim().toLowerCase()
      return !q || (r.run_id + (r.dataset_name ?? '')).toLowerCase().includes(q)
    })
)

const counts = computed(() => {
  const c = { all: preFiltered.value.length, running: 0, queued: 0, success: 0, failed: 0 }
  for (const r of preFiltered.value) if (r.status in c) c[r.status]++
  return c
})

const filtered = computed(() =>
  preFiltered.value.filter(r => activeStatus.value === 'all' || r.status === activeStatus.value)
)

const statusDot = (key) => STATUSES.find(s => s.key === key)?.dot ?? 'var(--surface-400)'

const resetFilters = () => { userFilter.value = []; dateRange.value = 'all' }

// ── per-row menu ─────────────────────────────────────────────────────────────
const menuRef   = ref(null)
const menuItems = ref([])

function showMenu(e, run) {
  menuItems.value = [
    { label: 'Open',   icon: 'pi pi-arrow-up-right', command: () => viewRun(run) },
    { label: 'Set active', icon: 'pi pi-check-circle', command: () => setActive(run), disabled: run.status !== 'success' || run.is_active },
    { label: 'Rerun',  icon: 'pi pi-refresh',         command: () => rerunRun(run), disabled: run.status === 'running' || run.status === 'queued' },
    { separator: true },
    { label: 'Cancel', icon: 'pi pi-times',           command: () => cancelRun(run), disabled: run.status !== 'running' && run.status !== 'queued' },
    { label: 'Delete', icon: 'pi pi-trash',           class: 'text-red-400', command: () => confirmDelete(run), disabled: run.status === 'running' || run.status === 'queued' },
  ]
  menuRef.value.toggle(e)
}

// ── actions ───────────────────────────────────────────────────────────────────
function viewRun(run) {
  router.push({ name: 'credit_risk_run', params: { run_id: run.run_id } })
}

async function setActive(run, { silent = false } = {}) {
  actionBusy.value[run.run_id] = true
  try {
    await creditRiskAPI.setActiveRun(run.run_id)
    await fetchRuns()
    if (!silent) toast.add({ severity: 'success', summary: 'Active run set', detail: run.dataset_name ?? run.run_id.slice(0, 8), life: 3000 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    delete actionBusy.value[run.run_id]
  }
}

async function rerunRun(run) {
  actionBusy.value[run.run_id] = true
  try {
    await creditRiskAPI.rerunRun(run.run_id)
    await fetchRuns()
    startPolling()
    toast.add({ severity: 'info', summary: 'Rerun queued', detail: run.dataset_name ?? run.run_id.slice(0, 8), life: 3000 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    delete actionBusy.value[run.run_id]
  }
}

async function cancelRun(run) {
  actionBusy.value[run.run_id] = true
  try {
    await creditRiskAPI.cancelRun(run.run_id)
    await fetchRuns()
    toast.add({ severity: 'warn', summary: 'Cancelled', detail: run.dataset_name ?? run.run_id.slice(0, 8), life: 3000 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Cancel failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    delete actionBusy.value[run.run_id]
  }
}

function confirmDelete(run) {
  confirm.require({
    message: `Delete run "${run.dataset_name ?? run.run_id.slice(0, 8)}"? This cannot be undone.`,
    header: 'Delete run',
    icon: 'pi pi-exclamation-triangle',
    acceptClass: 'p-button-danger',
    accept: () => deleteRun(run),
  })
}

async function deleteRun(run) {
  actionBusy.value[run.run_id] = true
  try {
    await creditRiskAPI.deleteRun(run.run_id)
    await fetchRuns()
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    delete actionBusy.value[run.run_id]
  }
}

function exitSelectMode() { selectMode.value = false; selection.value = [] }

function confirmBulkDelete() {
  const n = selection.value.length
  confirm.require({
    message: `Permanently delete ${n} selected run${n > 1 ? 's' : ''}? This cannot be undone.`,
    header: `Delete ${n} run${n > 1 ? 's' : ''}`,
    icon: 'pi pi-exclamation-triangle',
    acceptClass: 'p-button-danger',
    accept: bulkDelete,
  })
}

async function bulkDelete() {
  bulkDeleting.value = true
  const targets = [...selection.value]
  const results = await Promise.allSettled(targets.map(r => creditRiskAPI.deleteRun(r.run_id)))
  const failed = results.filter(r => r.status === 'rejected').length
  if (failed) {
    toast.add({ severity: 'warn', summary: `${failed} deletion${failed > 1 ? 's' : ''} failed`, life: 4000 })
  } else {
    toast.add({ severity: 'success', summary: `${targets.length} run${targets.length > 1 ? 's' : ''} deleted`, life: 3000 })
  }
  exitSelectMode()
  bulkDeleting.value = false
  await fetchRuns()
}

const filterPanel = ref(null)
</script>

<template>
  <div class="p-5 mx-auto" style="max-width: 1400px">
    <!-- Header -->
    <header class="flex align-items-end justify-content-between mb-4 flex-wrap gap-3">
      <div>
        <h1 class="text-3xl font-semibold m-0 tracking-tight">Analysis Jobs</h1>
        <p class="text-color-secondary text-sm m-0 mt-1">Credit risk analysis runs — KMV · ECL · PD/LGD.</p>
      </div>
      <Button label="New Analysis" icon="pi pi-plus" @click="router.push({ name: 'credit_risk_new' })" />
    </header>

    <!-- Toolbar -->
    <div class="flex flex-wrap align-items-center gap-3 mb-3">
      <div class="status-pills flex">
        <button
          v-for="s in STATUSES"
          :key="s.key"
          type="button"
          class="status-pill"
          :class="{ 'is-active': activeStatus === s.key }"
          @click="activeStatus = s.key"
        >
          <span class="dot" :style="{ background: s.dot }" />
          <span>{{ s.label }}</span>
          <span class="count">{{ counts[s.key] || 0 }}</span>
        </button>
      </div>

      <div class="flex align-items-center gap-2 ml-auto">
        <IconField iconPosition="left" style="width: 22rem">
          <InputIcon class="pi pi-search" />
          <InputText v-model="search" placeholder="Search by run ID or dataset…" class="w-full" />
        </IconField>
        <Button
          :label="activeFilterCount > 0 ? `Filters (${activeFilterCount})` : 'Filters'"
          icon="pi pi-sliders-h"
          severity="secondary"
          outlined
          @click="filterPanel.toggle($event)"
        />
        <Button
          :label="selectMode ? 'Cancel' : 'Select'"
          :icon="selectMode ? 'pi pi-times' : 'pi pi-check-square'"
          severity="secondary"
          :outlined="!selectMode"
          :text="selectMode"
          size="small"
          @click="selectMode ? exitSelectMode() : (selectMode = true)"
        />
      </div>
    </div>

    <!-- Filter overlay -->
    <OverlayPanel ref="filterPanel" class="w-22rem">
      <div class="flex flex-column gap-4 p-2">
        <div>
          <div class="text-xs font-semibold uppercase text-color-secondary mb-2">Date range</div>
          <Dropdown v-model="dateRange" :options="DATE_OPTIONS" optionLabel="label" optionValue="value" class="w-full" />
        </div>
        <div v-if="allUsers.length">
          <div class="text-xs font-semibold uppercase text-color-secondary mb-2">Triggered by</div>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="u in allUsers" :key="u" type="button"
              class="chip-toggle" :class="{ 'is-active': userFilter.includes(u) }"
              @click="userFilter.includes(u) ? userFilter = userFilter.filter(x => x !== u) : userFilter.push(u)"
            >{{ u.split('@')[0] }}</button>
          </div>
        </div>
        <div class="flex justify-content-end">
          <Button label="Reset" text size="small" @click="resetFilters" />
        </div>
      </div>
    </OverlayPanel>

    <div class="flex align-items-center justify-content-between mb-2">
      <span class="text-xs text-color-secondary">Showing {{ filtered.length }} of {{ runs.length }} runs</span>
      <Transition name="fade-up">
        <div v-if="selection.length" class="flex align-items-center gap-2">
          <span class="text-xs text-color-secondary">{{ selection.length }} selected</span>
          <Button
            icon="pi pi-trash"
            label="Delete selected"
            severity="danger"
            size="small"
            outlined
            :loading="bulkDeleting"
            @click="confirmBulkDelete"
          />
        </div>
      </Transition>
    </div>

    <!-- Table -->
    <div class="surface-card border-round overflow-hidden shadow-1">
      <DataTable
        :value="filtered"
        v-model:selection="selection"
        :selectionMode="selectMode ? 'multiple' : undefined"
        :isRowSelectable="row => row.data.status !== 'running' && row.data.status !== 'queued'"
        dataKey="run_id"
        size="small"
        :loading="listLoading"
        :paginator="filtered.length > 15"
        :rows="15"
        rowHover
        class="jobs-table"
        sortField="created_at"
        :sortOrder="-1"
        @row-click="(e) => !selectMode && viewRun(e.data)"
      >
        <template #empty>
          <div class="text-center py-6 text-color-secondary">
            <i class="pi pi-inbox text-3xl block mb-2 opacity-50" />
            <p class="m-0">No analysis runs yet.</p>
            <Button label="New Analysis" icon="pi pi-plus" text size="small" class="mt-2" @click="router.push({ name: 'credit_risk_new' })" />
          </div>
        </template>

        <Column v-if="selectMode" selectionMode="multiple" style="width: 3rem" />

        <!-- Active switch -->
        <Column header="Active" style="width: 5.5rem">
          <template #body="{ data }">
            <InputSwitch
              v-if="data.status === 'success'"
              :modelValue="data.is_active"
              :disabled="data.is_active || !!actionBusy[data.run_id]"
              v-tooltip.top="data.is_active ? 'Results shown in ECL / PD-LGD' : 'Set as active'"
              @change="setActive(data)"
            />
          </template>
        </Column>

        <Column header="Run" sortField="run_id" sortable>
          <template #body="{ data }">
            <div class="flex align-items-center gap-3">
              <span class="status-dot" :style="{ background: statusDot(data.status) }">
                <span v-if="data.status === 'running'" class="status-dot-ping" :style="{ background: statusDot(data.status) }" />
              </span>
              <div class="line-height-3">
                <div class="font-medium text-sm">{{ data.dataset_name ?? '—' }}</div>
                <div class="text-xs text-color-secondary font-mono">{{ data.run_id }}</div>
              </div>
            </div>
          </template>
        </Column>

        <Column header="Forecast Inputs" style="width: 18rem">
          <template #body="{ data }">
            <div v-if="data.forecast_inputs && Object.keys(data.forecast_inputs).length" class="flex flex-column gap-1">
              <div v-for="(runId, key) in data.forecast_inputs" :key="key" class="flex align-items-center gap-2 text-xs">
                <span class="font-medium capitalize" style="min-width:9rem">{{ typeof key === 'string' ? key.replace(/_/g, ' ') : key }}</span>
                <a
                  v-if="runId"
                  class="font-mono text-color-secondary cursor-pointer hover:text-primary"
                  style="text-decoration: none"
                  @click.stop="router.push({ name: 'forecast_run', params: { run_id: runId } })"
                >{{ runId.slice(0, 8) }}…</a>
              </div>
            </div>
            <span v-else class="text-xs text-color-secondary">—</span>
          </template>
        </Column>

        <Column header="Exposure" style="width: 9rem">
          <template #body="{ data }">
            <span class="text-sm font-mono">{{ data.exposure?.toLocaleString() }}</span>
          </template>
        </Column>

        <Column header="Status" sortField="status" style="width: 8rem">
          <template #body="{ data }">
            <Tag
              :value="data.status"
              :severity="{ queued: 'info', running: 'warning', success: 'success', failed: 'danger' }[data.status] ?? 'secondary'"
            />
          </template>
        </Column>

        <Column header="Progress" style="width: 10rem">
          <template #body="{ data }">
            <div v-if="data.status === 'success'" class="text-xs text-color-secondary">Completed</div>
            <div v-else-if="data.status === 'queued'" class="text-xs text-color-secondary">Waiting…</div>
            <div v-else class="flex align-items-center gap-2">
              <div class="progress-track flex-1">
                <div class="progress-fill" :style="{ width: (data.progress ?? 0) + '%', background: data.status === 'failed' ? '#f87171' : 'var(--primary-color)' }" />
              </div>
              <span class="text-xs font-mono text-color-secondary">{{ data.progress ?? 0 }}%</span>
            </div>
          </template>
        </Column>

        <Column header="Started" sortField="started_at" sortable style="width: 9rem">
          <template #body="{ data }">
            <span class="text-sm">{{ data.started_at ? fmtDate(data.started_at) : '—' }}</span>
          </template>
        </Column>

        <Column header="Finished" sortField="finished_at" sortable style="width: 9rem">
          <template #body="{ data }">
            <span class="text-sm">{{ data.finished_at ? fmtDate(data.finished_at) : '—' }}</span>
          </template>
        </Column>

        <Column header="By" sortField="triggered_by" sortable style="width: 7rem">
          <template #body="{ data }">
            <span class="text-sm">{{ data.triggered_by ? data.triggered_by.split('@')[0] : '—' }}</span>
          </template>
        </Column>

        <Column header="" style="width: 4rem">
          <template #body="{ data }">
            <Button
              icon="pi pi-ellipsis-v"
              text rounded size="small"
              severity="secondary"
              :loading="actionBusy[data.run_id]"
              @click.stop="showMenu($event, data)"
            />
          </template>
        </Column>
      </DataTable>
    </div>

    <Menu ref="menuRef" :model="menuItems" popup />

  </div>
</template>

<style scoped>
.status-pills {
  display: inline-flex;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 999px;
  padding: 4px;
  gap: 2px;
}
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border-radius: 999px;
  border: 0;
  background: transparent;
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease;
}
.status-pill:hover { color: var(--text-color); }
.status-pill.is-active { background: var(--surface-100, var(--surface-ground)); color: var(--text-color); }
.status-pill .dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
.status-pill .count {
  font-variant-numeric: tabular-nums;
  color: var(--text-color-secondary);
  font-size: 0.75rem;
  background: var(--surface-200, var(--surface-card));
  padding: 0 6px;
  border-radius: 999px;
  min-width: 1.25rem;
  text-align: center;
}
.status-pill.is-active .count { background: var(--surface-300, var(--surface-border)); color: var(--text-color); }

:deep(.jobs-table .p-inputswitch) { transform: scale(0.85); }

.status-dot {
  position: relative;
  width: 8px; height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.status-dot-ping {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  opacity: 0.6;
  animation: ping 1.6s cubic-bezier(0, 0, 0.2, 1) infinite;
}
@keyframes ping { 75%, 100% { transform: scale(2.4); opacity: 0; } }

.progress-track { height: 4px; background: var(--surface-border); border-radius: 999px; overflow: hidden; }
.progress-fill { height: 100%; border-radius: 999px; transition: width 250ms ease; }

.chip-toggle {
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid var(--surface-border);
  background: var(--surface-ground);
  color: var(--text-color-secondary);
  font-size: 0.78rem;
  cursor: pointer;
  transition: all 120ms;
}
.chip-toggle:hover { color: var(--text-color); }
.chip-toggle.is-active { background: var(--primary-color); border-color: var(--primary-color); color: var(--primary-color-text); }

:deep(.jobs-table .p-datatable-thead > tr > th) {
  background: var(--surface-ground);
  color: var(--text-color-secondary);
  font-weight: 500;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border: 0;
  border-bottom: 1px solid var(--surface-border);
  padding: 0.6rem 1rem;
}
:deep(.jobs-table .p-datatable-tbody > tr > td) {
  border: 0;
  border-bottom: 1px solid var(--surface-border);
  padding: 0.85rem 1rem;
  cursor: pointer;
}
:deep(.jobs-table .p-datatable-tbody > tr:last-child > td) { border-bottom: 0; }
:deep(.jobs-table .p-datatable-tbody > tr:hover) { background: var(--surface-hover, rgba(255,255,255,0.03)); }
:deep(.jobs-table .p-paginator) { border: 0; border-top: 1px solid var(--surface-border); background: transparent; }
:deep(.jobs-table .p-selection-column) { padding-right: 0; }
:deep(.jobs-table .p-checkbox .p-checkbox-box) { border-color: var(--surface-400); }

.fade-up-enter-active, .fade-up-leave-active { transition: opacity 150ms ease, transform 150ms ease; }
.fade-up-enter-from, .fade-up-leave-to { opacity: 0; transform: translateY(4px); }
</style>

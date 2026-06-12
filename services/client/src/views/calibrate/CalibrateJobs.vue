<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import mockRuns from './mock/runs.json'
import { statusSeverity, duration, algorithmOf } from './runUtils'

const router = useRouter()
const toast = useToast()

const runs = ref(mockRuns.map(r => ({ ...r, algorithm: algorithmOf(r.config_name) })))

const STATUSES = [
  { key: 'all',     label: 'All',      dot: 'var(--surface-400)' },
  { key: 'running', label: 'Running',  dot: '#facc15' },
  { key: 'queued',  label: 'Queued',   dot: '#60a5fa' },
  { key: 'success', label: 'Success',  dot: '#34d399' },
  { key: 'failed',  label: 'Failed',   dot: '#f87171' }
]

const search = ref('')
const activeStatus = ref('all')
const algoFilter = ref([])
const userFilter = ref([])
const dateRange = ref('7')

const DATE_OPTIONS = [
  { label: 'Today',         value: '1' },
  { label: 'Last 7 days',   value: '7' },
  { label: 'Last 30 days',  value: '30' },
  { label: 'All time',      value: 'all' }
]

const counts = computed(() => {
  const c = { all: runs.value.length, running: 0, queued: 0, success: 0, failed: 0 }
  for (const r of runs.value) c[r.status] = (c[r.status] || 0) + 1
  return c
})

const allAlgorithms = computed(() => [...new Set(runs.value.map(r => r.algorithm))])
const allUsers      = computed(() => [...new Set(runs.value.map(r => r.triggered_by))])

const activeFilterCount = computed(() =>
  algoFilter.value.length + userFilter.value.length + (dateRange.value !== '7' ? 1 : 0)
)

const daysAgo = (iso) => {
  if (!iso) return Infinity
  const d = new Date(iso.replace(' ', 'T') + ':00Z')
  return (Date.now() - d.getTime()) / 86400000
}

const filtered = computed(() =>
  runs.value
    .filter(r => activeStatus.value === 'all' || r.status === activeStatus.value)
    .filter(r => algoFilter.value.length === 0 || algoFilter.value.includes(r.algorithm))
    .filter(r => userFilter.value.length === 0 || userFilter.value.includes(r.triggered_by))
    .filter(r => dateRange.value === 'all' || daysAgo(r.started_at) <= Number(dateRange.value))
    .filter(r => {
      const q = search.value.trim().toLowerCase()
      if (!q) return true
      return (r.run_id + r.config_name + r.dataset_name).toLowerCase().includes(q)
    })
)

const resetFilters = () => {
  algoFilter.value = []
  userFilter.value = []
  dateRange.value = '7'
}

// Actions
const openRun = (r) => router.push({ name: 'calibrate_run', params: { run_id: r.run_id }, query: { tab: 'overview' } })
const cancelRun = (r) => {
  const idx = runs.value.findIndex(x => x.run_id === r.run_id)
  if (idx < 0) return
  runs.value[idx] = { ...r, status: 'failed', finished_at: new Date().toISOString().slice(0, 16).replace('T', ' ') }
  toast.add({ severity: 'warn', summary: 'Cancelled', detail: r.run_id, life: 2500 })
}
const duplicateRun = (r) => {
  router.push({ name: 'calibrate_new', query: { config_id: 1 } })
  toast.add({ severity: 'info', summary: 'Duplicating', detail: r.config_name, life: 2000 })
}
const deleteRun = (r) => {
  runs.value = runs.value.filter(x => x.run_id !== r.run_id)
  toast.add({ severity: 'success', summary: 'Deleted', detail: r.run_id, life: 2000 })
}

// Per-row overflow menu
const menuRef = ref(null)
const menuItems = ref([])
const showMenu = (e, r) => {
  menuItems.value = [
    { label: 'Open',      icon: 'pi pi-arrow-up-right', command: () => openRun(r) },
    { label: 'Duplicate', icon: 'pi pi-copy',           command: () => duplicateRun(r) },
    { separator: true },
    { label: 'Cancel',    icon: 'pi pi-times', disabled: r.status !== 'running' && r.status !== 'queued', command: () => cancelRun(r) },
    { label: 'Delete',    icon: 'pi pi-trash', class: 'text-red-400', command: () => deleteRun(r) }
  ]
  menuRef.value.toggle(e)
}

const filterPanel = ref(null)
const toggleFilterPanel = (e) => filterPanel.value.toggle(e)

const statusDot = (key) => STATUSES.find(s => s.key === key)?.dot ?? 'var(--surface-400)'
</script>

<template>
  <div class="p-5 max-w-screen mx-auto" style="max-width: 1400px">
    <!-- Page header -->
    <header class="flex align-items-end justify-content-between mb-4 flex-wrap gap-3">
      <div>
        <h1 class="text-3xl font-semibold m-0 tracking-tight">Calibration Jobs</h1>
        <p class="text-color-secondary text-sm m-0 mt-1">Track, inspect, and re-run every model calibration.</p>
      </div>
      <Button label="New run" icon="pi pi-plus" @click="router.push({ name: 'calibrate_new' })" />
    </header>

    <!-- Toolbar: status pills + search + filters -->
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
          <InputText v-model="search" placeholder="Search by run id, config, dataset…" class="w-full" />
        </IconField>
        <Button
          :label="activeFilterCount > 0 ? `Filters (${activeFilterCount})` : 'Filters'"
          icon="pi pi-sliders-h"
          severity="secondary"
          outlined
          @click="toggleFilterPanel"
        />
      </div>
    </div>

    <!-- Filters popover -->
    <OverlayPanel ref="filterPanel" class="w-22rem">
      <div class="flex flex-column gap-4 p-2">
        <div>
          <div class="text-xs font-semibold uppercase text-color-secondary mb-2">Date range</div>
          <Dropdown
            v-model="dateRange"
            :options="DATE_OPTIONS"
            optionLabel="label"
            optionValue="value"
            class="w-full"
          />
        </div>
        <div>
          <div class="text-xs font-semibold uppercase text-color-secondary mb-2">Algorithm</div>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="a in allAlgorithms"
              :key="a"
              type="button"
              class="chip-toggle"
              :class="{ 'is-active': algoFilter.includes(a) }"
              @click="algoFilter.includes(a) ? algoFilter = algoFilter.filter(x => x !== a) : algoFilter.push(a)"
            >
              {{ a }}
            </button>
          </div>
        </div>
        <div>
          <div class="text-xs font-semibold uppercase text-color-secondary mb-2">Triggered by</div>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="u in allUsers"
              :key="u"
              type="button"
              class="chip-toggle"
              :class="{ 'is-active': userFilter.includes(u) }"
              @click="userFilter.includes(u) ? userFilter = userFilter.filter(x => x !== u) : userFilter.push(u)"
            >
              {{ u.split('@')[0] }}
            </button>
          </div>
        </div>
        <div class="flex justify-content-end">
          <Button label="Reset" text size="small" @click="resetFilters" />
        </div>
      </div>
    </OverlayPanel>

    <!-- Active filter summary -->
    <div v-if="activeFilterCount > 0" class="flex flex-wrap align-items-center gap-2 mb-3 text-xs">
      <span class="text-color-secondary">Filtered by:</span>
      <Chip v-if="dateRange !== '7'" :label="DATE_OPTIONS.find(o => o.value === dateRange)?.label" removable @remove="dateRange = '7'" />
      <Chip v-for="a in algoFilter" :key="`fa-${a}`" :label="a" removable @remove="algoFilter = algoFilter.filter(x => x !== a)" />
      <Chip v-for="u in userFilter" :key="`fu-${u}`" :label="u.split('@')[0]" removable @remove="userFilter = userFilter.filter(x => x !== u)" />
      <Button label="Reset" text size="small" @click="resetFilters" />
    </div>

    <!-- Results count -->
    <div class="text-xs text-color-secondary mb-2">
      Showing {{ filtered.length }} of {{ runs.length }} runs
    </div>

    <!-- Table -->
    <div class="border-1 surface-border border-round overflow-hidden">
      <DataTable
        :value="filtered"
        size="small"
        :paginator="filtered.length > 15"
        :rows="15"
        rowHover
        @rowClick="(e) => openRun(e.data)"
        class="jobs-table"
        sortField="started_at"
        :sortOrder="-1"
      >
        <template #empty>
          <div class="text-center py-6 text-color-secondary">
            <i class="pi pi-inbox text-3xl block mb-2 opacity-50" />
            <p class="m-0">No runs match your filters.</p>
            <Button v-if="activeFilterCount > 0 || activeStatus !== 'all'"
              label="Clear filters" text size="small"
              @click="resetFilters(); activeStatus = 'all'; search = ''" class="mt-2" />
          </div>
        </template>

        <Column header="Run" sortable sortField="config_name">
          <template #body="{ data }">
            <div class="flex align-items-center gap-3">
              <span class="status-dot" :style="{ background: statusDot(data.status) }">
                <span v-if="data.status === 'running'" class="status-dot-ping" :style="{ background: statusDot(data.status) }" />
              </span>
              <div class="line-height-3">
                <div class="font-medium">{{ data.config_name }}</div>
                <div class="text-xs text-color-secondary font-mono">{{ data.run_id }} · {{ data.algorithm }}</div>
              </div>
            </div>
          </template>
        </Column>

        <Column field="dataset_name" header="Dataset" sortable>
          <template #body="{ data }">
            <span class="text-sm">{{ data.dataset_name }}</span>
          </template>
        </Column>

        <Column header="Progress" style="width: 14rem">
          <template #body="{ data }">
            <div v-if="data.status === 'success'" class="text-xs text-color-secondary">Completed</div>
            <div v-else-if="data.status === 'queued'" class="text-xs text-color-secondary">Waiting in queue</div>
            <div v-else class="flex align-items-center gap-2">
              <div class="progress-track flex-1">
                <div
                  class="progress-fill"
                  :style="{
                    width: data.progress + '%',
                    background: data.status === 'failed' ? '#f87171' : 'var(--primary-color)'
                  }"
                />
              </div>
              <span class="text-xs font-mono w-3rem text-right text-color-secondary">{{ data.progress }}%</span>
            </div>
          </template>
        </Column>

        <Column header="Duration" sortable sortField="started_at" style="width: 8rem">
          <template #body="{ data }">
            <div class="text-sm font-mono">{{ duration(data.started_at, data.finished_at, data.status) }}</div>
            <div class="text-xs text-color-secondary">{{ data.started_at.split(' ')[0] }}</div>
          </template>
        </Column>

        <Column field="triggered_by" header="By" sortable style="width: 7rem">
          <template #body="{ data }">
            <span class="text-sm">{{ data.triggered_by.split('@')[0] }}</span>
          </template>
        </Column>

        <Column header="" style="width: 3rem">
          <template #body="{ data }">
            <Button
              icon="pi pi-ellipsis-v"
              text rounded size="small"
              severity="secondary"
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
/* Status pills */
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
.status-pill.is-active {
  background: var(--surface-100, var(--surface-ground));
  color: var(--text-color);
}
.status-pill .dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  display: inline-block;
}
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
.status-pill.is-active .count {
  background: var(--surface-300, var(--surface-border));
  color: var(--text-color);
}

/* Algorithm/user chip toggles */
.chip-toggle {
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--surface-border);
  background: transparent;
  font-size: 0.75rem;
  color: var(--text-color-secondary);
  cursor: pointer;
  transition: all 120ms ease;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.chip-toggle:hover { color: var(--text-color); border-color: var(--text-color-secondary); }
.chip-toggle.is-active {
  background: var(--primary-color);
  color: var(--primary-color-text);
  border-color: var(--primary-color);
}

/* Status dot with ping for running */
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
@keyframes ping {
  75%, 100% { transform: scale(2.4); opacity: 0; }
}

/* Progress bar */
.progress-track {
  height: 4px;
  background: var(--surface-border);
  border-radius: 999px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 250ms ease;
}

/* Table polish — kill stripes, lighter rows, padded cells */
:deep(.jobs-table) {
  --row-divider: var(--surface-border);
}
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
  border-bottom: 1px solid var(--row-divider);
  padding: 0.85rem 1rem;
}
:deep(.jobs-table .p-datatable-tbody > tr:last-child > td) {
  border-bottom: 0;
}
:deep(.jobs-table .p-datatable-tbody > tr:hover) {
  cursor: pointer;
  background: var(--surface-hover, rgba(255, 255, 255, 0.03));
}
:deep(.jobs-table .p-paginator) {
  border: 0;
  border-top: 1px solid var(--surface-border);
  background: transparent;
}
</style>

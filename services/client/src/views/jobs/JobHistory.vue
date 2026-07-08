<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import { usePolling } from '@/composables/usePolling'
import jobsAPI, { KIND } from '@/api/jobs'
import creditRiskAPI from '@/api/creditRiskAPI'
import workflowsAPI from '@/api/workflowsAPI'
import { fmtDate } from '@/utils/datetime'

import PageHeader from '@/components/ui/PageHeader.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import BaseTable from '@/views/composables/BaseTable.vue'

const router = useRouter()
const toast  = useToast()

const jobs      = ref([])
const workflows = ref([])
const loading   = ref(true)
const busy      = ref(null)

const fetchJobs = async () => {
  const [jobsList, wfRes] = await Promise.all([
    jobsAPI.listJobs(),
    workflowsAPI.list({ per_page: 200 }),
  ])
  jobs.value      = jobsList
  workflows.value = wfRes.data.items ?? []
}

const autoSetActiveAnalysisRun = async () => {
  const analysisJobs = jobs.value.filter((j) => j.kind === KIND.ANALYSIS)
  if (analysisJobs.some((j) => j.raw.is_active)) return
  const latest = analysisJobs
    .filter((j) => j.status === 'success')
    .sort((a, b) => new Date(b.finished_at ?? b.started_at ?? 0) - new Date(a.finished_at ?? a.started_at ?? 0))[0]
  if (!latest) return
  try { await creditRiskAPI.setActiveRun(latest.run_id) } catch { /* best-effort */ }
}

// `deleting` counts as active: an async workflow purge keeps the row visible
// until the backend removes it, so we must keep polling to see it disappear.
const hasActive = computed(() =>
  jobs.value.some((j) => j.status === 'running' || j.status === 'queued') ||
  workflows.value.some((w) => w.status === 'running' || w.status === 'queued' || w.status === 'deleting')
)
const poll = usePolling(fetchJobs, { interval: 5000 })

onMounted(async () => {
  loading.value = true
  await fetchJobs()
  loading.value = false
  await autoSetActiveAnalysisRun()
  if (hasActive.value) poll.start()
})
watch(hasActive, (active) => { if (active) poll.start(); else poll.stop() })

// ── Standalone jobs ───────────────────────────────────────────────────────────
const standaloneJobs = computed(() => jobs.value.filter((j) => !j.raw.workflow_run_id))

// ── Filter chips ──────────────────────────────────────────────────────────────
const TYPE_CHIPS  = ['All', 'Auto', 'Manual']
const activeType  = ref('All')
const search      = ref('')

const typeCounts = computed(() => ({
  All:    workflows.value.length + standaloneJobs.value.length,
  Auto:   workflows.value.length,
  Manual: standaloneJobs.value.length,
}))

// ── Top-level rows ────────────────────────────────────────────────────────────
const topLevelRows = computed(() => {
  const q = search.value.trim().toLowerCase()

  const wfRows = (activeType.value === 'All' || activeType.value === 'Auto')
    ? workflows.value
        .filter((w) => !q || (w.name + w.run_id).toLowerCase().includes(q))
        .map((w) => ({ type: 'workflow', key: `wf-${w.run_id}`, sortAt: w.started_at ?? w.created_at, wf: w }))
    : []

  const jobRows = (activeType.value === 'All' || activeType.value === 'Manual')
    ? standaloneJobs.value
        .filter((j) => !q || (j.name + j.ref + j.run_id).toLowerCase().includes(q))
        .map((j) => ({ type: 'job', key: `job-${j.run_id}`, sortAt: j.started_at, job: j }))
    : []

  return [...wfRows, ...jobRows].sort((a, b) => new Date(b.sortAt ?? 0) - new Date(a.sortAt ?? 0))
})

// ── Table columns (checkbox injected when select mode is on) ──────────────────
const tableColumns = computed(() => [
  ...(selectMode.value ? [{ field: 'check', label: '', width: '36px', hideHeader: true }] : []),
  { field: 'run', label: 'RUN' },
  { field: 'type', label: 'TYPE',     width: '90px' },
  { field: 'input', label: 'INPUT' },
  { field: 'status', label: 'STATUS',   width: '125px' },
  { field: 'progress', label: 'PROGRESS', width: '150px' },
  { field: 'started', label: 'STARTED',  width: '140px' },
  { field: 'finished', label: 'FINISHED', width: '140px' },
  { field: 'by', label: 'BY',       width: '70px' },
  { field: 'actions', label: '',         width: '40px', align: 'right' },
])

// Fields shared by workflow/job rows, resolved once per row so cell slots stay
// terse instead of repeating the workflow?wf:job ternary everywhere.
const rowName      = (row) => (row.type === 'workflow' ? row.wf.name : row.job.name)
const rowRunId     = (row) => (row.type === 'workflow' ? row.wf.run_id : row.job.run_id)
const rowStatus    = (row) => (row.type === 'workflow' ? row.wf.status : row.job.status)
const rowStarted   = (row) => (row.type === 'workflow' ? row.wf.started_at : row.job.started_at)
const rowFinished  = (row) => (row.type === 'workflow' ? row.wf.finished_at : row.job.finished_at)
const rowBy        = (row) => (row.type === 'workflow' ? row.wf.triggered_by : row.job.triggered_by)
const rowIsActive  = (row) =>
  (row.type === 'workflow' && row.wf.analysis_summary?.is_active) ||
  (row.type === 'job' && row.job.kind === KIND.ANALYSIS && row.job.raw.is_active)
const rowMenu      = (row) => (row.type === 'workflow' ? buildWorkflowMenu(row.wf) : buildJobMenu(row.job))

// ── Navigation ────────────────────────────────────────────────────────────────
const openJob      = (j)  => router.push({ name: 'jobs_detail', params: { kind: j.kind, run_id: j.run_id } })
const openWorkflow = (wf) => router.push({ name: 'jobs_workflow', params: { run_id: wf.run_id } })

const clickRow = (row) => {
  if (selectMode.value) { toggleSelect(row.key); return }
  row.type === 'workflow' ? openWorkflow(row.wf) : openJob(row.job)
}

// ── Progress labels ───────────────────────────────────────────────────────────
// Terminal success shows nothing here — STATUS already says it. Only labels
// that add information survive: the failure point, or the live stage.
const progressLabel = (j) =>
  j.status === 'failed' ? `Failed at ${j.progress}%` : '—'

const STAGE_LABEL = { training: 'Training', forecast: 'Forecasting', analysis: 'Analyzing' }
const workflowProgressLabel = (wf) => {
  if (wf.status === 'success' || wf.status === 'failed') return '—'
  return STAGE_LABEL[wf.current_stage] ?? '—'
}
const workflowRef = (wf) => (wf.targets ?? []).map((t) => t.target_col).join(', ') || '—'

// ── Multi-select ──────────────────────────────────────────────────────────────
const selectMode   = ref(false)
const selection    = ref(new Set())
const confirmingBulkDelete = ref(false)

const toggleSelect    = (key) => { selection.value.has(key) ? selection.value.delete(key) : selection.value.add(key) }
const isSelected      = (key) => selection.value.has(key)
const toggleSelectAll = () => {
  selection.value = selection.value.size === topLevelRows.value.length
    ? new Set()
    : new Set(topLevelRows.value.map((r) => r.key))
}
const allSelected  = computed(() => selection.value.size > 0 && selection.value.size === topLevelRows.value.length)
const exitSelectMode = () => { selectMode.value = false; selection.value = new Set(); confirmingBulkDelete.value = false }

const bulkDelete = async () => {
  const rows = topLevelRows.value.filter((r) => selection.value.has(r.key))
  try {
    const results = await Promise.all(rows.map((r) =>
      r.type === 'workflow'
        ? workflowsAPI.delete(r.wf.run_id)   // 202 async, or 409 (resolves, not thrown)
        : jobsAPI.deleteJob(r.job.kind, r.job.run_id)
    ))
    const blocked = results.filter((res) => res?.status === 409).length
    const accepted = rows.length - blocked
    if (accepted) toast.add({ severity: 'success', summary: 'Deleting', detail: `${accepted} run${accepted !== 1 ? 's' : ''} queued for deletion`, life: 3000 })
    if (blocked)  toast.add({ severity: 'warn', summary: 'Some blocked', detail: `${blocked} run${blocked !== 1 ? 's' : ''} could not be deleted (dependencies)`, life: 5000 })
    await fetchJobs()
    poll.start()   // workflow purges are async — keep polling until rows clear
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Delete failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  }
  exitSelectMode()
}

// ── Context menu ──────────────────────────────────────────────────────────────
const menuRef   = ref(null)
const menuItems = ref([])

function openMenu(e, items) {
  e.stopPropagation()
  menuItems.value = items
  menuRef.value.toggle(e)
}

function buildWorkflowMenu(wf) {
  const active   = wf.status === 'running' || wf.status === 'queued'
  const deleting = wf.status === 'deleting'
  const items    = []

  if (wf.analysis_summary?.status === 'success') {
    items.push({
      label:    wf.analysis_summary?.is_active ? 'Analysis active ✓' : 'Set analysis active',
      icon:     'pi pi-check-circle',
      disabled: !!wf.analysis_summary?.is_active,
      command:  () => activateWorkflow(wf),
    })
  }
  items.push({ label: 'View', icon: 'pi pi-eye', command: () => openWorkflow(wf) })
  if (!active && !deleting) items.push({ label: 'Re-run', icon: 'pi pi-refresh', command: () => rerunWorkflow(wf) })
  if (active)  items.push({ label: 'Cancel',  icon: 'pi pi-times-circle', command: () => cancelWorkflow(wf) })
  items.push({ separator: true })
  items.push({ label: deleting ? 'Deleting…' : 'Delete', icon: 'pi pi-trash', class: 'menu-item-danger', disabled: deleting, command: () => deleteWorkflow(wf) })
  return items
}

function buildJobMenu(j) {
  const active = j.status === 'running' || j.status === 'queued'
  const items  = []

  if (j.kind === KIND.ANALYSIS && j.status === 'success') {
    items.push({
      label:    j.raw.is_active ? 'Analysis active ✓' : 'Set analysis active',
      icon:     'pi pi-check-circle',
      disabled: !!j.raw.is_active,
      command:  () => activateJob(j),
    })
  }
  items.push({ label: 'View', icon: 'pi pi-eye', command: () => openJob(j) })
  if (!active) items.push({ label: 'Re-run', icon: 'pi pi-refresh', command: () => rerunJob(j) })
  if (active)  items.push({ label: 'Cancel',  icon: 'pi pi-times-circle', command: () => cancelJob(j) })
  items.push({ separator: true })
  items.push({ label: 'Delete', icon: 'pi pi-trash', class: 'menu-item-danger', command: () => deleteJob(j) })
  return items
}

// ── Action helpers ────────────────────────────────────────────────────────────
async function activateWorkflow(wf) {
  busy.value = wf.run_id
  try {
    await workflowsAPI.activate(wf.run_id)
    toast.add({ severity: 'success', summary: 'Activated', detail: 'Analysis run set as active', life: 3000 })
    await fetchJobs()
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Error', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally { busy.value = null }
}

async function rerunWorkflow(wf) {
  busy.value = wf.run_id
  try {
    const { data } = await workflowsAPI.rerun(wf.run_id)
    toast.add({ severity: 'success', summary: 'Re-running', detail: data.name, life: 3000 })
    await fetchJobs()
    router.push({ name: 'jobs_workflow', params: { run_id: data.run_id } })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Error', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally { busy.value = null }
}

async function cancelWorkflow(wf) {
  busy.value = wf.run_id
  try {
    await workflowsAPI.cancel(wf.run_id)
    toast.add({ severity: 'info', summary: 'Cancelled', detail: wf.name, life: 3000 })
    await fetchJobs()
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Error', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally { busy.value = null }
}

async function deleteWorkflow(wf) {
  busy.value = wf.run_id
  try {
    const res = await workflowsAPI.delete(wf.run_id)
    if (res.status === 409) {
      toast.add({ severity: 'warn', summary: 'Cannot delete', detail: res.data?.error, life: 5000 })
    } else {
      // 202 Accepted: purge runs in the background. The row now reports the
      // `deleting` status; refetch to show it and keep polling until it's gone.
      toast.add({ severity: 'info', summary: 'Deleting…', detail: wf.name, life: 3000 })
      await fetchJobs()
      poll.start()
    }
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Error', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally { busy.value = null }
}

async function activateJob(j) {
  busy.value = j.run_id
  try {
    await creditRiskAPI.setActiveRun(j.run_id)
    toast.add({ severity: 'success', summary: 'Activated', detail: 'Analysis run set as active', life: 3000 })
    await fetchJobs()
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Error', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally { busy.value = null }
}

async function rerunJob(j) {
  busy.value = j.run_id
  try {
    await jobsAPI.rerunJob(j.kind, j.run_id)
    toast.add({ severity: 'success', summary: 'Re-running', detail: j.name, life: 3000 })
    await fetchJobs()
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Error', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally { busy.value = null }
}

async function cancelJob(j) {
  busy.value = j.run_id
  try {
    await jobsAPI.cancelJob(j.kind, j.run_id)
    toast.add({ severity: 'info', summary: 'Cancelled', detail: j.name, life: 3000 })
    await fetchJobs()
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Error', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally { busy.value = null }
}

async function deleteJob(j) {
  busy.value = j.run_id
  try {
    const res = await jobsAPI.deleteJob(j.kind, j.run_id)
    if (res?.status === 409) {
      toast.add({ severity: 'warn', summary: 'Cannot delete', detail: res.data?.error, life: 5000 })
    } else {
      toast.add({ severity: 'success', summary: 'Deleted', detail: j.name, life: 3000 })
      await fetchJobs()
    }
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Error', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally { busy.value = null }
}
</script>

<template>
  <div>
    <PageHeader title="Job History" subtitle="Every workflow, training, forecast and analysis run">
      <template #actions>
        <Button class="btn-new-model" @click="router.push({ name: 'model_new' })">
          <span class="btn-plus">+</span>
          <span>New Model</span>
        </Button>
      </template>
    </PageHeader>

    <!-- Toolbar -->
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

      <template v-if="!selectMode">
        <Button label="Select" icon="pi pi-check-square" size="small" severity="secondary" text @click="selectMode = true" />
      </template>
      <template v-else>
        <span class="text-sm text-color-secondary">{{ selection.size }} selected</span>
        <template v-if="!confirmingBulkDelete">
          <Button label="Delete selected" icon="pi pi-trash" size="small" severity="danger"
            :disabled="selection.size === 0" @click="confirmingBulkDelete = true" />
        </template>
        <template v-else>
          <span class="text-sm font-medium" style="color: var(--red-500, #ef4444)">Delete {{ selection.size }} run{{ selection.size !== 1 ? 's' : '' }}?</span>
          <Button label="Confirm" icon="pi pi-check" size="small" severity="danger" @click="bulkDelete" />
          <Button label="Cancel" size="small" severity="secondary" text @click="confirmingBulkDelete = false" />
        </template>
        <Button icon="pi pi-times" size="small" severity="secondary" text rounded @click="exitSelectMode" v-tooltip.top="'Exit select mode'" />
      </template>
    </div>

    <div class="showing-line">Showing {{ topLevelRows.length }} of {{ workflows.length + standaloneJobs.length }} runs</div>

    <div class="panel">
      <BaseTable
        :columns="tableColumns"
        :value="topLevelRows"
        dataKey="key"
        :rowClass="(row) => ({
          'jh-row': true,
          'jh-row--workflow': row.type === 'workflow',
          'jh-row--selected': isSelected(row.key),
        })"
        @row-click="clickRow"
      >
        <!-- Select-all checkbox header -->
        <template v-if="selectMode" #header-check>
          <span class="ey-cb" :class="{ 'is-checked': allSelected }" @click.stop="toggleSelectAll">
            <i v-if="allSelected" class="pi pi-check ey-cb-icon" />
          </span>
        </template>

        <template #empty>
          <EmptyState v-if="!loading">No runs match your filters.</EmptyState>
        </template>

        <!-- Select checkbox -->
        <template #cell-check="{ row }">
          <span class="td-check" @click.stop="toggleSelect(row.key)">
            <span class="ey-cb" :class="{ 'is-checked': isSelected(row.key) }">
              <i v-if="isSelected(row.key)" class="pi pi-check ey-cb-icon" />
            </span>
          </span>
        </template>

        <!-- RUN: name + uuid -->
        <template #cell-run="{ row }">
          <div class="run-name">
            <span class="run-name-text">{{ rowName(row) }}</span>
            <span
              v-if="rowIsActive(row)"
              v-tooltip.top="'Feeds the IFRS 9 ECL, PD/LGD and Transitions pages'"
              class="active-badge"
            >ACTIVE</span>
          </div>
          <div class="run-id font-mono">{{ rowRunId(row) }}</div>
        </template>

        <!-- TYPE -->
        <template #cell-type="{ row }">
          <span class="type-tag" :class="row.type === 'workflow' ? 'type-tag--auto' : ''">
            {{ row.type === 'workflow' ? 'AUTO' : 'MANUAL' }}
          </span>
        </template>

        <!-- INPUT -->
        <template #cell-input="{ row }">
          <span class="font-mono cell-secondary cell-truncate" :title="row.type === 'workflow' ? workflowRef(row.wf) : row.job.ref">{{ row.type === 'workflow' ? workflowRef(row.wf) : row.job.ref }}</span>
        </template>

        <!-- STATUS -->
        <template #cell-status="{ row }">
          <StatusDot :status="rowStatus(row)" />
        </template>

        <!-- PROGRESS -->
        <template #cell-progress="{ row }">
          <template v-if="row.type === 'workflow'">
            <div v-if="row.wf.status === 'running'" class="progress-row">
              <div class="progress-track"><div class="progress-fill" style="width:50%" /></div>
            </div>
            <div v-else-if="row.wf.status === 'deleting'" class="progress-row">
              <div class="progress-track"><div class="progress-fill progress-fill--deleting" /></div>
            </div>
            <span v-else class="progress-label">{{ workflowProgressLabel(row.wf) }}</span>
          </template>
          <template v-else>
            <div v-if="row.job.status === 'running'" class="progress-row">
              <div class="progress-track"><div class="progress-fill" :style="{ width: row.job.progress + '%' }" /></div>
              <span class="font-mono progress-pct">{{ row.job.progress }}%</span>
            </div>
            <span v-else class="progress-label">{{ progressLabel(row.job) }}</span>
          </template>
        </template>

        <!-- STARTED -->
        <template #cell-started="{ row }">
          <span class="font-mono cell-secondary">{{ rowStarted(row) ? fmtDate(rowStarted(row)) : '—' }}</span>
        </template>

        <!-- FINISHED -->
        <template #cell-finished="{ row }">
          <span class="font-mono cell-secondary">{{ rowFinished(row) ? fmtDate(rowFinished(row)) : '—' }}</span>
        </template>

        <!-- BY -->
        <template #cell-by="{ row }">
          <span class="cell-secondary">{{ rowBy(row)?.split('@')[0] ?? '—' }}</span>
        </template>

        <!-- ACTIONS -->
        <template #cell-actions="{ row }">
          <span @click.stop>
            <button
              class="action-btn"
              :class="{ 'is-busy': busy === rowRunId(row) }"
              aria-label="Run actions"
              @click="openMenu($event, rowMenu(row))"
            >
              <i class="pi pi-ellipsis-v" />
            </button>
          </span>
        </template>
      </BaseTable>
    </div>

    <!-- Shared context menu -->
    <Menu ref="menuRef" :model="menuItems" popup>
      <template #item="{ item, props: p }">
        <a v-bind="p.action" :class="['menu-item', item.class]">
          <i :class="item.icon" />
          <span>{{ item.label }}</span>
        </a>
      </template>
    </Menu>
  </div>
</template>

<style scoped>
.btn-new-model { height: 38px; display: flex; align-items: center; gap: 8px; padding: 0 18px; }
.btn-plus { color: var(--yellow); font-weight: 700; }

.toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
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
.type-chip:focus-visible { outline: none; box-shadow: 0 0 0 2px var(--yellow); }
.type-chip.is-active { background: var(--ink); color: #fff; border-color: var(--ink); }
.chip-count { color: var(--text-color-muted-2); }
.type-chip.is-active .chip-count { color: var(--yellow); }

.search-input { width: 280px; height: 36px; }
.showing-line { font-size: 12px; color: var(--text-color-muted); margin-bottom: 8px; }

.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
  padding: 0 16px 4px;
}

/* Row variants — these target the <tr> rendered by BaseTable, so they live in
   the unscoped block below, not here. */

/* Checkbox cell */
.td-check { width: 36px; }
.ey-cb {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: 1.5px solid var(--surface-border-input);
  border-radius: 2px;
  background: #fff;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
}
.ey-cb.is-checked { background: var(--yellow, #FFE600); border-color: var(--yellow, #FFE600); }
.ey-cb-icon { font-size: 9px; color: var(--ink, #1A1A24); font-weight: 900; }

/* Run name cell */
.run-name { display: flex; align-items: center; gap: 6px; }
.run-name-text { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 280px; }
.run-id { font-size: 10.5px; color: var(--text-color-muted-2); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 280px; }

.active-badge {
  display: inline-block;
  padding: 2px 6px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
  border-radius: 2px;
  background: var(--yellow);
  color: var(--ink);
  flex-shrink: 0;
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
.type-tag--auto { background: var(--ink); color: var(--yellow); border-color: var(--ink); }

.cell-secondary { font-size: 11.5px; color: var(--text-color-secondary); }
.cell-truncate { display: inline-block; max-width: 260px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; vertical-align: bottom; }

.progress-row { display: flex; align-items: center; gap: 8px; }
.progress-track { flex: 1; min-width: 60px; height: 5px; background: var(--surface-border-row); border-radius: 1px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--yellow); }
/* Indeterminate "deleting" bar — a stripe sliding across the track. */
.progress-fill--deleting {
  width: 40%;
  background: var(--deleting-color, var(--error-color));
  animation: jh-indeterminate 1.1s ease-in-out infinite;
}
@keyframes jh-indeterminate {
  0%   { margin-left: -40%; }
  100% { margin-left: 100%; }
}
@media (prefers-reduced-motion: reduce) {
  .progress-fill--deleting { animation: none; width: 100%; opacity: 0.5; }
}
.progress-pct { font-size: 11px; color: var(--text-color-muted); }
.progress-label { font-size: 12px; color: var(--text-color-muted-2); }

.action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 2px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--text-color-muted);
  transition: background 0.12s, color 0.12s;
  font-size: 14px;
}
.action-btn:hover { background: var(--surface-hover); color: var(--ink); }
.action-btn:focus-visible { outline: none; box-shadow: 0 0 0 2px var(--yellow); }
.action-btn.is-busy { opacity: 0.5; pointer-events: none; }

</style>

<!-- Menu item styles — not scoped so they reach the teleported Menu overlay -->
<style>
.menu-item { display: flex; align-items: center; gap: 8px; padding: 8px 14px; font-size: 13px; cursor: pointer; color: var(--text-color); text-decoration: none; }
.menu-item:hover { background: var(--surface-hover); }
.menu-item.menu-item-danger { color: var(--red-500, #ef4444); }

/* Row variants — target the <tr> BaseTable renders (out of this component's
   scoped reach). Override BaseTable's base row background/hover. */
.ey-table.p-datatable .p-datatable-tbody > tr.jh-row { cursor: pointer; }
.ey-table.p-datatable .p-datatable-tbody > tr.jh-row--workflow { background: var(--surface-inset); }
.ey-table.p-datatable .p-datatable-tbody > tr.jh-row--selected,
.ey-table.p-datatable .p-datatable-tbody > tr.jh-row--selected:hover {
  background: color-mix(in srgb, var(--yellow) 8%, transparent);
}
</style>

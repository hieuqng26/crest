<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useToast } from 'primevue/usetoast'
import { saveAs } from 'file-saver'
import workflowsAPI from '@/api/workflowsAPI'
import { usePolling } from '@/composables/usePolling'
import { fmtDate } from '@/utils/datetime'
import BaseTable from '@/views/composables/BaseTable.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const props = defineProps({
  runId: { type: String, required: true } // workflow run_id
})

const toast = useToast()

const outputs = ref([])
const jobs = ref([])
const loading = ref(true)
const generating = ref({}) // output_key -> bool (create in-flight)
const downloading = ref({}) // job_id -> bool

const outputLabel = computed(() => Object.fromEntries(outputs.value.map((o) => [o.key, o.label])))

const ACTIVE = new Set(['queued', 'running'])
const hasActiveJob = computed(() => jobs.value.some((j) => ACTIVE.has(j.status)))

const fetchOutputs = async () => {
  try {
    const { data } = await workflowsAPI.exportOutputs(props.runId)
    outputs.value = data.outputs ?? []
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load outputs', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  }
}

const fetchJobs = async () => {
  try {
    const { data } = await workflowsAPI.listExports(props.runId)
    jobs.value = data.jobs ?? []
  } catch (e) {
    // Poll errors are non-fatal — surface only the initial load failure.
    if (loading.value) {
      toast.add({ severity: 'error', summary: 'Failed to load exports', detail: e?.response?.data?.error ?? e.message, life: 4000 })
    }
  }
}

const poll = usePolling(fetchJobs, { interval: 3000 })
watch(hasActiveJob, (active) => { if (active) poll.start(); else poll.stop() })

onMounted(async () => {
  await Promise.all([fetchOutputs(), fetchJobs()])
  loading.value = false
  if (hasActiveJob.value) poll.start()
})

const generate = async (output, format) => {
  generating.value = { ...generating.value, [output.key]: true }
  try {
    await workflowsAPI.createExport(props.runId, output.key, format)
    toast.add({ severity: 'success', summary: 'Preparing your file…', detail: `${output.label} (${format.toUpperCase()})`, life: 2500 })
    await fetchJobs()
    poll.start()
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Could not start export', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    generating.value = { ...generating.value, [output.key]: false }
  }
}

const download = async (job) => {
  downloading.value = { ...downloading.value, [job.job_id]: true }
  try {
    const res = await workflowsAPI.downloadExport(props.runId, job.job_id)
    const name = filenameFromResponse(res) || job.filename || `${job.output_key}.${job.fmt}`
    saveAs(new Blob([res.data]), name)
  } catch (e) {
    // Blob error bodies arrive as a Blob — best-effort message.
    let detail = e?.message
    if (e?.response?.data instanceof Blob) {
      try { detail = JSON.parse(await e.response.data.text())?.error ?? detail } catch { /* keep default */ }
    } else {
      detail = e?.response?.data?.error ?? detail
    }
    toast.add({ severity: 'error', summary: 'Download failed', detail, life: 4000 })
  } finally {
    downloading.value = { ...downloading.value, [job.job_id]: false }
  }
}

const filenameFromResponse = (res) => {
  const cd = res?.headers?.['content-disposition']
  if (!cd) return null
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd)
  return m ? decodeURIComponent(m[1]) : null
}

const JOB_COLS = [
  { field: 'output', label: 'OUTPUT' },
  { field: 'format', label: 'FORMAT' },
  { field: 'status', label: 'STATUS' },
  { field: 'rows', label: 'ROWS', align: 'right' },
  { field: 'created', label: 'REQUESTED' },
  { field: 'actions', label: '', align: 'right' }
]
</script>

<template>
  <div class="download-tab">
    <div v-if="loading" class="loading-line"><i class="pi pi-spin pi-spinner" /> Loading outputs…</div>

    <template v-else>
      <!-- Available outputs -->
      <div class="panel outputs-panel">
        <div class="chart-title">Job outputs</div>
        <div class="panel-caption">Request a downloadable file for any of this workflow's outputs. Files are generated in the background and kept for a limited time.</div>

        <div class="output-list">
          <div v-for="o in outputs" :key="o.key" class="output-row">
            <div class="output-info">
              <div class="output-label">{{ o.label }}</div>
              <div class="output-desc">{{ o.description }}</div>
            </div>
            <div class="output-action">
              <SplitButton
                v-if="o.available"
                label="Generate"
                icon=""
                menuButtonIcon="pi pi-chevron-down"
                outlined
                :loading="!!generating[o.key]"
                :model="[
                  { label: 'CSV', icon: 'pi pi-file', command: () => generate(o, 'csv') },
                  { label: 'XLSX', icon: 'pi pi-file-excel', command: () => generate(o, 'xlsx') }
                ]"
                @click="generate(o, 'xlsx')"
              />
              <span v-else class="not-ready">Not ready yet</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Generated files -->
      <div class="panel results-panel">
        <div class="chart-title">Export files</div>
        <BaseTable :columns="JOB_COLS" :value="jobs" dataKey="job_id" :bleed="20" :rowHover="false">
          <template #empty>
            <EmptyState icon="pi pi-download">No export files yet. Generate one above.</EmptyState>
          </template>
          <template #cell-output="{ row }">
            {{ outputLabel[row.output_key] ?? row.output_key }}
          </template>
          <template #cell-format="{ row }">
            <span class="font-mono uppercase">{{ row.fmt }}</span>
          </template>
          <template #cell-status="{ row }">
            <span v-if="row.expired" class="muted">Expired</span>
            <span v-else class="status-cell">
              <StatusDot :status="row.status" :label="row.status === 'running' ? (row.progress_message || 'Running') : null" />
              <span v-if="row.status === 'failed' && row.error_message" class="err-hint" :title="row.error_message"><i class="pi pi-info-circle" /></span>
            </span>
          </template>
          <template #cell-rows="{ row }">
            <span class="font-mono cell-mono">{{ row.row_count != null ? row.row_count.toLocaleString() : '—' }}</span>
          </template>
          <template #cell-created="{ row }">
            <span class="font-mono cell-mono">{{ row.created_at ? fmtDate(row.created_at) : '—' }}</span>
          </template>
          <template #cell-actions="{ row }">
            <Button
              v-if="row.downloadable"
              label="Download" icon="pi pi-download" text size="small"
              :loading="!!downloading[row.job_id]"
              @click="download(row)"
            />
            <span v-else-if="row.expired" class="muted">regenerate above</span>
            <span v-else class="muted">—</span>
          </template>
        </BaseTable>
      </div>
    </template>
  </div>
</template>

<style scoped>
.download-tab { display: flex; flex-direction: column; gap: 20px; }
.loading-line { padding: 20px; text-align: center; color: var(--text-color-muted); font-size: 13px; }

/* .panel is global (_brand.scss). */
.outputs-panel, .results-panel { padding: 18px 20px; }
.chart-title { font-size: 13.5px; font-weight: 700; }
.panel-caption { font-size: 12px; color: var(--text-color-muted-2); margin-top: 3px; margin-bottom: 14px; }

.output-list { display: flex; flex-direction: column; }
.output-row {
  display: flex; align-items: center; gap: 16px;
  padding: 14px 0; border-bottom: 1px solid var(--surface-border-row);
}
.output-row:last-child { border-bottom: none; }
.output-info { flex: 1; min-width: 0; }
.output-label { font-size: 13.5px; font-weight: 600; }
.output-desc { font-size: 12px; color: var(--text-color-muted-2); margin-top: 2px; }
.output-action { flex-shrink: 0; }
.not-ready { font-size: 12px; color: var(--text-color-muted-2); font-style: italic; }

.status-cell { display: inline-flex; align-items: center; gap: 6px; }
.err-hint { color: var(--error-text-color); cursor: help; font-size: 12px; }
.cell-mono { font-size: 11.5px; color: var(--text-color-secondary); }
.muted { font-size: 12px; color: var(--text-color-muted-2); }
.uppercase { text-transform: uppercase; }
</style>

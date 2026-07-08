<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import workflowsAPI from '@/api/workflowsAPI'
import CommonDataTable from '@/components/Table/CommonDataTable.vue'
import { workflowLogColumns } from './resultColumns.js'

const props = defineProps({
  runId: { type: String, required: true }
})

const tableRef = ref(null)
const fetchPage = (params) => workflowsAPI.logs(props.runId, params)
const fetchDistinct = (column) => workflowsAPI.logsDistinct(props.runId, column)

// Logs are NOT polled. They load when the panel is opened (CommonDataTable fetches
// on mount) and reload only when the user asks — via the Reload button, or on
// revisiting the page (tab becomes visible again). refresh() re-runs the applied
// query, preserving the current page/sort/filter.
const reload = () => tableRef.value?.refresh()

const onVisible = () => { if (document.visibilityState === 'visible') reload() }
onMounted(() => document.addEventListener('visibilitychange', onVisible))
onUnmounted(() => document.removeEventListener('visibilitychange', onVisible))

const LEVEL_CLASS = { info: 'lvl-info', warn: 'lvl-warn', error: 'lvl-error' }
</script>

<template>
  <div class="wf-logs">
    <div class="wf-logs-bar">
      <span class="wf-logs-title">LOGS</span>
      <div class="spacer" />
      <Button label="Reload" icon="pi pi-refresh" text size="small" class="wf-logs-reload" @click="reload" />
    </div>

    <CommonDataTable
      ref="tableRef"
      :columns="workflowLogColumns"
      :fetch-page="fetchPage"
      :fetch-distinct="fetchDistinct"
      :initial-page-size="100"
      empty-message="No logs yet."
    >
      <template #cell-level="{ data }">
        <span class="lvl-tag" :class="LEVEL_CLASS[data.level] || 'lvl-info'">{{ (data.level || '').toUpperCase() }}</span>
      </template>
      <template #cell-message="{ data }">
        <span class="log-msg font-mono">{{ data.message }}</span>
      </template>
    </CommonDataTable>
  </div>
</template>

<style scoped>
.wf-logs { width: 100%; }

.wf-logs-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.wf-logs-title { font-size: 11px; font-weight: 700; letter-spacing: 0.07em; color: var(--text-color-muted); }
.wf-logs-bar .spacer { flex: 1; }
:deep(.wf-logs-reload.p-button) { font-size: 12.5px; font-weight: 600; color: var(--text-color-secondary); }
:deep(.wf-logs-reload.p-button:hover) { color: var(--ink); background: var(--surface-hover); }

.lvl-tag {
  display: inline-block;
  padding: 2px 7px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
  border-radius: 2px;
  font-family: 'IBM Plex Mono', monospace;
}
.lvl-info { color: var(--text-color-secondary); border: 1px solid var(--surface-border-input); }
.lvl-warn { color: #8a6d00; background: rgba(242, 194, 0, 0.14); }
.lvl-error { color: var(--error-text-color); background: rgba(196, 51, 29, 0.1); }

.log-msg { font-size: 12px; color: var(--text-color); white-space: pre-wrap; word-break: break-word; }
</style>

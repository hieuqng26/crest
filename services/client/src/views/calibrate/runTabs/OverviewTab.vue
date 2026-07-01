<script setup>
import { ref, computed, watch, onUnmounted, nextTick } from 'vue'
import calibrationsAPI from '@/api/calibrationsAPI'
import { fmtDate } from '@/utils/datetime'

const props = defineProps({ run: { type: Object, required: true } })

// ── Run details ───────────────────────────────────────────────────────────────
const featureCols = computed(() => {
  try {
    const cols = JSON.parse(props.run.feature_cols_json || '[]')
    return cols.length ? cols.join(', ') : '—'
  } catch { return '—' }
})

const statusDot = {
  queued:  '#60a5fa',
  running: '#facc15',
  success: '#34d399',
  failed:  '#f87171',
}

// ── Logs ──────────────────────────────────────────────────────────────────────
const SEVERITIES = ['info', 'warn', 'error']
const enabled    = ref({ info: true, warn: true, error: true })
const search     = ref('')
const autoScroll = ref(true)
const logEl      = ref(null)
const logs       = ref([])

const filteredLogs = computed(() => {
  const q = search.value.trim().toLowerCase()
  return logs.value.filter(l =>
    enabled.value[l.level] && (!q || l.text.toLowerCase().includes(q))
  )
})

const counts = computed(() => {
  const c = { info: 0, warn: 0, error: 0 }
  for (const l of logs.value) if (l.level in c) c[l.level]++
  return c
})

let pollTimer = null

const fetchLogs = async () => {
  try {
    const { data } = await calibrationsAPI.logs(props.run.run_id)
    logs.value = data.map(l => ({ t: l.t, level: l.level, text: l.message }))
  } catch (e) {
    console.warn('[OverviewTab] fetchLogs failed:', e?.response?.status, e?.message)
  }
}

const startPolling = () => {
  if (pollTimer) return
  pollTimer = setInterval(fetchLogs, 2000)
}

const stopPolling = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

onUnmounted(stopPolling)

watch(() => props.run.status, (s) => {
  if (s === 'running' || s === 'queued') { fetchLogs(); startPolling() }
  else { stopPolling(); fetchLogs() }
}, { immediate: true })

watch(filteredLogs, async () => {
  if (!autoScroll.value || !logEl.value) return
  await nextTick()
  logEl.value.scrollTop = logEl.value.scrollHeight
}, { flush: 'post' })

const levelColor = (level) => ({
  info:  'text-color-secondary',
  warn:  'text-yellow-700',
  error: 'text-red-500',
}[level] ?? 'text-color-secondary')

const copyAll = () => {
  navigator.clipboard?.writeText(
    logs.value.map(l => `[${l.t}] ${l.level.toUpperCase()} ${l.text}`).join('\n')
  )
}
</script>

<template>
  <div class="overview-body">

    <!-- Left: run details + progress -->
    <div class="panel flex flex-column gap-0">
      <div class="panel-title mb-3">Run Details</div>

      <dl class="detail-list">
        <div class="detail-row">
          <dt>Status</dt>
          <dd class="flex align-items-center gap-2">
            <span class="dot-status" :style="{ background: statusDot[run.status] ?? 'var(--surface-400)' }">
              <span v-if="run.status === 'running'" class="dot-ping" :style="{ background: statusDot[run.status] }" />
            </span>
            <span class="capitalize font-medium">{{ run.status }}</span>
          </dd>
        </div>
        <div class="detail-row">
          <dt>Run ID</dt>
          <dd class="font-mono text-xs">{{ run.run_id }}</dd>
        </div>
        <div class="detail-row">
          <dt>Configuration</dt>
          <dd>{{ run.config_name ?? '—' }}</dd>
        </div>
        <div class="detail-row">
          <dt>Algorithm</dt>
          <dd>{{ run.algorithm ?? '—' }}</dd>
        </div>
        <div class="detail-row">
          <dt>Dataset</dt>
          <dd>{{ run.dataset_name ?? '—' }}</dd>
        </div>
        <div class="detail-row">
          <dt>Target</dt>
          <dd class="font-mono">{{ run.target_col ?? '—' }}</dd>
        </div>
        <div class="detail-row">
          <dt>Features</dt>
          <dd class="font-mono text-xs" style="word-break:break-all">{{ featureCols }}</dd>
        </div>
        <template v-if="run.is_segmented">
          <div class="detail-row">
            <dt>Sectors</dt>
            <dd>{{ (run.seg_sectors || []).join(', ') || '—' }}</dd>
          </div>
          <div class="detail-row">
            <dt>Split By</dt>
            <dd>{{ run.seg_split_by ?? '—' }}</dd>
          </div>
          <div class="detail-row">
            <dt>Max Segments</dt>
            <dd>{{ run.seg_max_segments ?? '—' }}</dd>
          </div>
        </template>
        <div class="detail-row">
          <dt>Triggered By</dt>
          <dd>{{ run.triggered_by?.split('@')[0] ?? '—' }}</dd>
        </div>
        <div class="detail-row">
          <dt>Started</dt>
          <dd>{{ run.started_at ? fmtDate(run.started_at) : '—' }}</dd>
        </div>
        <div class="detail-row" style="border-bottom: 0">
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
    </div>

    <!-- Right: log viewer -->
    <div class="panel log-panel flex flex-column">
      <div class="flex flex-wrap align-items-center gap-2 mb-3">
        <span class="panel-title">Logs</span>
        <span class="text-xs text-color-secondary ml-1">{{ logs.length }} lines</span>

        <div class="flex gap-1 ml-2">
          <button
            v-for="lvl in SEVERITIES" :key="lvl" type="button"
            class="lvl-chip" :class="{ 'opacity-40': !enabled[lvl] }"
            @click="enabled[lvl] = !enabled[lvl]"
          >{{ lvl }} ({{ counts[lvl] }})</button>
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
          <Button icon="pi pi-copy" size="small" text rounded v-tooltip.top="'Copy all'" @click="copyAll" />
        </div>
      </div>

      <div ref="logEl" class="log-box flex-1">
        <div v-if="filteredLogs.length === 0" class="text-color-secondary text-center py-4 text-xs">
          {{ logs.length === 0 ? 'No logs yet.' : 'No log lines match your filter.' }}
        </div>
        <div v-for="(l, i) in filteredLogs" :key="i" :class="levelColor(l.level)" class="log-line">
          <span class="text-color-secondary">[{{ l.t }}]</span>
          <span class="font-bold mx-1 uppercase">{{ l.level }}</span>
          <span>{{ l.text }}</span>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.overview-body {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 1.25rem;
  min-height: 0;
}

.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  padding: 1.25rem;
}

.log-panel { overflow: hidden; }

.panel-title {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 600;
  color: var(--text-color-secondary);
}

.section-divider { margin: 1rem 0; border-top: 1px solid var(--surface-border); }

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

/* Status dot */
.dot-status {
  position: relative;
  width: 8px; height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.dot-ping {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  opacity: 0.6;
  animation: ping 1.6s cubic-bezier(0, 0, 0.2, 1) infinite;
}
@keyframes ping { 75%, 100% { transform: scale(2.4); opacity: 0; } }

/* Log viewer */
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

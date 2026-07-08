<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import jobsAPI from '@/api/jobs'
import { fmtTime } from '@/utils/datetime'

const props = defineProps({
  kind:        { type: String,  required: true },
  runId:       { type: String,  required: true },
  status:      { type: String,  required: true },
  collapsible: { type: Boolean, default: false },
  // Embedded mode: the panel lives inside the combined run/log box, which owns
  // the frame and collapse. Never self-collapse; fill the column height.
  embedded:    { type: Boolean, default: false },
})

const logs = ref([])
const search = ref('')
const logEl = ref(null)

// When collapsible: start expanded while live, collapse on completion.
const collapsed = ref(false)
const toggleCollapsed = () => { collapsed.value = !collapsed.value }

const filteredLogs = computed(() => {
  const q = search.value.trim().toLowerCase()
  return logs.value.filter((l) => !q || l.message.toLowerCase().includes(q))
})

const counts = computed(() => {
  const c = { info: 0, warn: 0, error: 0 }
  for (const l of logs.value) if (l.level in c) c[l.level]++
  return c
})

const fetchLogs = async () => {
  try {
    const { data } = await jobsAPI.getJobLogs(props.kind, props.runId)
    logs.value = data
  } catch {
    // best-effort
  }
}

watch(filteredLogs, async () => {
  await nextTick()
  if (!collapsed.value && logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
}, { flush: 'post' })

let pollTimer = null
const isLive = () => props.status === 'running' || props.status === 'queued'
const startPolling = () => { if (!pollTimer) pollTimer = setInterval(fetchLogs, 2000) }
const stopPolling = () => { clearInterval(pollTimer); pollTimer = null }

onMounted(() => {
  fetchLogs()
  if (isLive()) startPolling()
})
onUnmounted(stopPolling)
watch(() => props.status, (s) => {
  if (s === 'running' || s === 'queued') {
    startPolling()
    if (props.collapsible) collapsed.value = false
  } else {
    stopPolling()
    fetchLogs()
    if (props.collapsible) collapsed.value = true
  }
})
</script>

<template>
  <div class="logs-panel" :class="{ 'logs-panel--collapsed': collapsed, 'logs-panel--embedded': embedded }">
    <div class="logs-header" :class="{ 'logs-header--clickable': collapsible }" @click="collapsible && toggleCollapsed()">
      <span class="eyebrow logs-title">LOGS</span>
      <span class="font-mono logs-count">{{ logs.length }} lines</span>
      <span class="font-mono chip chip-info">info {{ counts.info }}</span>
      <span class="font-mono chip">warn {{ counts.warn }}</span>
      <span class="font-mono chip" :class="{ 'chip-error': counts.error > 0 }">error {{ counts.error }}</span>
      <div class="spacer" />
      <input v-if="!collapsed" v-model="search" class="logs-filter font-mono" placeholder="Filter logs…" @click.stop />
      <i v-if="collapsible" class="pi logs-chevron" :class="collapsed ? 'pi-chevron-down' : 'pi-chevron-up'" />
    </div>
    <div v-if="!collapsed" ref="logEl" class="logs-body font-mono">
      <div v-if="filteredLogs.length === 0" class="logs-empty">
        {{ logs.length === 0 ? 'No logs yet.' : 'No log lines match your filter.' }}
      </div>
      <div v-for="(l, i) in filteredLogs" :key="i" class="log-line">
        <span class="log-time">{{ fmtTime(l.t) }}</span>
        <span class="log-level" :class="`log-level--${l.level}`">{{ l.level.toUpperCase() }}</span>
        <span class="log-msg">{{ l.message }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.logs-panel {
  background: var(--ink);
  border-radius: 2px;
  display: flex;
  flex-direction: column;
  min-height: 480px;
}
.logs-panel--collapsed { min-height: unset; }

/* Embedded: fills the right column of the combined box; frame is the parent's. */
.logs-panel--embedded {
  min-height: 0;
  height: 100%;
  border-radius: 0;
}

.logs-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--chrome-hover);
  flex-wrap: wrap;
}
.logs-panel--collapsed .logs-header { border-bottom: none; }
.logs-header--clickable { cursor: pointer; user-select: none; }
.logs-header--clickable:hover { background: rgba(255,255,255,0.04); }

.logs-title { color: var(--chrome-text-muted) !important; }
.logs-count { font-size: 11px; color: #5A5A66; }
.chip {
  font-size: 10.5px;
  color: var(--chrome-text-muted);
  border: 1px solid var(--chrome-hover);
  padding: 2px 7px;
  border-radius: 2px;
}
.chip-info { color: var(--yellow); }
.chip-error { color: var(--error-color); border-color: var(--error-color); }
.spacer { flex: 1; }
.logs-filter {
  width: 180px;
  height: 28px;
  background: var(--chrome-bg-2);
  border: 1px solid var(--chrome-hover);
  border-radius: 2px;
  padding: 0 10px;
  font-size: 11.5px;
  color: #E7E7EA;
}
.logs-filter:focus { outline: none; border-color: var(--yellow); }
.logs-filter::placeholder { color: #5A5A66; }

.logs-chevron { font-size: 11px; color: var(--chrome-text-muted); flex-shrink: 0; }

.logs-body {
  padding: 14px 16px;
  font-size: 12px;
  line-height: 1.85;
  overflow-y: auto;
  flex: 1;
}
.logs-empty { color: var(--chrome-text-muted); text-align: center; padding: 2rem 0; }
.log-line { display: flex; gap: 10px; white-space: pre-wrap; word-break: break-all; }
.log-time { color: #5A5A66; flex: none; }
.log-level { font-weight: 600; flex: none; }
.log-level--info { color: var(--yellow); }
.log-level--warn { color: #D6B600; }
.log-level--error { color: var(--error-color); }
.log-msg { color: #D8D8DE; }
</style>

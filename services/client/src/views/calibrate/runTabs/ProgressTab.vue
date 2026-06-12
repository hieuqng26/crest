<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { socket } from '@/api/socket'

const props = defineProps({ run: { type: Object, required: true } })
const emit = defineEmits(['update:run'])

const SEVERITIES = ['info', 'warn', 'error']
const enabled = ref({ info: true, warn: true, error: true })
const search = ref('')
const autoScroll = ref(true)
const logEl = ref(null)

const logs = ref([
  { t: new Date().toISOString().slice(11, 19), level: 'info', text: `Connecting to run ${props.run.run_id}…` }
])

const filteredLogs = computed(() => {
  const q = search.value.trim().toLowerCase()
  return logs.value.filter(l =>
    enabled.value[l.level] &&
    (!q || l.text.toLowerCase().includes(q))
  )
})

const counts = computed(() => {
  const c = { info: 0, warn: 0, error: 0 }
  for (const l of logs.value) c[l.level]++
  return c
})

const appendLog = (level, text) => {
  const t = new Date().toISOString().slice(11, 19)
  logs.value.push({ t, level, text })
}

const inferLevel = (msg) => {
  const m = msg?.toLowerCase() ?? ''
  if (m.includes('error') || m.includes('fail')) return 'error'
  if (m.includes('warn'))  return 'warn'
  return 'info'
}

// SocketIO: listen for progress events from the Celery task
const onProgress = (payload) => {
  if (payload.run_id !== props.run.run_id) return
  const level = payload.progress === -1 ? 'error' : inferLevel(payload.message)
  appendLog(level, payload.message)
  const next = payload.progress >= 0
    ? { ...props.run, progress: payload.progress }
    : { ...props.run, status: 'failed' }
  if (payload.progress === 100) next.status = 'success'
  emit('update:run', next)
}

onMounted(() => {
  socket.on('calibration_progress', onProgress)
  if (props.run.status === 'running' || props.run.status === 'queued') {
    appendLog('info', 'Waiting for task worker…')
  } else if (props.run.status === 'success') {
    appendLog('info', 'Run completed successfully.')
  } else if (props.run.status === 'failed') {
    appendLog('error', props.run.error_message ?? 'Run failed.')
  }
})
onUnmounted(() => socket.off('calibration_progress', onProgress))

watch(filteredLogs, async () => {
  if (!autoScroll.value || !logEl.value) return
  await nextTick()
  logEl.value.scrollTop = logEl.value.scrollHeight
}, { flush: 'post' })

const levelColor = (level) => ({
  info:  'text-color-secondary',
  warn:  'text-yellow-400',
  error: 'text-red-400'
}[level] || 'text-color-secondary')

const copyAll = () => {
  navigator.clipboard?.writeText(
    logs.value.map(l => `[${l.t}] ${l.level.toUpperCase()} ${l.text}`).join('\n')
  )
}
</script>

<template>
  <div class="flex flex-column gap-4">
    <!-- Progress card -->
    <div class="surface-card border-round shadow-1 p-4">
      <div class="flex align-items-center justify-content-between mb-2">
        <span class="text-sm font-semibold text-color-secondary uppercase">Training progress</span>
        <span class="text-sm font-mono">{{ run.progress }}%</span>
      </div>
      <ProgressBar :value="run.progress" style="height: 10px" />
      <div class="flex gap-2 mt-2 text-xs text-color-secondary">
        <span v-if="run.status === 'running'"><i class="pi pi-spin pi-spinner" /> Live</span>
        <span v-else-if="run.status === 'success'"><i class="pi pi-check-circle text-green-400" /> Completed</span>
        <span v-else-if="run.status === 'failed'"><i class="pi pi-times-circle text-red-400" /> Failed</span>
      </div>
    </div>

    <!-- Log viewer -->
    <div class="surface-card border-round shadow-1 p-4">
      <div class="flex flex-wrap align-items-center gap-2 mb-3">
        <span class="text-sm font-semibold text-color-secondary uppercase">Logs</span>
        <span class="text-xs text-color-secondary ml-2">{{ logs.length }} lines</span>

        <div class="flex gap-1 ml-3">
          <Chip
            v-for="lvl in SEVERITIES"
            :key="lvl"
            :label="`${lvl} (${counts[lvl]})`"
            class="cursor-pointer text-xs"
            :class="enabled[lvl] ? '' : 'opacity-50'"
            @click="enabled[lvl] = !enabled[lvl]"
          />
        </div>

        <IconField class="flex-1 ml-2" style="min-width: 14rem">
          <InputIcon class="pi pi-search" />
          <InputText v-model="search" placeholder="Filter logs…" class="w-full" />
        </IconField>

        <div class="flex gap-1 ml-auto">
          <Button
            :icon="autoScroll ? 'pi pi-arrow-down' : 'pi pi-pause'"
            size="small" text rounded
            v-tooltip.top="autoScroll ? 'Auto-scroll on' : 'Auto-scroll off'"
            @click="autoScroll = !autoScroll"
          />
          <Button icon="pi pi-copy" size="small" text rounded v-tooltip.top="'Copy all'" @click="copyAll" />
        </div>
      </div>

      <div
        ref="logEl"
        class="surface-ground border-round p-3 font-mono text-xs"
        style="height: 22rem; overflow-y: auto"
      >
        <div v-if="filteredLogs.length === 0" class="text-color-secondary text-center py-4">
          No log lines match your filter.
        </div>
        <div v-for="(l, i) in filteredLogs" :key="i" :class="levelColor(l.level)" class="whitespace-nowrap">
          <span class="text-color-secondary">[{{ l.t }}]</span>
          <span class="font-bold mx-1 uppercase">{{ l.level }}</span>
          <span>{{ l.text }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

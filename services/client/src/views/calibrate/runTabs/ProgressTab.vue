<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import calibrationsAPI from '@/api/calibrationsAPI'

const props = defineProps({ run: { type: Object, required: true } })

const SEVERITIES = ['info', 'warn', 'error']
const enabled = ref({ info: true, warn: true, error: true })
const search = ref('')
const autoScroll = ref(true)
const logEl = ref(null)

const logs = ref([])

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

const isActive = () => props.run.status === 'running' || props.run.status === 'queued'

let pollTimer = null

const fetchLogs = async () => {
  try {
    const { data } = await calibrationsAPI.logs(props.run.run_id)
    logs.value = data.map(l => ({ t: l.t, level: l.level, text: l.message }))
  } catch (e) {
    console.warn('[ProgressTab] fetchLogs failed:', e?.response?.status, e?.message)
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

// immediate: true ensures fetchLogs() is called on component creation for any status,
// including terminal states (failed/success) where there is no polling to retry.
watch(() => props.run.status, (s) => {
  if (s === 'running' || s === 'queued') {
    fetchLogs()
    startPolling()
  } else {
    stopPolling()
    fetchLogs()
  }
}, { immediate: true })

watch(filteredLogs, async () => {
  if (!autoScroll.value || !logEl.value) return
  await nextTick()
  logEl.value.scrollTop = logEl.value.scrollHeight
}, { flush: 'post' })

const levelColor = (level) => ({
  info:  'text-color-secondary',
  warn:  'text-yellow-700',
  error: 'text-red-500'
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

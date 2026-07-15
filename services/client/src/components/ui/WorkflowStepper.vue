<script setup>
import { computed } from 'vue'

// Progress tracker for the workflow pipeline: Training → Forecast →
// Credit Analysis → Complete. Reads the same `wf` object WorkflowDetail already
// holds (full + light-merged), so it updates live as polling advances stages.
const props = defineProps({
  wf: { type: Object, required: true }
})

// Aggregate a set of child-run statuses into one step state. `pending` means no
// runs exist for the step yet; otherwise failed wins, then all-success, then any
// running, then queued.
const aggStatus = (runs) => {
  const list = (runs ?? []).filter(Boolean)
  if (!list.length) return 'pending'
  if (list.some((r) => r.status === 'failed')) return 'failed'
  if (list.every((r) => r.status === 'success')) return 'success'
  if (list.some((r) => r.status === 'running')) return 'running'
  if (list.some((r) => r.status === 'queued')) return 'queued'
  return 'running'
}

const cals = computed(() => (props.wf?.targets ?? []).map((t) => t.calibration))
const fcs = computed(() =>
  (props.wf?.targets ?? []).map((t) => t.forecast).filter(Boolean)
)

const trainState = computed(() => aggStatus(cals.value))

const forecastState = computed(() => {
  if (trainState.value === 'failed') return 'pending'
  if (fcs.value.length === 0) return trainState.value === 'success' ? 'queued' : 'pending'
  return aggStatus(fcs.value)
})

// The credit run's 0–100 progress is split by the backend: the per-client KMV+ECL
// computation runs 0 → CLIENT_COMPUTE_END, then the analysis-series materialisation
// runs CLIENT_COMPUTE_END → 100 while the run stays `running`. We map the two bands
// onto the "Credit Analysis" and "Complete" steps. Keep in sync with the backend
// `_CLIENT_COMPUTE_END` (services/server/project/workers/credit.py).
const CLIENT_COMPUTE_END = 80
const analysisProgress = computed(() => props.wf?.analysis?.progress ?? 0)

const creditState = computed(() => {
  if (props.wf?.analysis_skipped_reason) return 'skipped'
  const a = props.wf?.analysis
  if (!a) {
    // No analysis run: either not reached yet, or the workflow finished with credit
    // analysis skipped (no credit dataset / missing targets) before the skip reason
    // was re-fetched into the light-polled object.
    if (props.wf?.status === 'success' && props.wf?.current_stage === 'done') return 'skipped'
    return forecastState.value === 'success' ? 'queued' : 'pending'
  }
  if (a.status === 'failed') return 'failed'
  if (a.status === 'success') return 'success'
  // Past the compute band the KMV+ECL computation is done — the remaining work
  // (materialisation) belongs to the Complete step, so Credit reads as done.
  if (a.status === 'running') return analysisProgress.value >= CLIENT_COMPUTE_END ? 'success' : 'running'
  return a.status || 'queued'
})

// Final step — the post-analysis finalisation (materialising the heatmap / forecast
// views). The credit run stays `running` through this phase with progress in the
// CLIENT_COMPUTE_END → 100 band, so show it as running with a real percentage rather
// than an idle-looking pending. A workflow failure surfaces on the failing step.
const doneState = computed(() => {
  if (props.wf?.status === 'success' && props.wf?.current_stage === 'done') return 'success'
  const a = props.wf?.analysis
  if (a && a.status === 'running' && analysisProgress.value >= CLIENT_COMPUTE_END) return 'running'
  const creditDone = creditState.value === 'success' || creditState.value === 'skipped'
  if (creditDone && props.wf?.status === 'running') return 'running'
  return 'pending'
})

// Sub-caption for a target-count step (Training/Forecast).
const countCaption = (runs, state) => {
  const list = (runs ?? []).filter(Boolean)
  const done = list.filter((r) => r.status === 'success').length
  const total = list.length
  if (state === 'failed') return 'Failed'
  if (state === 'success') return `${total}/${total} done`
  if (state === 'running') return `${done}/${total} done`
  if (state === 'queued') return 'Queued'
  return 'Pending'
}

const STATE_CAPTION = {
  success: 'Done',
  running: 'Running',
  queued: 'Queued',
  failed: 'Failed',
  skipped: 'Skipped',
  pending: 'Pending'
}

const pct = (v) => `${Math.max(0, Math.min(100, Math.round(v)))}%`

// Credit shows the client-compute percentage while running (0 → CLIENT_COMPUTE_END
// mapped to 0–100%); otherwise a plain state word.
const creditCaption = computed(() => {
  if (creditState.value !== 'running') return STATE_CAPTION[creditState.value]
  return pct((analysisProgress.value / CLIENT_COMPUTE_END) * 100)
})

// Complete shows the materialisation percentage while finalising (CLIENT_COMPUTE_END
// → 100 mapped to 0–100%).
const doneCaption = computed(() => {
  if (doneState.value === 'success') return 'Finished'
  if (doneState.value !== 'running') return 'Pending'
  const p = analysisProgress.value
  if (p < CLIENT_COMPUTE_END) return 'Finalizing'
  return pct(((p - CLIENT_COMPUTE_END) / (100 - CLIENT_COMPUTE_END)) * 100)
})

const steps = computed(() => [
  {
    key: 'training',
    label: 'Training',
    state: trainState.value,
    caption: countCaption(cals.value, trainState.value)
  },
  {
    key: 'forecast',
    label: 'Forecast',
    state: forecastState.value,
    caption: countCaption(fcs.value, forecastState.value)
  },
  {
    key: 'credit',
    label: 'Credit Analysis',
    state: creditState.value,
    caption: creditCaption.value
  },
  {
    key: 'done',
    label: 'Complete',
    state: doneState.value,
    caption: doneCaption.value
  }
])

// Node glyph: check / cross / dash, else the 1-based step number.
const nodeIcon = (state) => {
  if (state === 'success') return 'pi pi-check'
  if (state === 'failed') return 'pi pi-times'
  if (state === 'skipped') return 'pi pi-minus'
  if (state === 'running') return 'pi pi-spin pi-spinner'
  return null
}
</script>

<template>
  <ol class="wf-stepper" aria-label="Workflow progress">
    <li
      v-for="(step, i) in steps"
      :key="step.key"
      class="wf-step"
      :class="`is-${step.state}`"
      :aria-current="step.state === 'running' ? 'step' : undefined"
    >
      <!-- connector into this step (skipped on the first) -->
      <span
        v-if="i > 0"
        class="wf-connector"
        :class="{ 'is-filled': steps[i - 1].state === 'success' || steps[i - 1].state === 'skipped' }"
        aria-hidden="true"
      />
      <span class="wf-node">
        <i v-if="nodeIcon(step.state)" :class="nodeIcon(step.state)" />
        <span v-else class="wf-node-num">{{ i + 1 }}</span>
      </span>
      <span class="wf-labels">
        <span class="wf-label">{{ step.label }}</span>
        <span class="wf-caption">{{ step.caption }}</span>
      </span>
    </li>
  </ol>
</template>

<style scoped>
.wf-stepper {
  display: flex;
  align-items: flex-start;
  list-style: none;
  margin: 0;
  padding: 0;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
  padding: 20px 24px;
}
.wf-step {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
/* Connector spans the gap between this node's centre and the previous one's,
   sitting behind the node row (node is 30px tall → line at 15px). */
.wf-connector {
  position: absolute;
  top: 15px;
  right: 50%;
  left: -50%;
  height: 2px;
  background: var(--surface-border-input);
  transform: translateY(-1px);
}
.wf-connector.is-filled { background: var(--success-color); }

.wf-node {
  position: relative;
  z-index: 1;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--surface-border-input);
  background: var(--surface-card);
  color: var(--text-color-muted-2);
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}
.wf-node-num { line-height: 1; }
.wf-node i { font-size: 13px; }

.wf-labels {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  text-align: center;
  min-width: 0;
}
.wf-label {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-color-muted);
  line-height: 1.2;
}
.wf-caption {
  font-size: 11px;
  color: var(--text-color-muted-2);
  line-height: 1.2;
}

/* ── Per-state colouring ─────────────────────────────────────────────────── */
.is-success .wf-node {
  border-color: var(--success-color);
  background: var(--success-color);
  color: #fff;
}
.is-success .wf-label { color: var(--ink); }

.is-running .wf-node {
  border-color: var(--running-color);
  color: var(--running-text-color);
}
.is-running .wf-label { color: var(--ink); }
.is-running .wf-caption { color: var(--running-text-color); }

.is-failed .wf-node {
  border-color: var(--error-color);
  background: var(--error-color);
  color: #fff;
}
.is-failed .wf-label { color: var(--error-text-color); }
.is-failed .wf-caption { color: var(--error-text-color); }

.is-queued .wf-node { border-color: var(--queued-color); color: var(--text-color-muted); }
.is-queued .wf-label { color: var(--text-color-muted); }

.is-skipped .wf-node { border-style: dashed; }
.is-skipped .wf-label,
.is-skipped .wf-caption { color: var(--text-color-muted-2); }

/* Stack vertically on narrow screens (connectors drop out to avoid overlap). */
@media (max-width: 640px) {
  .wf-stepper { flex-direction: column; align-items: stretch; gap: 14px; }
  .wf-step { flex-direction: row; align-items: center; gap: 12px; }
  .wf-labels { align-items: flex-start; text-align: left; }
  .wf-connector { display: none; }
}
</style>

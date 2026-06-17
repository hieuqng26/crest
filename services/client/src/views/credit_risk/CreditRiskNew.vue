<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'

import calibrationsAPI from '@/api/calibrationsAPI'
import creditRiskAPI from '@/api/creditRiskAPI'
import datasetsAPI from '@/api/datasetsAPI'

const router = useRouter()
const toast  = useToast()

// ── data sources ──────────────────────────────────────────────────────────────
const creditDatasets = ref([])
const calRuns        = ref([])
const loadingInit    = ref(false)

const datasetOptions = computed(() =>
  creditDatasets.value.map(d => ({
    label: `${d.name}  (${d.row_count?.toLocaleString() ?? '?'} rows)`,
    value: d.id,
  }))
)

// ── calibration input selection ───────────────────────────────────────────────
// Group successful cal runs by target_col → { [target_col]: [run, ...] }
const targetVarMap = computed(() => {
  const map = {}
  for (const r of calRuns.value) {
    const key = r.target_col || '(unknown)'
    if (!map[key]) map[key] = []
    map[key].push(r)
  }
  return map
})

const availableTargetVars = computed(() => Object.keys(targetVarMap.value).sort())

// selectedInputs: [{ target_col, cal_run_id }] — one entry per chosen target variable
const selectedInputs = ref([])

function toggleTargetVar(targetCol) {
  const idx = selectedInputs.value.findIndex(i => i.target_col === targetCol)
  if (idx >= 0) {
    selectedInputs.value.splice(idx, 1)
  } else {
    const runs = targetVarMap.value[targetCol] || []
    // Default to the most recently created run for this target variable
    const latest = runs.reduce((a, b) =>
      new Date(a.created_at || 0) > new Date(b.created_at || 0) ? a : b, runs[0])
    selectedInputs.value.push({ target_col: targetCol, cal_run_id: latest?.run_id ?? null })
  }
}

function isTargetSelected(targetCol) {
  return selectedInputs.value.some(i => i.target_col === targetCol)
}

function runOptionsFor(targetCol) {
  return (targetVarMap.value[targetCol] || []).map(r => ({
    label: `${r.config_name ?? r.run_id.slice(0, 8)}  ·  ${r.run_id.slice(0, 8)}…`,
    value: r.run_id,
  }))
}

// ── form state ────────────────────────────────────────────────────────────────
const selectedDatasetId = ref(null)
const exposure          = ref(1_000_000)
const discountRate      = ref(0.05)
const lifetimeHorizon   = ref(5)
const submitting        = ref(false)

const canLaunch = computed(() => selectedDatasetId.value != null && exposure.value > 0)

const launch = async () => {
  if (!canLaunch.value) return
  submitting.value = true
  try {
    const { data } = await creditRiskAPI.createRun({
      dataset_id:       selectedDatasetId.value,
      cal_run_ids:      selectedInputs.value.map(i => i.cal_run_id).filter(Boolean),
      exposure:         exposure.value,
      discount_rate:    discountRate.value,
      lifetime_horizon: lifetimeHorizon.value,
    })
    toast.add({ severity: 'success', summary: 'Queued', detail: `Run ${data.run_id.slice(0, 8)}…`, life: 3000 })
    router.push({ name: 'credit_risk_jobs' })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Launch failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  loadingInit.value = true
  try {
    const [dsResp, crResp] = await Promise.all([
      datasetsAPI.listByKind('credit'),
      calibrationsAPI.list({ status: 'success', per_page: 200 }),
    ])
    creditDatasets.value = dsResp.data ?? []
    calRuns.value        = (crResp.data?.items ?? crResp.data) ?? []
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    loadingInit.value = false
  }
})
</script>

<template>
  <div class="p-5 mx-auto" style="max-width: 860px">
    <!-- Header -->
    <header class="flex align-items-end justify-content-between mb-5 flex-wrap gap-3">
      <div>
        <div class="text-xs text-color-secondary uppercase mb-1" style="letter-spacing: 0.06em">Credit Risk</div>
        <h1 class="text-3xl font-semibold m-0 tracking-tight">New Analysis</h1>
        <p class="text-color-secondary text-sm m-0 mt-1">
          Run KMV and IFRS 9 ECL computations for every client in a credit dataset.
        </p>
      </div>
      <Button
        label="Launch"
        icon="pi pi-play"
        :loading="submitting"
        :disabled="!canLaunch || loadingInit"
        @click="launch"
      />
    </header>

    <!-- Card: Data sources -->
    <div class="form-card mb-4">
      <div class="form-card-head">
        <div class="text-xs text-color-secondary uppercase font-semibold" style="letter-spacing: 0.06em">
          Data Sources
        </div>
      </div>

      <div class="form-row">
        <div class="form-label">
          <div class="font-medium text-sm">Credit Dataset</div>
          <div class="text-xs text-color-secondary mt-1">
            Must include <span class="font-mono">client_id</span>,
            <span class="font-mono">market_cap</span>,
            <span class="font-mono">vol_equity</span>,
            <span class="font-mono">risk_free_rate</span>,
            <span class="font-mono">rating</span>.
          </div>
        </div>
        <div class="form-input">
          <Dropdown
            v-model="selectedDatasetId"
            :options="datasetOptions"
            optionLabel="label"
            optionValue="value"
            placeholder="Select credit dataset"
            :loading="loadingInit"
            :disabled="loadingInit"
            class="w-full"
            filter
          />
          <div v-if="!loadingInit && creditDatasets.length === 0" class="text-xs text-color-secondary mt-1">
            No credit datasets found.
            <a class="text-primary cursor-pointer" @click="router.push({ name: 'credit_risk_data' })">Upload one</a>
            first.
          </div>
        </div>
      </div>
    </div>

    <!-- Card: Calibration Inputs -->
    <div class="form-card mb-4">
      <div class="form-card-head flex align-items-center justify-content-between">
        <div class="text-xs text-color-secondary uppercase font-semibold" style="letter-spacing: 0.06em">
          Calibration Inputs <span class="font-normal normal-case ml-1">(optional)</span>
        </div>
        <div v-if="selectedInputs.length" class="text-xs text-color-secondary">
          {{ selectedInputs.length }} selected
        </div>
      </div>

      <!-- No cal runs -->
      <div v-if="!loadingInit && availableTargetVars.length === 0" class="p-4 text-xs text-color-secondary">
        No successful calibration runs found. Analysis will use synthetic scenarios.
      </div>

      <div v-else class="p-4">
        <div class="text-xs text-color-secondary mb-3">
          Select target variables to use as balance sheet inputs. If multiple runs share a variable, choose which one to use.
        </div>

        <!-- Target variable chips -->
        <div class="flex flex-wrap gap-2 mb-4">
          <button
            v-for="tv in availableTargetVars"
            :key="tv"
            type="button"
            class="tv-chip"
            :class="{ 'is-selected': isTargetSelected(tv) }"
            @click="toggleTargetVar(tv)"
          >
            <i class="pi text-xs" :class="isTargetSelected(tv) ? 'pi-check-circle' : 'pi-circle'" />
            {{ tv }}
            <span class="tv-count">{{ targetVarMap[tv].length }}</span>
          </button>
        </div>

        <!-- Run selectors for chosen target vars -->
        <div v-if="selectedInputs.length" class="flex flex-column gap-3">
          <div
            v-for="inp in selectedInputs"
            :key="inp.target_col"
            class="cal-input-row"
          >
            <div class="font-medium text-sm w-10rem flex-shrink-0">{{ inp.target_col }}</div>
            <Dropdown
              v-model="inp.cal_run_id"
              :options="runOptionsFor(inp.target_col)"
              optionLabel="label"
              optionValue="value"
              class="flex-1"
              :disabled="runOptionsFor(inp.target_col).length <= 1"
            />
            <Button
              icon="pi pi-times"
              text rounded size="small"
              severity="secondary"
              @click="toggleTargetVar(inp.target_col)"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- Card: Parameters -->
    <div class="form-card mb-5">
      <div class="form-card-head">
        <div class="text-xs text-color-secondary uppercase font-semibold" style="letter-spacing: 0.06em">
          Parameters
        </div>
      </div>

      <div class="form-row">
        <div class="form-label">
          <div class="font-medium text-sm">Exposure at Default (EAD)</div>
          <div class="text-xs text-color-secondary mt-1">Notional exposure per client used in ECL calculation.</div>
        </div>
        <div class="form-input">
          <InputNumber
            v-model="exposure"
            :min="1"
            mode="decimal"
            :useGrouping="true"
            :minFractionDigits="0"
            :maxFractionDigits="0"
            class="w-full"
          />
        </div>
      </div>

      <div class="form-row">
        <div class="form-label">
          <div class="font-medium text-sm">Discount Rate</div>
          <div class="text-xs text-color-secondary mt-1">Annual discount rate for ECL present-value calculation.</div>
        </div>
        <div class="form-input">
          <InputNumber
            v-model="discountRate"
            :min="0"
            :max="1"
            :step="0.01"
            :minFractionDigits="2"
            :maxFractionDigits="4"
            class="w-full"
          />
        </div>
      </div>

      <div class="form-row" style="border-bottom: 0">
        <div class="form-label">
          <div class="font-medium text-sm">Lifetime Horizon</div>
          <div class="text-xs text-color-secondary mt-1">Number of years for lifetime ECL calculation.</div>
        </div>
        <div class="form-input">
          <InputNumber
            v-model="lifetimeHorizon"
            :min="1"
            :max="30"
            :step="1"
            :minFractionDigits="0"
            :maxFractionDigits="0"
            class="w-full"
          />
        </div>
      </div>
    </div>

    <div class="flex gap-2">
      <Button label="Launch" icon="pi pi-play" :loading="submitting" :disabled="!canLaunch || loadingInit" @click="launch" />
      <Button label="Cancel" severity="secondary" text @click="router.push({ name: 'credit_risk_jobs' })" />
    </div>

    <Toast />
  </div>
</template>

<style scoped>
.form-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  overflow: hidden;
}

.form-card-head {
  padding: 0.85rem 1.5rem;
  border-bottom: 1px solid var(--surface-border);
  background: var(--surface-ground);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1.6fr;
  gap: 1.5rem;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--surface-border);
  align-items: start;
}

.form-label { padding-top: 0.2rem; }
.form-input { display: flex; flex-direction: column; gap: 0.25rem; }

/* Target variable chips */
.tv-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--surface-border);
  background: transparent;
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
  cursor: pointer;
  transition: all 120ms ease;
}
.tv-chip:hover { border-color: var(--primary-color); color: var(--text-color); }
.tv-chip.is-selected {
  border-color: var(--primary-color);
  background: color-mix(in srgb, var(--primary-color) 12%, transparent);
  color: var(--text-color);
}
.tv-count {
  font-size: 0.7rem;
  background: var(--surface-border);
  border-radius: 999px;
  padding: 1px 6px;
  color: var(--text-color-secondary);
}

.cal-input-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
  background: var(--surface-ground);
}

:deep(.p-inputnumber-input) { width: 100%; }
</style>

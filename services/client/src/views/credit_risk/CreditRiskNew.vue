<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'

import creditRiskAPI from '@/api/creditRiskAPI'
import datasetsAPI from '@/api/datasetsAPI'
import forecastRunsAPI from '@/api/forecastRunsAPI'

const router = useRouter()
const toast  = useToast()

// ── data sources ──────────────────────────────────────────────────────────────
const creditDatasets = ref([])
const forecastRuns   = ref([])
const loadingInit    = ref(false)

const datasetOptions = computed(() =>
  creditDatasets.value.map(d => ({
    label: `${d.name}  (${d.row_count?.toLocaleString() ?? '?'} rows)`,
    value: d.id,
  }))
)

// ── KMV calibration inputs (3 required) ──────────────────────────────────────
const KMV_INPUTS = [
  { key: 'total_assets',     label: 'Total Assets',     hint: 'Forecast of total assets — used as AT in KMV' },
  { key: 'short_term_debts', label: 'Short-term Debts', hint: 'Forecast of current liabilities (CL)' },
  { key: 'long_term_debts',  label: 'Long-term Debts',  hint: 'Forecast of non-current liabilities (NonCL)' },
]

const calInputs = ref({ total_assets: null, short_term_debts: null, long_term_debts: null })

const runOptions = computed(() =>
  forecastRuns.value.map(r => ({
    label: `${r.target_col ?? '—'}  ·  ${r.name ?? r.config_name ?? r.run_id.slice(0, 8)}  ·  ${r.run_id.slice(0, 8)}…`,
    value: r.run_id,
  }))
)

// ── form state ────────────────────────────────────────────────────────────────
const selectedDatasetId = ref(null)
const exposure          = ref(1_000_000)
const discountRate      = ref(0.05)
const lifetimeHorizon   = ref(5)
const submitting        = ref(false)

const allInputsFilled = computed(() =>
  KMV_INPUTS.every(i => calInputs.value[i.key] != null)
)
const canLaunch = computed(() => selectedDatasetId.value != null && exposure.value > 0 && allInputsFilled.value)

const launch = async () => {
  if (!canLaunch.value) return
  submitting.value = true
  try {
    const { data } = await creditRiskAPI.createRun({
      dataset_id:       selectedDatasetId.value,
      cal_inputs:       calInputs.value,
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
    const [dsResp, frResp] = await Promise.all([
      datasetsAPI.listByKind('credit'),
      forecastRunsAPI.list({ status: 'success' }),
    ])
    creditDatasets.value = dsResp.data ?? []
    forecastRuns.value   = frResp.data ?? []
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    loadingInit.value = false
  }
})
</script>

<template>
  <div class="p-5 mx-auto" style="max-width: 1040px">
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
        v-can="'credit_risk:execute'"
        label="Launch"
        icon="pi pi-play"
        :loading="submitting"
        :disabled="!canLaunch || loadingInit || submitting"
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
            No credit datasets found. Go to
            <a class="text-primary cursor-pointer" @click="router.push({ name: 'datasets' })">Datasets</a>
            and upload a file with type "Credit".
          </div>
        </div>
      </div>
    </div>

    <!-- Card: Forecast Inputs -->
    <div class="form-card mb-4">
      <div class="form-card-head flex align-items-center justify-content-between">
        <div class="text-xs text-color-secondary uppercase font-semibold" style="letter-spacing: 0.06em">
          Forecast Inputs
        </div>
        <div class="text-xs text-color-secondary">
          {{ KMV_INPUTS.filter(i => calInputs[i.key]).length }} / {{ KMV_INPUTS.length }} selected
        </div>
      </div>

      <div v-if="!loadingInit && forecastRuns.length === 0" class="p-4 text-xs text-color-secondary">
        No successful forecast runs found.
        Create forecast runs for <span class="font-mono">total_assets</span>,
        <span class="font-mono">short_term_debts</span>, and
        <span class="font-mono">long_term_debts</span> in the
        <a class="text-primary cursor-pointer" @click="router.push({ name: 'forecast_jobs' })">Forecast</a>
        module before launching.
      </div>

      <div v-else>
        <div
          v-for="inp in KMV_INPUTS"
          :key="inp.key"
          class="form-row"
        >
          <div class="form-label">
            <div class="flex align-items-center gap-2">
              <i
                class="pi text-xs"
                :class="calInputs[inp.key] ? 'pi-check-circle' : 'pi-circle'"
                :style="calInputs[inp.key] ? 'color:#34d399' : 'color:var(--text-color-secondary)'"
              />
              <span class="font-medium text-sm">{{ inp.label }}</span>
            </div>
            <div class="text-xs text-color-secondary mt-1 ml-4">{{ inp.hint }}</div>
          </div>
          <div class="form-input">
            <Dropdown
              v-model="calInputs[inp.key]"
              :options="runOptions"
              optionLabel="label"
              optionValue="value"
              :loading="loadingInit"
              :disabled="loadingInit || forecastRuns.length === 0"
              placeholder="Select forecast run"
              class="w-full"
              filter
              showClear
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
      <Button v-can="'credit_risk:execute'" label="Launch" icon="pi pi-play" :loading="submitting" :disabled="!canLaunch || loadingInit || submitting" @click="launch" />
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
  box-shadow: 0 2px 8px rgba(20, 20, 40, 0.06), 0 1px 2px rgba(20, 20, 40, 0.04);
}

.form-card-head {
  padding: 0.85rem 1.5rem;
  border-bottom: 1px solid var(--surface-border);
  background: var(--surface-section);
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


:deep(.p-inputnumber-input) { width: 100%; }
</style>

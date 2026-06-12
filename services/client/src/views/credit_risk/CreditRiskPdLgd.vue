<script setup>
import { ref } from 'vue'

const selectedRun = ref('PD_LR_2024_Q4')
const runOptions = [
  { label: 'PD_LR_2024_Q4',  hash: 'a1b2c3d4' },
  { label: 'PD_GLM_Retail',  hash: 'f7a8b9c0' }
]

const pdTermData = {
  labels: ['1Y', '2Y', '3Y', '5Y', '7Y', '10Y'],
  datasets: [
    { label: 'Corporate', data: [0.012, 0.024, 0.038, 0.058, 0.073, 0.091], borderColor: '#60a5fa', borderWidth: 2, tension: 0.35, pointRadius: 0, pointHoverRadius: 4 },
    { label: 'Retail',    data: [0.021, 0.038, 0.055, 0.079, 0.098, 0.118], borderColor: '#facc15', borderWidth: 2, tension: 0.35, pointRadius: 0, pointHoverRadius: 4 },
    { label: 'SME',       data: [0.031, 0.057, 0.081, 0.112, 0.138, 0.162], borderColor: '#f87171', borderWidth: 2, tension: 0.35, pointRadius: 0, pointHoverRadius: 4 }
  ]
}

const lgdTermData = {
  labels: ['1Y', '2Y', '3Y', '5Y', '7Y', '10Y'],
  datasets: [
    { label: 'Secured',   data: [0.32, 0.35, 0.37, 0.40, 0.42, 0.44], borderColor: '#34d399', borderWidth: 2, tension: 0.35, pointRadius: 0, pointHoverRadius: 4 },
    { label: 'Unsecured', data: [0.55, 0.57, 0.59, 0.62, 0.64, 0.66], borderColor: '#a78bfa', borderWidth: 2, tension: 0.35, pointRadius: 0, pointHoverRadius: 4 }
  ]
}

const pdLegend  = pdTermData.datasets.map(d => ({ label: d.label, color: d.borderColor }))
const lgdLegend = lgdTermData.datasets.map(d => ({ label: d.label, color: d.borderColor }))

const baseOptions = {
  maintainAspectRatio: false,
  plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
  interaction: { mode: 'nearest', axis: 'x', intersect: false },
  scales: {
    x: { ticks: { color: '#9ca3af', font: { size: 10 } }, grid: { display: false } },
    y: {
      ticks: { color: '#9ca3af', font: { size: 10 }, callback: v => (v * 100).toFixed(1) + '%' },
      grid: { color: 'rgba(156,163,175,0.08)' },
      border: { display: false }
    }
  }
}

const table = [
  { segment: 'Corporate', horizon: '1Y', pd: '1.20%', lgd: '42%', ead: '2,140M', ecl: '10.8M' },
  { segment: 'Corporate', horizon: '3Y', pd: '3.80%', lgd: '42%', ead: '2,140M', ecl: '34.1M' },
  { segment: 'Retail',    horizon: '1Y', pd: '2.10%', lgd: '35%', ead: '3,200M', ecl: '23.5M' },
  { segment: 'Retail',    horizon: '3Y', pd: '5.50%', lgd: '35%', ead: '3,200M', ecl: '61.6M' },
  { segment: 'SME',       horizon: '1Y', pd: '3.10%', lgd: '55%', ead: '430M',   ecl: '7.3M'  }
]

const currentRunMeta = () => runOptions.find(r => r.label === selectedRun.value)
</script>

<template>
  <div class="p-5 mx-auto" style="max-width: 1400px">
    <!-- Header -->
    <header class="flex align-items-end justify-content-between mb-5 flex-wrap gap-3">
      <div>
        <h1 class="text-3xl font-semibold m-0 tracking-tight">PD / LGD Term Structure</h1>
        <p class="text-color-secondary text-sm m-0 mt-1">Lifetime PD and LGD by segment and horizon.</p>
      </div>
      <div class="flex align-items-center gap-2">
        <span class="text-xs text-color-secondary uppercase tracking-wide">Source run</span>
        <Dropdown
          v-model="selectedRun"
          :options="runOptions"
          optionLabel="label"
          optionValue="label"
          class="w-16rem"
        >
          <template #value>
            <div class="flex align-items-center gap-2">
              <span class="font-medium">{{ selectedRun }}</span>
              <span class="text-xs text-color-secondary font-mono">{{ currentRunMeta()?.hash }}</span>
            </div>
          </template>
          <template #option="{ option }">
            <div class="flex align-items-center justify-content-between w-full">
              <span class="font-medium">{{ option.label }}</span>
              <span class="text-xs text-color-secondary font-mono">{{ option.hash }}</span>
            </div>
          </template>
        </Dropdown>
      </div>
    </header>

    <!-- Charts row -->
    <div class="grid m-0 gap-4 mb-4 grid-cols-1 lg:grid-cols-2">
      <!-- PD term structure -->
      <div class="panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">PD term structure</div>
            <div class="text-xs text-color-secondary mt-1">By segment · marginal default probability</div>
          </div>
          <div class="legend-row">
            <span v-for="l in pdLegend" :key="l.label" class="legend-pill">
              <span class="legend-dot" :style="{ background: l.color }" />
              {{ l.label }}
            </span>
          </div>
        </div>
        <div style="height: 240px">
          <Chart type="line" :data="pdTermData" :options="baseOptions" class="h-full" />
        </div>
      </div>

      <!-- LGD term structure -->
      <div class="panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">LGD term structure</div>
            <div class="text-xs text-color-secondary mt-1">By collateral · loss given default</div>
          </div>
          <div class="legend-row">
            <span v-for="l in lgdLegend" :key="l.label" class="legend-pill">
              <span class="legend-dot" :style="{ background: l.color }" />
              {{ l.label }}
            </span>
          </div>
        </div>
        <div style="height: 240px">
          <Chart type="line" :data="lgdTermData" :options="baseOptions" class="h-full" />
        </div>
      </div>
    </div>

    <!-- Summary table -->
    <div class="panel">
      <div class="panel-head">
        <span class="panel-title">PD × LGD × EAD summary</span>
        <span class="text-xs text-color-secondary">{{ table.length }} rows</span>
      </div>
      <div class="bare-table">
        <DataTable :value="table" size="small" class="bare-table-inner">
          <Column field="segment" header="Segment" />
          <Column field="horizon" header="Horizon" />
          <Column field="pd"      header="PD" />
          <Column field="lgd"     header="LGD" />
          <Column field="ead"     header="EAD" />
          <Column header="ECL">
            <template #body="{ data }">
              <span class="font-medium">{{ data.ecl }}</span>
            </template>
          </Column>
        </DataTable>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  padding: 1.25rem 1.25rem 1rem;
}
.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}
.panel-title {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 600;
  color: var(--text-color-secondary);
}

.legend-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.legend-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--surface-ground);
  font-size: 0.75rem;
  color: var(--text-color-secondary);
}
.legend-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  display: inline-block;
}

/* Flat table */
.bare-table { margin: 0 -1.25rem -1rem; }
:deep(.bare-table-inner .p-datatable-thead > tr > th) {
  background: transparent;
  color: var(--text-color-secondary);
  font-weight: 500;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border: 0;
  border-bottom: 1px solid var(--surface-border);
  padding: 0.6rem 1.25rem;
}
:deep(.bare-table-inner .p-datatable-tbody > tr > td) {
  border: 0;
  border-bottom: 1px solid var(--surface-border);
  padding: 0.85rem 1.25rem;
  font-size: 0.875rem;
}
:deep(.bare-table-inner .p-datatable-tbody > tr:last-child > td) {
  border-bottom: 0;
}
</style>

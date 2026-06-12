<script setup>
import { ref, computed } from 'vue'

const horizon = ref(4)

const quarters = ['2023-Q1','2023-Q2','2023-Q3','2023-Q4','2024-Q1','2024-Q2','2024-Q3','2024-Q4','2025-Q1','2025-Q2','2025-Q3','2025-Q4']
const actual   = [0.0121, 0.0134, 0.0118, 0.0145, 0.0162, 0.0178, 0.0155, 0.0141, 0.0130, 0.0148, null, null]
const fitted   = [0.0115, 0.0128, 0.0122, 0.0140, 0.0158, 0.0175, 0.0160, 0.0138, 0.0132, 0.0145, null, null]
const forecast_base = [null, null, null, null, null, null, null, null, null, null, 0.0152, 0.0161]

const chartData = computed(() => {
  const fcastSlice = forecast_base.map((v, i) => i < 12 - horizon.value ? null : v)
  return {
    labels: quarters,
    datasets: [
      { label: 'Actual',   data: actual,    borderColor: '#60a5fa', backgroundColor: 'rgba(96,165,250,0.15)', pointRadius: 4, tension: 0.3 },
      { label: 'Fitted',   data: fitted,    borderColor: '#34d399', borderDash: [4, 3], pointRadius: 3, tension: 0.3, fill: false },
      { label: 'Forecast', data: fcastSlice, borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.15)', borderDash: [6, 3], pointRadius: 4, fill: false, tension: 0.3 }
    ]
  }
})

const chartOptions = {
  maintainAspectRatio: false,
  plugins: { legend: { labels: { color: '#9ca3af' } } },
  scales: {
    x: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(156,163,175,0.1)' } },
    y: { ticks: { color: '#9ca3af', callback: v => (v * 100).toFixed(2) + '%' }, grid: { color: 'rgba(156,163,175,0.1)' } }
  }
}

const forecastRows = [
  { period: '2025-Q3', forecast: '1.52%', lower: '1.21%', upper: '1.83%' },
  { period: '2025-Q4', forecast: '1.61%', lower: '1.28%', upper: '1.94%' }
]
</script>

<template>
  <div class="flex flex-column gap-4">
    <div class="surface-card border-round shadow-1 p-4">
      <div class="flex flex-wrap align-items-center justify-content-between mb-3">
        <h4 class="text-sm font-semibold m-0">Actual · Fitted · Forecast</h4>
        <div class="flex align-items-center gap-3">
          <span class="text-sm text-color-secondary">Horizon: {{ horizon }} quarter{{ horizon === 1 ? '' : 's' }}</span>
          <Slider v-model="horizon" :min="1" :max="4" :step="1" style="width: 120px" />
        </div>
      </div>
      <div style="height: 360px">
        <Chart type="line" :data="chartData" :options="chartOptions" class="h-full" />
      </div>
    </div>

    <div class="surface-card border-round shadow-1 p-4">
      <h4 class="text-sm font-semibold mb-3 m-0">Forecast values</h4>
      <DataTable :value="forecastRows" size="small" stripedRows>
        <Column field="period"   header="Period" />
        <Column field="forecast" header="Point Forecast" />
        <Column field="lower"    header="Lower 95% CI" />
        <Column field="upper"    header="Upper 95% CI" />
      </DataTable>
    </div>
  </div>
</template>

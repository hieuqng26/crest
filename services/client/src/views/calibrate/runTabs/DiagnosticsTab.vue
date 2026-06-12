<script setup>
import { computed } from 'vue'
import d from '@/views/evaluate/mock/diagnostics.json'

const rocData = computed(() => ({
  labels: d.roc_curve.fpr.map(v => v.toFixed(2)),
  datasets: [
    { label: `AUC = ${d.metrics.auc_roc}`, data: d.roc_curve.tpr, borderColor: '#60a5fa', backgroundColor: 'rgba(96,165,250,0.1)', fill: true, tension: 0.3, pointRadius: 0 },
    { label: 'Random', data: d.roc_curve.fpr, borderColor: '#6b7280', borderDash: [4, 4], pointRadius: 0, fill: false }
  ]
}))

const calibData = computed(() => ({
  labels: d.calibration_curve.mean_predicted.map(v => v.toFixed(2)),
  datasets: [
    { label: 'Model', data: d.calibration_curve.fraction_positive, borderColor: '#34d399', backgroundColor: 'rgba(52,211,153,0.1)', fill: false, tension: 0.3 },
    { label: 'Perfect', data: d.calibration_curve.mean_predicted, borderColor: '#6b7280', borderDash: [4, 4], pointRadius: 0, fill: false }
  ]
}))

const fiData = computed(() => ({
  labels: d.feature_importance.map(f => f.feature),
  datasets: [{ label: 'Importance', data: d.feature_importance.map(f => f.importance), backgroundColor: '#60a5fa' }]
}))

const chartOptions = {
  maintainAspectRatio: false,
  plugins: { legend: { labels: { color: '#9ca3af' } } },
  scales: {
    x: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(156,163,175,0.1)' } },
    y: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(156,163,175,0.1)' } }
  }
}

const kpis = [
  { label: 'AUC-ROC',   value: d.metrics.auc_roc },
  { label: 'KS',        value: d.metrics.ks },
  { label: 'Gini',      value: d.metrics.gini },
  { label: 'Accuracy',  value: d.metrics.accuracy },
  { label: 'Precision', value: d.metrics.precision },
  { label: 'Recall',    value: d.metrics.recall },
  { label: 'F1',        value: d.metrics.f1 }
]

const cm = d.confusion_matrix
</script>

<template>
  <div class="flex flex-column gap-4">
    <!-- KPI strip -->
    <div class="flex flex-wrap gap-3">
      <div v-for="kpi in kpis" :key="kpi.label"
        class="surface-card border-round px-4 py-3 shadow-1 text-center min-w-6rem">
        <div class="text-xl font-bold text-blue-400">{{ kpi.value.toFixed(3) }}</div>
        <div class="text-xs text-color-secondary mt-1">{{ kpi.label }}</div>
      </div>
      <div class="surface-card border-round px-4 py-3 shadow-1 text-center min-w-10rem"
        :class="d.hosmer_lemeshow.passed ? 'border-green-400' : 'border-red-400'" style="border-left:3px solid">
        <div class="text-sm font-bold" :class="d.hosmer_lemeshow.passed ? 'text-green-400' : 'text-red-400'">
          {{ d.hosmer_lemeshow.passed ? 'HL PASS' : 'HL FAIL' }}
        </div>
        <div class="text-xs text-color-secondary mt-1">p = {{ d.hosmer_lemeshow.p_value }}</div>
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 m-0">
      <div class="surface-card border-round shadow-1 p-4">
        <h4 class="text-sm font-semibold mb-3 m-0">ROC Curve</h4>
        <div style="height: 280px">
          <Chart type="line" :data="rocData" :options="chartOptions" class="h-full" />
        </div>
      </div>
      <div class="surface-card border-round shadow-1 p-4">
        <h4 class="text-sm font-semibold mb-3 m-0">Calibration Curve</h4>
        <div style="height: 280px">
          <Chart type="line" :data="calibData" :options="chartOptions" class="h-full" />
        </div>
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 m-0">
      <div class="surface-card border-round shadow-1 p-4">
        <h4 class="text-sm font-semibold mb-3 m-0">Feature Importance</h4>
        <div style="height: 240px">
          <Chart type="bar" :data="fiData" :options="{ ...chartOptions, indexAxis: 'y' }" class="h-full" />
        </div>
      </div>
      <div class="surface-card border-round shadow-1 p-4">
        <h4 class="text-sm font-semibold mb-3 m-0">Confusion Matrix</h4>
        <div class="flex justify-content-center align-items-center" style="height: 240px">
          <table class="text-center" style="border-collapse: separate; border-spacing: 4px">
            <thead>
              <tr>
                <th class="text-xs text-color-secondary px-3"></th>
                <th class="text-xs text-color-secondary px-3">Pred: 0</th>
                <th class="text-xs text-color-secondary px-3">Pred: 1</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td class="text-xs text-color-secondary pr-3">Act: 0</td>
                <td class="border-round p-3 font-bold text-green-400 bg-green-900 text-lg" style="min-width: 80px">{{ cm[0][0].toLocaleString() }}</td>
                <td class="border-round p-3 font-bold text-red-300 bg-red-900 text-lg"     style="min-width: 80px">{{ cm[0][1].toLocaleString() }}</td>
              </tr>
              <tr>
                <td class="text-xs text-color-secondary pr-3">Act: 1</td>
                <td class="border-round p-3 font-bold text-red-300 bg-red-900 text-lg"     style="min-width: 80px">{{ cm[1][0].toLocaleString() }}</td>
                <td class="border-round p-3 font-bold text-green-400 bg-green-900 text-lg" style="min-width: 80px">{{ cm[1][1].toLocaleString() }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

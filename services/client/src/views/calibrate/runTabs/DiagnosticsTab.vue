<script setup>
import { computed } from 'vue'

const props = defineProps({ run: { type: Object, required: true } })

const diag = computed(() => {
  try { return JSON.parse(props.run.val_metrics_json || 'null') } catch { return null }
})

const chartBase = {
  maintainAspectRatio: false,
  plugins: { legend: { labels: { color: '#9ca3af', boxWidth: 14, padding: 12 } } },
  scales: {
    x: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(156,163,175,0.08)' } },
    y: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(156,163,175,0.08)' } }
  }
}

const kpis = computed(() => {
  const d = diag.value
  if (!d) return []
  const KEYS = ['auc_roc', 'ks', 'gini', 'accuracy', 'precision', 'recall', 'f1',
                'rmse', 'mae', 'r2', 'mape', 'concordance_index']
  return KEYS
    .filter(k => typeof d[k] === 'number')
    .map(k => ({ label: k.replace(/_/g, ' ').toUpperCase(), value: d[k] }))
})

const hl = computed(() => diag.value?.hosmer_lemeshow ?? null)

const rocData = computed(() => {
  const rc = diag.value?.roc_curve
  if (!rc) return null
  return {
    labels: rc.fpr.map(v => v.toFixed(2)),
    datasets: [
      { label: `AUC = ${diag.value.auc_roc?.toFixed(3)}`, data: rc.tpr, borderColor: '#60a5fa', backgroundColor: 'rgba(96,165,250,0.08)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
      { label: 'Random', data: rc.fpr, borderColor: '#6b7280', borderDash: [5, 5], pointRadius: 0, fill: false, borderWidth: 1.5 }
    ]
  }
})

const calibData = computed(() => {
  const cc = diag.value?.calibration_curve
  if (!cc) return null
  return {
    labels: cc.mean_predicted.map(v => v.toFixed(2)),
    datasets: [
      { label: 'Model', data: cc.fraction_positive, borderColor: '#34d399', fill: false, tension: 0.3, pointRadius: 3, borderWidth: 2 },
      { label: 'Perfect', data: cc.mean_predicted, borderColor: '#6b7280', borderDash: [5, 5], pointRadius: 0, fill: false, borderWidth: 1.5 }
    ]
  }
})

const fiData = computed(() => {
  const fi = diag.value?.feature_importance
  if (!fi?.length) return null
  const sorted = [...fi].sort((a, b) => b.importance - a.importance).slice(0, 15)
  return {
    labels: sorted.map(f => f.feature),
    datasets: [{ label: 'Importance', data: sorted.map(f => f.importance), backgroundColor: 'rgba(96,165,250,0.75)', borderColor: '#60a5fa', borderWidth: 1, borderRadius: 3 }]
  }
})

const coefData = computed(() => {
  const ct = diag.value?.coef_table
  if (!ct?.length) return null
  const sorted = [...ct].sort((a, b) => Math.abs(b.coef) - Math.abs(a.coef)).slice(0, 20)
  return {
    labels: sorted.map(f => f.feature),
    datasets: [{
      label: 'Coefficient',
      data: sorted.map(f => f.coef),
      backgroundColor: sorted.map(f => f.coef >= 0 ? 'rgba(52,211,153,0.75)' : 'rgba(248,113,113,0.75)'),
      borderColor:     sorted.map(f => f.coef >= 0 ? '#34d399' : '#f87171'),
      borderWidth: 1,
      borderRadius: 3,
    }]
  }
})

const isRegression = computed(() => !!diag.value?.residuals)

const residVsFittedData = computed(() => {
  const d = diag.value
  if (!d?.residuals?.length || !d?.fitted?.length) return null
  return {
    datasets: [{
      label: 'Residual',
      data: d.fitted.map((f, i) => ({ x: f, y: d.residuals[i] })),
      backgroundColor: 'rgba(96,165,250,0.5)',
      pointRadius: d.fitted.length > 300 ? 2 : 4,
      pointHoverRadius: 5,
    }]
  }
})

const residVsFittedOptions = {
  maintainAspectRatio: false,
  animation: false,
  plugins: {
    legend: { display: false },
    tooltip: { callbacks: { label: ctx => ` fitted=${ctx.parsed.x.toFixed(4)}, resid=${ctx.parsed.y.toFixed(4)}` } }
  },
  scales: {
    x: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(156,163,175,0.08)' }, title: { display: true, text: 'Fitted value', color: '#6b7280', font: { size: 11 } } },
    y: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(156,163,175,0.08)' }, title: { display: true, text: 'Residual', color: '#6b7280', font: { size: 11 } } }
  }
}

const qqChartData = computed(() => {
  const d = diag.value
  if (!d?.qq_data) return null
  return {
    datasets: [
      {
        label: 'Residuals',
        data: d.qq_data.theoretical.map((t, i) => ({ x: t, y: d.qq_data.sample[i] })),
        backgroundColor: 'rgba(52,211,153,0.55)',
        pointRadius: d.qq_data.theoretical.length > 300 ? 2 : 3,
      },
      {
        label: 'Normal',
        data: (() => {
          const t = d.qq_data.theoretical
          const s = d.qq_data.sample
          const x0 = t[0], x1 = t[t.length - 1]
          const y0 = s[0], y1 = s[s.length - 1]
          return [{ x: x0, y: y0 }, { x: x1, y: y1 }]
        })(),
        type: 'line',
        borderColor: '#f59e0b',
        borderDash: [5, 4],
        pointRadius: 0,
        borderWidth: 1.5,
        fill: false,
      }
    ]
  }
})

const qqOptions = {
  maintainAspectRatio: false,
  animation: false,
  plugins: {
    legend: { labels: { color: '#9ca3af', boxWidth: 12 } },
    tooltip: { callbacks: { label: ctx => ` theoretical=${ctx.parsed.x.toFixed(3)}, sample=${ctx.parsed.y.toFixed(4)}` } }
  },
  scales: {
    x: { type: 'linear', ticks: { color: '#9ca3af' }, grid: { color: 'rgba(156,163,175,0.08)' }, title: { display: true, text: 'Theoretical quantiles', color: '#6b7280', font: { size: 11 } } },
    y: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(156,163,175,0.08)' }, title: { display: true, text: 'Sample quantiles', color: '#6b7280', font: { size: 11 } } }
  }
}

const residHistData = computed(() => {
  const residuals = diag.value?.residuals
  if (!residuals?.length) return null
  const N_BINS = 20
  const min = Math.min(...residuals)
  const max = Math.max(...residuals)
  const binWidth = (max - min) / N_BINS || 1
  const counts = new Array(N_BINS).fill(0)
  residuals.forEach(r => {
    const i = Math.min(Math.floor((r - min) / binWidth), N_BINS - 1)
    counts[i]++
  })
  const labels = counts.map((_, i) => (min + (i + 0.5) * binWidth).toFixed(3))
  return {
    labels,
    datasets: [{
      label: 'Count',
      data: counts,
      backgroundColor: 'rgba(167,139,250,0.7)',
      borderColor: '#a78bfa',
      borderWidth: 1,
      borderRadius: 2,
    }]
  }
})

const residHistOptions = {
  maintainAspectRatio: false,
  animation: false,
  plugins: {
    legend: { display: false },
  },
  scales: {
    x: { ticks: { color: '#9ca3af', maxTicksLimit: 8 }, grid: { color: 'rgba(156,163,175,0.08)' }, title: { display: true, text: 'Residual', color: '#6b7280', font: { size: 11 } } },
    y: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(156,163,175,0.08)' }, title: { display: true, text: 'Count', color: '#6b7280', font: { size: 11 } } }
  }
}

const cm = computed(() => diag.value?.confusion_matrix ?? null)

const cmTotal = computed(() => {
  if (!cm.value) return 0
  return cm.value[0][0] + cm.value[0][1] + cm.value[1][0] + cm.value[1][1]
})

const cmPct = (v) => cmTotal.value ? ((v / cmTotal.value) * 100).toFixed(1) + '%' : '—'
</script>

<template>
  <div v-if="diag" class="diag-root">

    <!-- KPI strip -->
    <div v-if="kpis.length" class="kpi-strip">
      <div v-for="kpi in kpis" :key="kpi.label" class="kpi-card">
        <div class="kpi-value">{{ kpi.value.toFixed(3) }}</div>
        <div class="kpi-label">{{ kpi.label }}</div>
      </div>
      <div
        v-if="hl"
        class="kpi-card hl-card"
        :class="hl.passed ? 'hl-pass' : 'hl-fail'"
      >
        <div class="kpi-value" :class="hl.passed ? 'text-green-400' : 'text-red-400'">
          {{ hl.passed ? 'PASS' : 'FAIL' }}
        </div>
        <div class="kpi-label">HL  p = {{ Number(hl.p_value).toFixed(4) }}</div>
      </div>
    </div>

    <!-- ROC + Calibration -->
    <div v-if="rocData || calibData" class="charts-grid">
      <div v-if="rocData" class="chart-card">
        <div class="chart-title">ROC Curve</div>
        <div class="chart-body">
          <Chart type="line" :data="rocData" :options="chartBase" style="height:100%;width:100%" />
        </div>
      </div>
      <div v-if="calibData" class="chart-card">
        <div class="chart-title">Calibration Curve</div>
        <div class="chart-body">
          <Chart type="line" :data="calibData" :options="chartBase" style="height:100%;width:100%" />
        </div>
      </div>
    </div>

    <!-- Feature importance / Coefficients + Confusion matrix -->
    <div class="charts-grid">
      <div v-if="fiData" class="chart-card">
        <div class="chart-title">Feature Importance</div>
        <div class="chart-body">
          <Chart type="bar" :data="fiData" :options="{ ...chartBase, indexAxis: 'y' }" style="height:100%;width:100%" />
        </div>
      </div>
      <div v-else-if="coefData" class="chart-card">
        <div class="chart-title">Coefficients <span style="font-weight:400;color:var(--text-color-secondary);font-size:0.72rem">(sorted by magnitude · green = positive · red = negative)</span></div>
        <div class="chart-body">
          <Chart type="bar" :data="coefData" :options="{ ...chartBase, indexAxis: 'y', plugins: { ...chartBase.plugins, legend: { display: false } } }" style="height:100%;width:100%" />
        </div>
      </div>

      <div v-if="cm" class="chart-card">
        <div class="chart-title">Confusion Matrix</div>
        <div class="cm-wrap">
          <div class="cm-grid">
            <!-- corner + col headers -->
            <div class="cm-corner"></div>
            <div class="cm-col-header">Predicted 0</div>
            <div class="cm-col-header">Predicted 1</div>

            <!-- row 0 -->
            <div class="cm-row-header">Actual 0</div>
            <div class="cm-cell cm-correct">
              <span class="cm-count">{{ cm[0][0].toLocaleString() }}</span>
              <span class="cm-pct">{{ cmPct(cm[0][0]) }}</span>
              <span class="cm-tag">TN</span>
            </div>
            <div class="cm-cell cm-wrong">
              <span class="cm-count">{{ cm[0][1].toLocaleString() }}</span>
              <span class="cm-pct">{{ cmPct(cm[0][1]) }}</span>
              <span class="cm-tag">FP</span>
            </div>

            <!-- row 1 -->
            <div class="cm-row-header">Actual 1</div>
            <div class="cm-cell cm-wrong">
              <span class="cm-count">{{ cm[1][0].toLocaleString() }}</span>
              <span class="cm-pct">{{ cmPct(cm[1][0]) }}</span>
              <span class="cm-tag">FN</span>
            </div>
            <div class="cm-cell cm-correct">
              <span class="cm-count">{{ cm[1][1].toLocaleString() }}</span>
              <span class="cm-pct">{{ cmPct(cm[1][1]) }}</span>
              <span class="cm-tag">TP</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Regression-specific plots -->
    <template v-if="isRegression">
      <div class="charts-grid" style="grid-template-columns: repeat(2, 1fr)">
        <div v-if="residVsFittedData" class="chart-card">
          <div class="chart-title">Residuals vs Fitted</div>
          <div class="chart-body">
            <Chart type="scatter" :data="residVsFittedData" :options="residVsFittedOptions" style="height:100%;width:100%" />
          </div>
        </div>
        <div v-if="residHistData" class="chart-card">
          <div class="chart-title">Residuals Distribution</div>
          <div class="chart-body">
            <Chart type="bar" :data="residHistData" :options="residHistOptions" style="height:100%;width:100%" />
          </div>
        </div>
      </div>
      <div v-if="qqChartData" class="chart-card">
        <div class="chart-title">Q-Q Plot <span style="font-weight:400;color:var(--text-color-secondary);font-size:0.72rem">(residuals vs normal distribution — points on the line indicate normality)</span></div>
        <div class="chart-body">
          <Chart type="scatter" :data="qqChartData" :options="qqOptions" style="height:100%;width:100%" />
        </div>
      </div>
    </template>

  </div>

  <div v-else class="empty-state">
    <i class="pi pi-chart-bar text-3xl block mb-2 opacity-40" />
    <p class="m-0">No diagnostic data available for this run.</p>
  </div>
</template>

<style scoped>
.diag-root { display: flex; flex-direction: column; gap: 1rem; }

/* KPI strip */
.kpi-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 0.625rem;
}
.kpi-card {
  flex: 1 1 7rem;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 0.75rem 1rem;
  text-align: center;
}
.hl-card { border-left-width: 3px; }
.hl-pass { border-left-color: #34d399; }
.hl-fail { border-left-color: #f87171; }
.kpi-value {
  font-size: 1.15rem;
  font-weight: 700;
  color: #60a5fa;
  letter-spacing: -0.01em;
}
.kpi-label {
  font-size: 0.68rem;
  color: var(--text-color-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-top: 0.2rem;
}

/* Chart grid — 2 cols, collapses to 1 on narrow */
.charts-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}
@media (max-width: 860px) {
  .charts-grid { grid-template-columns: 1fr; }
}

.chart-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 1rem;
  min-width: 0; /* prevent chart overflow */
}
.chart-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-color);
  margin-bottom: 0.75rem;
  letter-spacing: 0.01em;
}
.chart-body {
  height: 260px;
  position: relative;
}

/* Confusion matrix */
.cm-wrap {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 1rem 0.5rem;
}
.cm-grid {
  display: grid;
  grid-template-columns: auto 1fr 1fr;
  gap: 6px;
}
.cm-corner { }
.cm-col-header {
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-color-secondary);
  text-align: center;
  padding-bottom: 2px;
}
.cm-row-header {
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-color-secondary);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-right: 8px;
  white-space: nowrap;
}
.cm-cell {
  min-width: 100px;
  min-height: 80px;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  position: relative;
  padding: 0.75rem;
}
.cm-correct {
  background: rgba(52, 211, 153, 0.08);
  border: 1px solid rgba(52, 211, 153, 0.25);
}
.cm-wrong {
  background: rgba(248, 113, 113, 0.08);
  border: 1px solid rgba(248, 113, 113, 0.2);
}
.cm-count {
  font-size: 1.4rem;
  font-weight: 700;
  line-height: 1;
}
.cm-correct .cm-count { color: #34d399; }
.cm-wrong   .cm-count { color: #f87171; }
.cm-pct {
  font-size: 0.75rem;
  color: var(--text-color-secondary);
}
.cm-tag {
  position: absolute;
  top: 5px;
  right: 7px;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  opacity: 0.5;
}
.cm-correct .cm-tag { color: #34d399; }
.cm-wrong   .cm-tag { color: #f87171; }

/* Empty state */
.empty-state {
  text-align: center;
  padding: 4rem 2rem;
  border: 1px dashed var(--surface-border);
  border-radius: 10px;
  color: var(--text-color-secondary);
}
</style>

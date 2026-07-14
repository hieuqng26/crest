<script setup>
// Coefficient table + fit-diagnostics strip, family-aware. Renders the enriched
// `coef_table` and the matching stats bundle produced by the backend:
//   • regression → regression_stats (t-tests, F/ANOVA, VIF, AIC/BIC, DW, JB,
//     Omnibus, Breusch–Pagan, White, RESET, condition #)
//   • glm        → glm_stats        (Wald z-tests, VIF, pseudo-R², LR test, AIC/BIC…)
//   • arima      → arima_stats      (per-term z-tests, AIC/BIC/HQIC, Ljung–Box,
//     Jarque–Bera, heteroskedasticity, ADF)
// All inference is computed on the model's TRAINING data (the fit itself).
import { computed } from 'vue'

const props = defineProps({
  coefTable: { type: Array, default: () => [] },
  stats: { type: Object, default: null },
  family: { type: String, default: 'regression' }, // regression | glm | arima
})

const statKey = computed(() => (props.family === 'regression' ? 't_stat' : 'z'))
const statLabel = computed(() => (props.family === 'regression' ? 't' : 'z'))
const hasInference = computed(() => props.coefTable.some((c) => c.p_value != null))
const hasVif = computed(() => props.coefTable.some((c) => c.vif != null))
// The "approximate inference" caveat only applies to regularised regression;
// GLM/ARIMA inference comes straight from statsmodels and is exact.
const isApprox = computed(
  () => props.family === 'regression' && props.stats && props.stats.exact_inference === false,
)

const rows = computed(() => {
  const out = []
  const its = props.stats?.intercept_stats
  if (its) out.push({ feature: '(intercept)', muted: true, ...its })
  for (const c of props.coefTable) out.push({ ...c })
  return out
})

const fmt = (v, d = 4) => (v == null || !Number.isFinite(v) ? '—' : v.toFixed(d))
const fmtP = (v) => {
  if (v == null || !Number.isFinite(v)) return '—'
  return v < 0.0001 ? '<0.0001' : v.toFixed(4)
}
const stars = (p) => {
  if (p == null) return ''
  if (p < 0.001) return '***'
  if (p < 0.01) return '**'
  if (p < 0.05) return '*'
  if (p < 0.1) return '.'
  return ''
}
const sigClass = (p) => (p != null && p < 0.05 ? 'is-sig' : p != null && p < 0.1 ? 'is-marg' : '')
const vifClass = (v) => (v == null ? '' : v > 10 ? 'vif-warn' : v > 5 ? 'vif-caution' : '')

// ── Fit-statistics tiles (family-specific) ────────────────────────────────────
const num = (label, v, d = 4) => (v == null ? null : { label, value: fmt(v, d) })
const test = (label, t, okHint, failHint) =>
  !t || t.p_value == null
    ? null
    : { label, value: fmtP(t.p_value), pill: { tone: t.passed ? 'ok' : 'warn', text: t.passed ? okHint : failHint } }
const sig = (label, stat, p) =>
  stat == null
    ? null
    : { label, value: fmt(stat, 2), pill: { tone: p != null && p < 0.05 ? 'ok' : 'warn', text: `p ${fmtP(p)}` } }

const tiles = computed(() => {
  const s = props.stats
  if (!s) return []
  let list = []
  if (props.family === 'regression') {
    const dw = s.durbin_watson
    list = [
      num('R² (train)', s.r2_train),
      num('Adj R²', s.adj_r2),
      sig('F-statistic', s.f_stat, s.f_pvalue),
      num('AIC', s.aic, 1),
      num('BIC', s.bic, 1),
      num('Log-lik', s.log_likelihood, 1),
      dw == null
        ? null
        : {
            label: 'Durbin–Watson',
            value: dw.toFixed(2),
            pill: { tone: dw >= 1.5 && dw <= 2.5 ? 'ok' : 'warn', text: dw >= 1.5 && dw <= 2.5 ? 'No autocorrelation' : 'Autocorrelation' },
          },
      test('Jarque–Bera', s.jarque_bera, 'Normal', 'Non-normal'),
      test('Omnibus', s.omnibus, 'Normal', 'Non-normal'),
      test('Breusch–Pagan', s.breusch_pagan, 'Homoscedastic', 'Heteroscedastic'),
      test('White', s.white_test, 'Homoscedastic', 'Heteroscedastic'),
      test('Ramsey RESET', s.reset_test, 'Well specified', 'Misspecified'),
      s.condition_number == null
        ? null
        : { label: 'Condition no.', value: s.condition_number.toFixed(1), pill: s.condition_number > 30 ? { tone: 'warn', text: 'Multicollinearity' } : null },
    ]
  } else if (props.family === 'glm') {
    list = [
      num('Pseudo-R² (McFadden)', s.pseudo_r2_mcfadden),
      sig('LR test', s.lr_test?.stat, s.lr_test?.p_value),
      num('AIC', s.aic, 1),
      num('BIC', s.bic, 1),
      num('Log-lik', s.log_likelihood, 1),
      num('Deviance', s.deviance, 1),
      test('Hosmer–Lemeshow', s.hosmer_lemeshow, 'Good fit', 'Poor fit'),
    ]
  } else if (props.family === 'arima') {
    list = [
      num('AIC', s.aic, 1),
      num('BIC', s.bic, 1),
      num('HQIC', s.hqic, 1),
      num('Log-lik', s.log_likelihood, 1),
      test('Ljung–Box', s.ljung_box, 'No autocorrelation', 'Autocorrelation'),
      test('Jarque–Bera', s.jarque_bera, 'Normal', 'Non-normal'),
      test('Heteroskedasticity', s.heteroskedasticity, 'Homoscedastic', 'Heteroscedastic'),
      s.adf_test == null
        ? null
        : { label: 'ADF (stationarity)', value: fmtP(s.adf_test.p_value), pill: { tone: s.adf_test.passed ? 'ok' : 'warn', text: s.adf_test.passed ? 'Stationary' : 'Unit root' } },
    ]
  }
  return list.filter(Boolean)
})

// ── ANOVA table (regression only) ─────────────────────────────────────────────
const anovaRows = computed(() => {
  const a = props.stats?.anova
  if (props.family !== 'regression' || !a) return null
  return [
    { source: 'Model', ss: a.ss_model, df: a.df_model, ms: a.ms_model, f: a.f_stat, p: a.f_pvalue },
    { source: 'Residual', ss: a.ss_resid, df: a.df_resid, ms: a.ms_resid, f: null, p: null },
    { source: 'Total', ss: a.ss_total, df: (a.df_model ?? 0) + (a.df_resid ?? 0), ms: null, f: null, p: null },
  ]
})
</script>

<template>
  <div class="coef">
    <div class="chart-title">
      Coefficients
      <span v-if="isApprox" class="coef__note" title="Standard errors use the OLS formula applied to the regularised (shrunk) coefficients — treat p-values as approximate.">
        <i class="pi pi-info-circle" /> approximate inference
      </span>
    </div>

    <div v-if="tiles.length" class="coef__strip">
      <div v-for="t in tiles" :key="t.label" class="coef__stat">
        <div class="coef__stat-label">{{ t.label }}</div>
        <div class="coef__stat-value">
          {{ t.value }}
          <span v-if="t.pill" :class="['coef__pill', t.pill.tone]">{{ t.pill.text }}</span>
        </div>
      </div>
    </div>

    <div class="coef__table-wrap">
      <table class="coef__table">
        <thead>
          <tr>
            <th class="l">Term</th>
            <th>Coef.</th>
            <th v-if="hasInference">Std err</th>
            <th v-if="hasInference">{{ statLabel }}</th>
            <th v-if="hasInference">p-value</th>
            <th v-if="hasVif">VIF</th>
            <th v-if="hasInference">95% CI</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in rows" :key="i" :class="{ 'is-muted': r.muted }">
            <td class="l feat">{{ r.feature }}</td>
            <td>{{ fmt(r.coef) }}</td>
            <td v-if="hasInference">{{ fmt(r.std_err) }}</td>
            <td v-if="hasInference">{{ fmt(r[statKey], 3) }}</td>
            <td v-if="hasInference" :class="sigClass(r.p_value)">
              {{ fmtP(r.p_value) }}<span class="coef__stars">{{ stars(r.p_value) }}</span>
            </td>
            <td v-if="hasVif" :class="vifClass(r.vif)">
              <template v-if="r.vif != null">
                {{ r.vif > 100 ? r.vif.toFixed(0) : r.vif.toFixed(2) }}<span v-if="r.vif > 10" class="coef__pill warn coef__vif-pill">high</span>
              </template>
              <template v-else>—</template>
            </td>
            <td v-if="hasInference" class="ci">
              <template v-if="r.ci_lower != null">[{{ fmt(r.ci_lower, 3) }}, {{ fmt(r.ci_upper, 3) }}]</template>
              <template v-else>—</template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="hasInference" class="coef__legend">
      Significance: <code>***</code> p&lt;0.001 &nbsp; <code>**</code> p&lt;0.01 &nbsp; <code>*</code> p&lt;0.05 &nbsp; <code>.</code> p&lt;0.1
      <template v-if="hasVif"> &nbsp;·&nbsp; VIF &gt; 5 caution, &gt; 10 high multicollinearity</template>
    </div>

    <div v-if="anovaRows" class="coef__anova">
      <div class="coef__anova-title">Analysis of variance</div>
      <div class="coef__table-wrap">
        <table class="coef__table">
          <thead>
            <tr>
              <th class="l">Source</th><th>SS</th><th>df</th><th>MS</th><th>F</th><th>p-value</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in anovaRows" :key="r.source">
              <td class="l feat">{{ r.source }}</td>
              <td>{{ fmt(r.ss, 2) }}</td>
              <td>{{ r.df ?? '—' }}</td>
              <td>{{ fmt(r.ms, 2) }}</td>
              <td>{{ fmt(r.f, 2) }}</td>
              <td :class="sigClass(r.p)">{{ r.p == null ? '—' : fmtP(r.p) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.coef { display: flex; flex-direction: column; gap: 14px; }
.chart-title { font-size: 13.5px; font-weight: 700; display: flex; align-items: center; gap: 10px; }
.coef__note {
  font-size: 11px; font-weight: 600; color: var(--text-color-muted);
  display: inline-flex; align-items: center; gap: 4px; cursor: help;
}

.coef__strip {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px 18px;
}
.coef__stat-label {
  font-size: 10px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase;
  color: var(--text-color-muted); margin-bottom: 3px;
}
.coef__stat-value {
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: 14px; font-weight: 600; color: var(--ink);
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.coef__pill {
  font-family: system-ui, sans-serif; font-size: 10px; font-weight: 700;
  padding: 2px 7px; border-radius: 999px; white-space: nowrap;
}
.coef__pill.ok { background: rgba(24, 134, 71, 0.12); color: var(--success-text-color); }
.coef__pill.warn { background: rgba(196, 62, 30, 0.12); color: var(--danger-color); }

.coef__table-wrap { overflow-x: auto; }
.coef__table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.coef__table th {
  font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
  color: var(--text-color-muted); text-align: right; padding: 6px 12px 8px;
  border-bottom: 1px solid var(--surface-border-row);
}
.coef__table th.l, .coef__table td.l { text-align: left; }
.coef__table td {
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  text-align: right; padding: 7px 12px; border-bottom: 1px solid var(--surface-border-row);
  color: var(--ink-2); white-space: nowrap;
}
.coef__table tr:last-child td { border-bottom: none; }
.coef__table td.feat { font-weight: 600; color: var(--ink); }
.coef__table tr.is-muted td.feat { color: var(--text-color-muted); font-style: italic; }
.coef__table td.is-sig { color: var(--success-text-color); font-weight: 600; }
.coef__table td.is-marg { color: var(--ink); }
.coef__table td.ci { color: var(--text-color-secondary); }
.coef__table td.vif-caution { color: var(--ink); font-weight: 600; }
.coef__table td.vif-warn { color: var(--danger-color); font-weight: 600; }
.coef__stars { color: var(--yellow-chart); margin-left: 3px; }
.coef__vif-pill { margin-left: 6px; }

.coef__legend { font-size: 11px; color: var(--text-color-muted); }
.coef__legend code {
  font-family: 'IBM Plex Mono', monospace; color: var(--yellow-chart); font-weight: 700;
}

.coef__anova { margin-top: 4px; }
.coef__anova-title {
  font-size: 10px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase;
  color: var(--text-color-muted); margin-bottom: 8px;
}
</style>

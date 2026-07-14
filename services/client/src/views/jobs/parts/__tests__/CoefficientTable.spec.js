import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import CoefficientTable from '../CoefficientTable.vue'

const regressionCoef = [
  { feature: 'inflation_rate', coef: 1.42, std_err: 0.11, t_stat: 12.9, p_value: 0.0000004, ci_lower: 1.2, ci_upper: 1.64, vif: 2.1 },
  { feature: 'oil_price', coef: -0.03, std_err: 0.04, t_stat: -0.75, p_value: 0.45, ci_lower: -0.11, ci_upper: 0.05, vif: 14.6 },
]
const regressionStats = {
  r2_train: 0.62,
  adj_r2: 0.6,
  exact_inference: false,
  f_stat: 88.4,
  f_pvalue: 0.0,
  aic: 512.3,
  bic: 528.1,
  log_likelihood: -253.2,
  condition_number: 42.1,
  durbin_watson: 1.98,
  skew: 0.1,
  kurtosis: -0.2,
  intercept_stats: { coef: 3.1, std_err: 0.2, t_stat: 15.5, p_value: 0.0, ci_lower: 2.7, ci_upper: 3.5 },
  jarque_bera: { stat: 1.2, p_value: 0.55, passed: true },
  omnibus: { stat: 0.9, p_value: 0.63, passed: true },
  breusch_pagan: { stat: 9.9, p_value: 0.001, passed: false },
  white_test: { stat: 12.0, p_value: 0.02, passed: false },
  reset_test: { stat: 0.8, p_value: 0.46, passed: true },
  anova: { ss_model: 758.6, ss_resid: 76.9, ss_total: 835.5, df_model: 2, df_resid: 296, ms_model: 379.3, ms_resid: 0.26, f_stat: 88.4, f_pvalue: 0.0 },
}

describe('CoefficientTable — regression', () => {
  it('renders coefficient rows, stars, VIF column and approximate-inference note', () => {
    const w = mount(CoefficientTable, { props: { coefTable: regressionCoef, stats: regressionStats, family: 'regression' } })
    const text = w.text()
    expect(text).toContain('(intercept)')
    expect(text).toContain('inflation_rate')
    expect(text).toContain('***')
    expect(text).toContain('<0.0001')
    expect(text).toContain('approximate inference')
    // VIF column present; the high-VIF row (>10) shows a "high" warn pill.
    expect(text.toUpperCase()).toContain('VIF')
    const warnPills = w.findAll('.coef__pill.warn')
    expect(warnPills.some((p) => p.text() === 'high')).toBe(true)
    expect(w.find('td.vif-warn').exists()).toBe(true)
  })

  it('renders the extended stat tiles and the ANOVA table', () => {
    const w = mount(CoefficientTable, { props: { coefTable: regressionCoef, stats: regressionStats, family: 'regression' } })
    const text = w.text()
    for (const label of ['Adj R²', 'AIC', 'BIC', 'Omnibus', 'White', 'Ramsey RESET', 'Durbin–Watson']) {
      expect(text).toContain(label)
    }
    // ANOVA table with the three sources.
    expect(text).toContain('Analysis of variance')
    expect(text).toContain('Model')
    expect(text).toContain('Residual')
    expect(text).toContain('Total')
  })

  it('hides inference/VIF columns when coef_table has no p-values', () => {
    const w = mount(CoefficientTable, {
      props: { coefTable: [{ feature: 'x', coef: 1.0 }], stats: null, family: 'regression' },
    })
    expect(w.find('td.ci').exists()).toBe(false)
    expect(w.text()).not.toContain('Significance:')
  })
})

describe('CoefficientTable — glm', () => {
  const glmCoef = [{ feature: 'x1', coef: 1.1, std_err: 0.14, z: 7.8, p_value: 0.0, ci_lower: 0.8, ci_upper: 1.4, vif: 1.0 }]
  const glmStats = {
    pseudo_r2_mcfadden: 0.22,
    aic: 436.1,
    bic: 452.0,
    log_likelihood: -214.0,
    deviance: 428.1,
    lr_test: { stat: 118.5, df: 3, p_value: 1e-25, passed: true },
    hosmer_lemeshow: { stat: 6.1, p_value: 0.63, passed: true },
    intercept_stats: { coef: 0.45, std_err: 0.12, z: 3.7, p_value: 0.0002, ci_lower: 0.21, ci_upper: 0.69 },
  }

  it('labels the stat column z and shows GLM-specific tiles', () => {
    const w = mount(CoefficientTable, { props: { coefTable: glmCoef, stats: glmStats, family: 'glm' } })
    const text = w.text()
    expect(text).toContain('Pseudo-R² (McFadden)')
    expect(text).toContain('LR test')
    expect(text).toContain('Hosmer–Lemeshow')
    // z header (not t), and no approximate-inference caveat for GLM.
    expect(w.findAll('th').some((th) => th.text() === 'z')).toBe(true)
    expect(text).not.toContain('approximate inference')
    // No ANOVA table outside regression.
    expect(text).not.toContain('Analysis of variance')
  })
})

describe('CoefficientTable — arima', () => {
  const arimaCoef = [{ feature: 'ar.L1', coef: 0.59, std_err: 0.1, z: 5.9, p_value: 0.0, ci_lower: 0.39, ci_upper: 0.78 }]
  const arimaStats = {
    aic: 555.0,
    bic: 564.9,
    hqic: 559.0,
    log_likelihood: -274.5,
    ljung_box: { stat: 12.6, p_value: 0.24, passed: true },
    jarque_bera: { stat: 4.4, p_value: 0.11, passed: true },
    heteroskedasticity: { stat: 1.3, p_value: 0.32, passed: true },
    adf_test: { stat: -1.9, p_value: 0.29, passed: false, n_diff: 1 },
  }

  it('shows ARIMA tiles including HQIC, Ljung–Box and ADF', () => {
    const w = mount(CoefficientTable, { props: { coefTable: arimaCoef, stats: arimaStats, family: 'arima' } })
    const text = w.text()
    expect(text).toContain('ar.L1')
    expect(text).toContain('HQIC')
    expect(text).toContain('Ljung–Box')
    expect(text).toContain('ADF (stationarity)')
    // ADF failed → "Unit root" warn pill.
    expect(text).toContain('Unit root')
  })
})

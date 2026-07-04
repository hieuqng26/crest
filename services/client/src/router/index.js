import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from '@/layout/AppLayout.vue'
import NotFound from '@/views/auth/NotFound.vue'
import Login from '@/views/auth/Login.vue'
import Access from '@/views/auth/Access.vue'
import Error from '@/views/auth/Error.vue'
import ComingSoon from '@/views/_ComingSoon.vue'
import store from '@/store'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: { name: 'dashboard' } },
    {
      path: '/',
      component: AppLayout,
      children: [
        { path: '/dashboard', name: 'dashboard', component: () => import('@/views/Dashboard.vue'), meta: { requiresAuth: true } },

        // Datasets
        { path: '/datasets',      name: 'datasets',      component: () => import('@/views/ingest/Datasets.vue'),    meta: { requiresAuth: true, requiresPerm: 'dataset:read' } },
        { path: '/datasets/:id',  name: 'dataset_view',  component: () => import('@/views/ingest/DatasetView.vue'), meta: { requiresAuth: true, requiresPerm: 'dataset:read' }, props: true },

        // Model (v2) — new consolidated screens, built in a follow-up pass
        { path: '/model/new',     name: 'model_new',     component: ComingSoon, meta: { requiresAuth: true, requiresPerm: 'calibration:read', eyebrow: 'MODEL', title: 'New Model' } },
        { path: '/model/results', name: 'model_results', component: ComingSoon, meta: { requiresAuth: true, requiresPerm: 'calibration:read', eyebrow: 'MODEL', title: 'Model Results' } },

        // Models (v1 — superseded by New Model / Model Results; deleted once those land)
        { path: '/models',         name: 'models',               component: () => import('@/views/configure/Models.vue'),                         meta: { requiresAuth: true, requiresPerm: 'model_config:read' } },
        { path: '/configurations', name: 'configurations',       component: () => import('@/views/configure/Configurations.vue'),                 meta: { requiresAuth: true, requiresPerm: 'model_config:read' } },

        // Calibrate (v1 — superseded by New Model / Job History; deleted once those land)
        { path: '/calibrate/new',    name: 'calibrate_new',  component: () => import('@/views/calibrate/CalibrateNew.vue'),  meta: { requiresAuth: true, requiresPerm: 'calibration:read' } },
        { path: '/calibrate/jobs',   name: 'calibrate_jobs', component: () => import('@/views/calibrate/CalibrateJobs.vue'), meta: { requiresAuth: true, requiresPerm: 'calibration:read' } },
        { path: '/calibrate/:run_id', name: 'calibrate_run', component: () => import('@/views/calibrate/CalibrateRun.vue'),  meta: { requiresAuth: true, requiresPerm: 'calibration:read' } },

        // Evaluate (legacy URL → redirects to unified run page)
        { path: '/evaluate/:run_id', name: 'evaluate_run', component: () => import('@/views/evaluate/EvaluateRedirect.vue'), meta: { requiresAuth: true } },

        // Forecast module (v1 — superseded by Financial Forecast / Job History; deleted once those land)
        { path: '/forecast/jobs',    name: 'forecast_jobs', component: () => import('@/views/forecast/ForecastJobs.vue'),    meta: { requiresAuth: true, requiresPerm: 'forecast:read' } },
        { path: '/forecast/new',     name: 'forecast_new',  component: () => import('@/views/forecast/ForecastNew.vue'),     meta: { requiresAuth: true, requiresPerm: 'forecast:read' } },
        { path: '/forecast/:run_id', name: 'forecast_run',  component: () => import('@/views/forecast/ForecastRunView.vue'), meta: { requiresAuth: true, requiresPerm: 'forecast:read' } },

        // Analysis (v2)
        { path: '/analysis/heatmap',  name: 'analysis_heatmap', component: ComingSoon, meta: { requiresAuth: true, requiresPerm: 'credit_risk:read', eyebrow: 'ANALYSIS', title: 'Sector Heatmap' } },
        { path: '/analysis/forecast', name: 'analysis_forecast', component: ComingSoon, meta: { requiresAuth: true, requiresPerm: 'credit_risk:read', eyebrow: 'ANALYSIS', title: 'Financial Forecast' } },

        // Credit Risk
        { path: '/credit-risk/new',          name: 'credit_risk_new',         component: () => import('@/views/credit_risk/CreditRiskNew.vue'),        meta: { requiresAuth: true, requiresPerm: 'credit_risk:read' } },
        { path: '/credit-risk/jobs',         name: 'credit_risk_jobs',        component: () => import('@/views/credit_risk/CreditRiskJobs.vue'),       meta: { requiresAuth: true, requiresPerm: 'credit_risk:read' } },
        { path: '/credit-risk/runs/:run_id', name: 'credit_risk_run',         component: () => import('@/views/credit_risk/CreditRiskRunView.vue'),    meta: { requiresAuth: true, requiresPerm: 'credit_risk:read' } },
        { path: '/credit-risk/ecl',          name: 'credit_risk_ecl',         component: () => import('@/views/credit_risk/CreditRiskECL.vue'),        meta: { requiresAuth: true, requiresPerm: 'credit_risk:read' } },
        { path: '/credit-risk/pd-lgd',       name: 'credit_risk_pd_lgd',      component: () => import('@/views/credit_risk/CreditRiskPdLgd.vue'),     meta: { requiresAuth: true, requiresPerm: 'credit_risk:read' } },
        { path: '/credit-risk/transitions',  name: 'credit_risk_transitions', component: () => import('@/views/credit_risk/CreditRiskTransitions.vue'), meta: { requiresAuth: true, requiresPerm: 'credit_risk:read' } },

        // Jobs (v2) — unifies Calibration/Forecast/Credit-Risk job lists
        { path: '/jobs',           name: 'jobs_history', component: ComingSoon, meta: { requiresAuth: true, requiresPerm: 'calibration:read', eyebrow: 'JOBS', title: 'Job History' } },
        { path: '/jobs/:run_id',   name: 'jobs_detail',  component: ComingSoon, meta: { requiresAuth: true, requiresPerm: 'calibration:read', eyebrow: 'JOBS', title: 'Job Detail' } },

        // System
        { path: '/uam',             name: 'uam',             component: () => import('@/views/users/UAM.vue'),              meta: { requiresAuth: true, requiresPerm: 'user:read' } },
        { path: '/role-management', name: 'role-management', component: () => import('@/views/admin/RoleManagement.vue'),   meta: { requiresAuth: true, requiresPerm: 'role:read' } },
        { path: '/log',             name: 'log',             component: () => import('@/views/AuditLog.vue'),               meta: { requiresAuth: true, requiresPerm: 'auditlog:read' } },
      ]
    },
    { path: '/pages/notfound', name: 'notfound',     component: NotFound },
    { path: '/auth/login',     name: 'login',        component: Login },
    { path: '/auth/access',    name: 'accessDenied', component: Access },
    { path: '/auth/error',     name: 'error',        component: Error },
    { path: '/:pathMatch(.*)*', component: NotFound, meta: { status: 404 } }
  ]
})

router.beforeEach(async (to, from, next) => {
  const needsAuth = to.matched.some((r) => r.meta.requiresAuth)
  if (!needsAuth) return next()

  if (!store.getters.isAuthenticated) {
    const ok = await store.dispatch('fetchMe')
    if (!ok) return next({ name: 'login', query: { redirect: to.fullPath } })
  }

  const permRoute = to.matched.find((r) => r.meta.requiresPerm)
  if (permRoute && !store.getters.can(permRoute.meta.requiresPerm)) {
    return next({ name: 'accessDenied' })
  }

  return next()
})

export default router

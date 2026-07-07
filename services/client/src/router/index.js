import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from '@/layout/AppLayout.vue'
import NotFound from '@/views/auth/NotFound.vue'
import Login from '@/views/auth/Login.vue'
import Access from '@/views/auth/Access.vue'
import Error from '@/views/auth/Error.vue'
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

        // Model (v2) — New Model launches training; Model Results browses trained models
        { path: '/model/new',            name: 'model_new',              component: () => import('@/views/model/ModelNew.vue'),                  meta: { requiresAuth: true, requiresPerm: 'calibration:read' } },
        { path: '/model/new/features',   name: 'model_feature_selection', component: () => import('@/views/model/AdvancedFeatureSelection.vue'), meta: { requiresAuth: true, requiresPerm: 'calibration:read' } },
        { path: '/model/configurations', name: 'model_configurations',    component: () => import('@/views/model/ModelConfigurations.vue'),      meta: { requiresAuth: true, requiresPerm: 'model_config:read' } },
        { path: '/model/results',        name: 'model_results',          component: () => import('@/views/model/ModelResults.vue'),             meta: { requiresAuth: true, requiresPerm: 'calibration:read' } },

        // Analysis (v2)
        { path: '/analysis/heatmap',  name: 'analysis_heatmap',  component: () => import('@/views/credit_risk/CreditRiskHeatmap.vue'),  meta: { requiresAuth: true, requiresPerm: 'credit_risk:read' } },
        { path: '/analysis/forecast', name: 'analysis_forecast', component: () => import('@/views/credit_risk/CreditRiskForecast.vue'), meta: { requiresAuth: true, requiresPerm: 'credit_risk:read' } },

        // Credit Risk (v1 — jobs list/detail superseded by Job History/Detail)
        { path: '/credit-risk/ecl',          name: 'credit_risk_ecl',         component: () => import('@/views/credit_risk/CreditRiskECL.vue'),        meta: { requiresAuth: true, requiresPerm: 'credit_risk:read' } },
        { path: '/credit-risk/pd-lgd',       name: 'credit_risk_pd_lgd',      component: () => import('@/views/credit_risk/CreditRiskPdLgd.vue'),     meta: { requiresAuth: true, requiresPerm: 'credit_risk:read' } },
        { path: '/credit-risk/transitions',  name: 'credit_risk_transitions', component: () => import('@/views/credit_risk/CreditRiskTransitions.vue'), meta: { requiresAuth: true, requiresPerm: 'credit_risk:read' } },

        // Jobs (v2) — unifies Calibration/Forecast/Credit-Risk job lists + detail
        { path: '/jobs',                name: 'jobs_history',  component: () => import('@/views/jobs/JobHistory.vue'),    meta: { requiresAuth: true, requiresPerm: 'calibration:read' } },
        { path: '/jobs/workflow/:run_id', name: 'jobs_workflow', component: () => import('@/views/jobs/WorkflowDetail.vue'), meta: { requiresAuth: true, requiresPerm: 'calibration:read' } },
        { path: '/jobs/:kind/:run_id',  name: 'jobs_detail',   component: () => import('@/views/jobs/JobDetail.vue'),     meta: { requiresAuth: true, requiresPerm: 'calibration:read' } },

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

import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from '@/layout/AppLayout.vue'
import Home from '@/views/Home.vue'
import NotFound from '@/views/auth/NotFound.vue'
import Login from '@/views/auth/Login.vue'
import Access from '@/views/auth/Access.vue'
import Error from '@/views/auth/Error.vue'
import store from '@/store'
import { isValidJwt } from '@/utils'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: Home, meta: { requiresAuth: true } },
    {
      path: '/',
      component: AppLayout,
      children: [
        { path: '/dashboard', name: 'dashboard', component: () => import('@/views/Dashboard.vue'), meta: { requiresAuth: true } },

        // Datasets
        { path: '/datasets',      name: 'datasets',      component: () => import('@/views/ingest/Datasets.vue'),    meta: { requiresAuth: true } },
        { path: '/datasets/:id',  name: 'dataset_view',  component: () => import('@/views/ingest/DatasetView.vue'), meta: { requiresAuth: true }, props: true },

        // Models
        { path: '/models',          name: 'models',         component: () => import('@/views/configure/Models.vue'),         meta: { requiresAuth: true } },
        { path: '/configurations',  name: 'configurations', component: () => import('@/views/configure/Configurations.vue'), meta: { requiresAuth: true } },

        // Calibrate
        { path: '/calibrate/new',         name: 'calibrate_new',  component: () => import('@/views/calibrate/CalibrateNew.vue'),  meta: { requiresAuth: true } },
        { path: '/calibrate/jobs',         name: 'calibrate_jobs', component: () => import('@/views/calibrate/CalibrateJobs.vue'), meta: { requiresAuth: true } },
        { path: '/calibrate/:run_id',      name: 'calibrate_run',  component: () => import('@/views/calibrate/CalibrateRun.vue'),  meta: { requiresAuth: true } },

        // Evaluate (legacy URL → redirects to unified run page)
        { path: '/evaluate/:run_id', name: 'evaluate_run', component: () => import('@/views/evaluate/EvaluateRedirect.vue'), meta: { requiresAuth: true } },

        // Forecast (legacy URL → redirects to unified run page)
        { path: '/forecast/:run_id', name: 'forecast_run', component: () => import('@/views/forecast/ForecastRedirect.vue'), meta: { requiresAuth: true } },

        // Credit Risk
        { path: '/credit-risk/new',       name: 'credit_risk_new',  component: () => import('@/views/credit_risk/CreditRiskNew.vue'),     meta: { requiresAuth: true } },
        { path: '/credit-risk/jobs',      name: 'credit_risk_jobs', component: () => import('@/views/credit_risk/CreditRiskJobs.vue'),    meta: { requiresAuth: true } },
        { path: '/credit-risk/runs/:run_id', name: 'credit_risk_run', component: () => import('@/views/credit_risk/CreditRiskRunView.vue'), meta: { requiresAuth: true } },
        { path: '/credit-risk/ecl',         name: 'credit_risk_ecl',         component: () => import('@/views/credit_risk/CreditRiskECL.vue'),         meta: { requiresAuth: true } },
        { path: '/credit-risk/pd-lgd',      name: 'credit_risk_pd_lgd',      component: () => import('@/views/credit_risk/CreditRiskPdLgd.vue'),        meta: { requiresAuth: true } },
        { path: '/credit-risk/transitions', name: 'credit_risk_transitions',  component: () => import('@/views/credit_risk/CreditRiskTransitions.vue'),  meta: { requiresAuth: true } },
        { path: '/credit-risk/data',        name: 'credit_risk_data',         component: () => import('@/views/credit_risk/CreditRiskData.vue'),          meta: { requiresAuth: true } },

        // System
        { path: '/uam', name: 'uam', component: () => import('@/views/users/UAM.vue'), meta: { requiresAuth: true } },
        { path: '/log', name: 'log', component: () => import('@/views/AuditLog.vue'),  meta: { requiresAuth: true } },
      ]
    },
    { path: '/pages/notfound', name: 'notfound',     component: NotFound },
    { path: '/auth/login',     name: 'login',        component: Login },
    { path: '/auth/access',    name: 'accessDenied', component: Access },
    { path: '/auth/error',     name: 'error',        component: Error },
    { path: '/:pathMatch(.*)*', component: NotFound, meta: { status: 404 } }
  ]
})

router.beforeEach((to, from, next) => {
  if (to.name === 'login') {
    const token = store.state.jwt?.accessToken
    if (token && isValidJwt(token)) return next({ name: 'dashboard' })
  }
  if (to.matched.some((r) => r.meta.requiresAuth)) {
    if (!store.state.jwt) return next({ name: 'login', params: { redirect: to.fullPath } })
    if (!isValidJwt(store.state.jwt.accessToken)) {
      store.dispatch('refreshToken')
        .then(() => {
          const t = store.state.jwt?.accessToken
          return t && isValidJwt(t) ? next() : next({ name: 'login', params: { redirect: to.fullPath } })
        })
        .catch(() => next({ name: 'login', params: { redirect: to.fullPath } }))
    } else {
      return next()
    }
  } else {
    return next()
  }
})

export default router

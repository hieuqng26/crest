import { createRouter, createWebHistory } from 'vue-router'
import Home from '@/views/Home.vue'
import AppLayout from '@/layout/AppLayout.vue'
import Dashboard from '@/views/Dashboard.vue'
import AuditLog from '@/views/AuditLog.vue'
import UAM from '@/views/users/UAM.vue'
import NotFound from '@/views/auth/NotFound.vue'
import Login from '@/views/auth/Login.vue'
import Access from '@/views/auth/Access.vue'
import Error from '@/views/auth/Error.vue'
import store from '@/store'
import { isValidJwt } from '@/utils'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: Home,
      meta: { requiresAuth: true }
    },
    {
      path: '/',
      component: AppLayout,
      children: [
        {
          path: '/dashboard',
          name: 'dashboard',
          component: Dashboard,
          meta: { requiresAuth: true }
        },
        //==========System admin==========
        {
          path: '/uam',
          name: 'uam',
          component: UAM,
          meta: {
            requiresAuth: true
          }
        },
        {
          path: '/log',
          name: 'log',
          component: AuditLog,
          meta: {
            requiresAuth: true
          }
        }
      ]
    },
    //==========Exceptions==========
    {
      path: '/pages/notfound',
      name: 'notfound',
      component: NotFound
    },
    {
      path: '/auth/login',
      name: 'login',
      component: Login
    },
    {
      path: '/auth/access',
      name: 'accessDenied',
      component: Access
    },
    {
      path: '/auth/error',
      name: 'error',
      component: Error
    },
    // Catch-all route for 404
    {
      path: '/:pathMatch(.*)*',
      component: NotFound,
      meta: { status: 404 }
    }
  ]
})

router.beforeEach((to, from, next) => {
  // if to is login and user is already logged in, redirect to dashboard
  if (to.name === 'login') {
    const token = store.state.jwt?.accessToken
    if (token && isValidJwt(token)) {
      return next({ name: 'dashboard' })
    }
  }

  if (to.matched.some((record) => record.meta.requiresAuth)) {
    // if no token exists, redirect to login
    if (!store.state.jwt) {
      return next({ name: 'login', params: { redirect: to.fullPath } })
    }
    // if access token expires
    else if (!isValidJwt(store.state.jwt.accessToken)) {
      // attempt to refresh it
      store
        .dispatch('refreshToken')
        .then(() => {
          const newAccessToken = store.state.jwt?.accessToken
          if (!newAccessToken || !isValidJwt(newAccessToken)) {
            return next({ name: 'login', params: { redirect: to.fullPath } })
          } else {
            return next()
          }
        })
        .catch(() => {
          // if refresh token fails, redirect to login
          return next({ name: 'login', params: { redirect: to.fullPath } })
        })
    } else {
      // if access token is valid, continue
      return next()
    }
  } else {
    // if route does not require auth, continue
    return next()
  }
})

export default router

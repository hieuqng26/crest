import axios from 'axios'
import store from '@/store'
import router from '@/router'
import { getCookie } from '@/utils/cookies'

const API_URL = (import.meta.env.VITE_API_URL || '') + '/api'

export const httpClient = axios.create({ baseURL: API_URL, withCredentials: true })

// Attach CSRF header for state-changing requests (double-submit cookie).
httpClient.interceptors.request.use((config) => {
  const method = (config.method || 'get').toLowerCase()
  if (method !== 'get' && method !== 'head' && method !== 'options') {
    const isRefresh = (config.url || '').includes('/auth/refresh')
    const token = getCookie(isRefresh ? 'csrf_refresh_token' : 'csrf_access_token')
    if (token) config.headers['X-CSRF-TOKEN'] = token
  }
  return config
})

let isRefreshing = false
let subscribers = []
const onRefreshed = () => { subscribers.forEach((cb) => cb()); subscribers = [] }

httpClient.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config
    const status = error.response?.status
    const url = original?.url || ''
    if (status !== 401 || original._retry || url.includes('/auth/refresh') || url.includes('/auth/login')) {
      return Promise.reject(error)
    }
    if (isRefreshing) {
      return new Promise((resolve) => subscribers.push(() => { original._retry = true; resolve(httpClient(original)) }))
    }
    original._retry = true
    isRefreshing = true
    try {
      await httpClient.post('/auth/refresh')
      isRefreshing = false
      onRefreshed()
      return httpClient(original)
    } catch (e) {
      isRefreshing = false
      subscribers = []
      store.dispatch('logout', true)
      router.push({ name: 'login' })
      return Promise.reject(e)
    }
  }
)

export default httpClient

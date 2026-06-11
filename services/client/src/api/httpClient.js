import axios from 'axios'
import store from '@/store'
import router from '@/router'

const API_URL = (import.meta.env.VITE_API_URL || '') + '/api'

const httpClient = axios.create({
  baseURL: API_URL,
  withCredentials: true,
  xsrfCookieName: 'csrf_access_token'
})

const setAuthHeader = (jwt) => ({ Authorization: `Bearer ${jwt}` })

let isRefreshing = false
let refreshSubscribers = []

const onRefreshed = (token) => {
  refreshSubscribers.forEach((callback) => callback(token))
}

const addRefreshSubscriber = (callback) => {
  refreshSubscribers.push(callback)
}

// Refresh token logic in case of 401 Unauthorized errors
httpClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // login credentials are invalid
    if (
      error.response?.status === 401 &&
      error.response?.data?.message?.toUpperCase().includes('USERNAME') &&
      error.response?.data?.message?.toUpperCase().includes('PASSWORD')
    ) {
      const errorAnnotated = new Error(error.response?.data?.message || 'Unauthorized')
      errorAnnotated.response = error.response
      errorAnnotated.status = error.response?.status
      return Promise.reject(errorAnnotated)
    }

    // another new login was made
    if (
      error.response?.status === 401 &&
      error.response?.data?.message?.toUpperCase().includes('NEW') &&
      error.response?.data?.message?.toUpperCase().includes('LOGIN')
    ) {
      const errorAnnotated = new Error(error.response?.data?.message || 'Unauthorized')
      errorAnnotated.response = error.response
      errorAnnotated.status = error.response?.status
      // jump to login page
      sessionStorage.clear() // Clear client session
      const doNotCallBackend = true
      store.dispatch('logout', doNotCallBackend) // Clear server session
      router.push({ path: '/auth/login', query: { errorMessage: errorAnnotated.message } })
      return Promise.reject(errorAnnotated)
    }

    // handle 401 that is authentication error
    if (error.response?.status === 401 && error.response?.data?.type === 'Authentication Error') {
      const errorAnnotated = new Error(error.response?.data?.message || 'Unauthorized')
      errorAnnotated.response = error.response
      errorAnnotated.status = error.response?.status
      return Promise.reject(errorAnnotated)
    }

    // Check if the error is due to an unauthorized request and if the request has not been retried yet
    if (error.response?.status === 401 && !originalRequest._retry) {
      // If no refresh is in progress, start a new refresh
      if (!isRefreshing) {
        isRefreshing = true
        originalRequest._retry = true
        httpClient.defaults.xsrfCookieName = 'csrf_refresh_token'
        try {
          // Attempt to refresh the token, but avoid repeated call for refreshToken
          if (originalRequest.url != '/auth/refresh') {
            await store.dispatch('refreshToken')
          } else {
            return Promise.reject(new Error('Token refresh failed'))
          }
          const newAccessToken = store.state.jwt.accessToken
          isRefreshing = false

          // Notify all subscribers with the new token and clear the subscribers list
          onRefreshed(newAccessToken)
          refreshSubscribers = []

          // Update the original request with the new token and retry it
          originalRequest.headers['Authorization'] = `Bearer ${newAccessToken}`
          httpClient.defaults.xsrfCookieName = 'csrf_access_token'
          return httpClient(originalRequest)
        } catch (refreshError) {
          isRefreshing = false
          const refreshErrorAnnotated = new Error(refreshError.message || 'Token refresh failed')
          refreshErrorAnnotated.response = error.response
          refreshErrorAnnotated.status = error.response?.status
          return Promise.reject(refreshErrorAnnotated)
        }
      } else {
        // If a refresh is already in progress, add the request to the subscribers list
        return new Promise((resolve) => {
          addRefreshSubscriber((token) => {
            originalRequest.headers['Authorization'] = `Bearer ${token}`
            resolve(httpClient(originalRequest))
          })
        })
      }
    }
    const errorAnnotated = new Error(error.message || 'Request failed')
    errorAnnotated.response = error.response
    errorAnnotated.status = error.response?.status
    return Promise.reject(errorAnnotated)
  }
)

export { API_URL, httpClient, setAuthHeader }

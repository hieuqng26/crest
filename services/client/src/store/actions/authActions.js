import { authAPI } from '@/api'

export const authActions = {
  async login(context, credentials) {
    const { data } = await authAPI.login(credentials)
    context.commit('setAuth', { user: data.user, permissions: data.permissions })
    return data
  },
  async fetchMe(context) {
    try {
      const { data } = await authAPI.me()
      context.commit('setAuth', { user: data.user, permissions: data.permissions })
      return true
    } catch {
      context.commit('clearAuth')
      return false
    }
  },
  async logout(context, skipBackend = false) {
    if (!skipBackend) { try { await authAPI.logout() } catch { /* ignore */ } }
    context.commit('clearAuth')
  }
}

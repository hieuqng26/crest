import { authAPI } from '@/api'

export const authActions = {
  login(context, userData) {
    return new Promise((resolve, reject) => {
      authAPI
        .login(userData)
        .then((response) => {
          context.commit('setLoginData', response.data)
          return resolve(response)
        })
        .catch((error) => {
          const errorAnnotated = new Error(error?.message || 'Login failed')
          errorAnnotated.response = error.response
          errorAnnotated.status = error.response?.status
          return reject(errorAnnotated)
        })
    })
  },
  refreshToken(context) {
    return new Promise((resolve, reject) => {
      const token = context.state.jwt?.refreshToken
      // if token s not valid, reject the promise with code 401
      if (!token) {
        const message = 'Unauthorized: No refresh token available'
        var error = new Error(message)
        error.message = message
        error.status = { response: { status: 401 } }
        return reject(error)
      }
      authAPI
      .refreshToken(token)
      .then((response) => {
        context.commit('setAccessToken', response.data.accessToken)
        return resolve(response)
      })
      .catch((error) => {
        const errorAnnotated = new Error(error?.message || 'Token refresh failed')
        errorAnnotated.response = error.response
        errorAnnotated.status = error.response?.status
        return reject(errorAnnotated)
      })
    })
  },
  logout(context, doNotCallBackend = false) {
    // clear server-side
    if (!doNotCallBackend) {
      authAPI.logout(context.state.jwt.accessToken)
    }

    // clear client-side
    context.state.jwt = null
    context.state.currentUser = null
    localStorage.removeItem('vuex')
  }
}

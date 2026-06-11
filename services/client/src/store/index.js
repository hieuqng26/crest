import { createStore } from 'vuex'
import createPersistedState from 'vuex-persistedstate'
import { actions } from './actions'
import { isValidJwt } from '@/utils'

const state = {
  // initialize state from local storage to enable user to stay logged in
  currentUser: null,
  jwt: null,
  ROLES_PER_MODULE: null
}

const getters = {
  isAuthenticated(state) {
    const accessToken = state.jwt?.accessToken
    return accessToken && isValidJwt(accessToken)
  },
  getCurrentUser(state) {
    return JSON.parse(state.currentUser)
  },
  getModulesByRole:
    (state, roles_in = null) =>
    (roleType) => {
      const roles = !roles_in ? roles_in : state.roles
      const currentUser = state.currentUser
        ? JSON.parse(state.currentUser)
        : null
      if (!currentUser || !roles) {
        return []
      }
      const userRole = currentUser.role
      if (!roles[userRole]) {
        return []
      }
      if (roleType == '*') {
        return (
          roles[userRole]['read'] ||
          roles[userRole]['write'] ||
          roles[userRole]['execute'] ||
          []
        )
      } else {
        return roles[userRole][roleType] || []
      }
    }
}

const mutations = {
  setLoginData(state, payload) {
    state.jwt = payload.jwt
    state.currentUser = JSON.stringify(payload.user)
  },
  setAccessToken(state, accessToken) {
    state.jwt.accessToken = accessToken
  },
  setRoles(state, payload) {
    const { roles } = payload
    state.roles = roles
    state.ROLES_PER_MODULE = {}
    for (const role_name in roles) {
      const modulesPerPermission = roles[role_name]
      for (const perm in modulesPerPermission) {
        const modules = modulesPerPermission[perm]
        for (const module of modules) {
          if (!state.ROLES_PER_MODULE.hasOwnProperty(module)) {
            state.ROLES_PER_MODULE[module] = [role_name]
          } else if (!state.ROLES_PER_MODULE[module].includes(role_name)) {
            state.ROLES_PER_MODULE[module].push(role_name)
          }
        }
      }
    }
  }
}

const store = createStore({
  state,
  getters,
  actions,
  mutations,
  plugins: [
    createPersistedState({
      storage: window.localStorage,
      paths: ['currentUser', 'jwt']
    })
  ]
})

export default store

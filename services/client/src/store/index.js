import { createStore } from 'vuex'
import { actions } from './actions'
import { can as canPerm } from '@/utils/permissions'

const state = {
  currentUser: null,
  permissions: []
}

const getters = {
  isAuthenticated: (state) => !!state.currentUser,
  getCurrentUser: (state) => state.currentUser,
  can: (state) => (permission) => canPerm(state.permissions, permission)
}

const mutations = {
  setAuth(state, { user, permissions }) {
    state.currentUser = user
    state.permissions = permissions || []
  },
  clearAuth(state) {
    state.currentUser = null
    state.permissions = []
  }
}

const store = createStore({
  state,
  getters,
  actions,
  mutations
})

export default store

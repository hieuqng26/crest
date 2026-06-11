import { roleAPI } from '@/api'

export const roleActions = {
  getRolesVariables(context) {
    return roleAPI.getRolesVariables()
  },
  getAllRolePermissions(context, forceLoadDB = false) {
    return new Promise((resolve, reject) => {
      // If the data is already in the state, resolve the promise with the cached data
      if (!forceLoadDB && context.state.roles) {
        resolve(context.state.roles)
      } else {
        // Otherwise, fetch the data from the API
        roleAPI.getAllRolePermissions(context.state.jwt.accessToken)
          .then((response) => {
            // Store the fetched data in the state
            context.commit('setRoles', {
              roles: response.data
            })
            resolve(response.data)
          })
          .catch((error) => {
            reject(new Error(error.response?.data?.message || error?.message || 'Failed to fetch roles'))
          })
      }
    }) 
  },
  getAllRoles(context) {
    return roleAPI.getAllRoles(context.state.jwt.accessToken)
  },
  getRoleByName(context, roleName) {
    return roleAPI.getRoleByName(roleName, context.state.jwt.accessToken)
  },
  addRole(context, roleData) {
    return roleAPI.addRole(roleData, context.state.jwt.accessToken)
  },
  addMultiRoles(context, roleData) {
    return roleAPI.addMultiRoles(roleData, context.state.jwt.accessToken)
  },
  updateRole(context, payload) {
    const { roleId, roleData } = payload
    return roleAPI.updateRole(roleId, roleData, context.state.jwt.accessToken)
  },
  updateRoles(context, payload) {
    const { rolesData } = payload
    return roleAPI.updateRoles(rolesData, context.state.jwt.accessToken)
  },
  deleteRole(context, roleId) {
    return roleAPI.deleteRole(roleId, context.state.jwt.accessToken)
  },
  deleteMultiRoles(context, roleIds) {
    return roleAPI.deleteMultiRoles(roleIds, context.state.jwt.accessToken)
  }
}

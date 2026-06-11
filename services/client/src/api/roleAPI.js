import { httpClient, setAuthHeader } from '@/api/httpClient'

const roleAPI = {
  getRolesVariables: () => httpClient.get('/role/roles_variable'),
  getAllRolePermissions: (jwt) => httpClient.get('/role/permissions', { headers: setAuthHeader(jwt) }),
  getAllRoles: (jwt) => httpClient.get(`/role/all`, { headers: setAuthHeader(jwt) }),
  getRoleByName: (name, jwt) =>
    httpClient.get(`/role/name/${name}`, { headers: setAuthHeader(jwt) }),
  addRole: (roleData, jwt) =>
    httpClient.post(`/role/add`, roleData, { headers: setAuthHeader(jwt) }),
  addMultiRoles: (roleData, jwt) =>
    httpClient.post(`/role/add_batch`, { roles: roleData }, { headers: setAuthHeader(jwt) }),
  updateRole: (roleId, roleData, jwt) =>
    httpClient.put(`/role/update/${roleId}`, roleData, { headers: setAuthHeader(jwt) }),
  updateRoles: (rolesData, jwt) =>
    httpClient.put(`/role/updates`, { roles: rolesData }, { headers: setAuthHeader(jwt) }),
  deleteRole: (roleId, jwt) =>
    httpClient.delete(`/role/delete/${roleId}`, { headers: setAuthHeader(jwt) }),
  deleteMultiRoles: (roleIds, jwt) =>
    // http client does not support body parameters, so use post instead
    httpClient.post(`/role/delete_batch`, { roleIds: roleIds }, { headers: setAuthHeader(jwt) })
}

export default roleAPI

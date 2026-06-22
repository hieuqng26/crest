import httpClient from '@/api/httpClient'

const roleAPI = {
  getRolesVariables: () => httpClient.get('/role/roles_variable'),
  getAllRolePermissions: () => httpClient.get('/role/permissions'),
  getAllRoles: () => httpClient.get(`/role/all`),
  getRoleByName: (name) =>
    httpClient.get(`/role/name/${name}`),
  addRole: (roleData) =>
    httpClient.post(`/role/add`, roleData),
  addMultiRoles: (roleData) =>
    httpClient.post(`/role/add_batch`, { roles: roleData }),
  updateRole: (roleId, roleData) =>
    httpClient.put(`/role/update/${roleId}`, roleData),
  updateRoles: (rolesData) =>
    httpClient.put(`/role/updates`, { roles: rolesData }),
  deleteRole: (roleId) =>
    httpClient.delete(`/role/delete/${roleId}`),
  deleteMultiRoles: (roleIds) =>
    // http client does not support body parameters, so use post instead
    httpClient.post(`/role/delete_batch`, { roleIds: roleIds })
}

export default roleAPI

import { httpClient, setAuthHeader } from '@/api/httpClient'

const userAPI = {
  getAllUsers: (jwt) => httpClient.get(`/user/all`, { headers: setAuthHeader(jwt) }),
  getIsLocalSystemAdmin: (username, jwt) =>
    httpClient.get(`/user/is_local_system_admin/${username}`, { headers: setAuthHeader(jwt) }),
  getUserByEmail: (email, jwt) =>
    httpClient.get(`/user/email/${email}`, { headers: setAuthHeader(jwt) }),
  addUser: (userData, jwt) =>
    httpClient.post(`/user/add`, userData, { headers: setAuthHeader(jwt) }),
  addMultiUsers: (userData, jwt) =>
    httpClient.post(`/user/add_batch`, { users: userData }, { headers: setAuthHeader(jwt) }),
  updateUser: (userId, userData, jwt) =>
    httpClient.put(`/user/update/${userId}`, userData, { headers: setAuthHeader(jwt) }),
  updateUsers: (usersData, jwt) =>
    httpClient.put(`/user/updates`, { users: usersData }, { headers: setAuthHeader(jwt) }),
  deleteUser: (userId, jwt) =>
    httpClient.delete(`/user/delete/${userId}`, { headers: setAuthHeader(jwt) })
}

export default userAPI

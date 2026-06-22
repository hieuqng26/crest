import httpClient from '@/api/httpClient'

const userAPI = {
  getAllUsers: () => httpClient.get(`/user/all`),
  getIsLocalSystemAdmin: (username) =>
    httpClient.get(`/user/is_local_system_admin/${username}`),
  getUserByEmail: (email) =>
    httpClient.get(`/user/email/${email}`),
  addUser: (userData) =>
    httpClient.post(`/user/add`, userData),
  addMultiUsers: (userData) =>
    httpClient.post(`/user/add_batch`, { users: userData }),
  updateUser: (userId, userData) =>
    httpClient.put(`/user/update/${userId}`, userData),
  updateUsers: (usersData) =>
    httpClient.put(`/user/updates`, { users: usersData }),
  deleteUser: (userId) =>
    httpClient.delete(`/user/delete/${userId}`)
}

export default userAPI

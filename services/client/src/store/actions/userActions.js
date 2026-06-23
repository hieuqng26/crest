import { userAPI } from '@/api'

export const userActions = {
  getAllUsers() {
    return userAPI.getAllUsers()
  },
  getIsLocalSystemAdmin(context, userId) {
    return userAPI.getIsLocalSystemAdmin(userId)
  },
  getUserById(context, userId) {
    return userAPI.getUserById(userId)
  },
  getUserByEmail(context, email) {
    return userAPI.getUserByEmail(email)
  },
  addUser(context, userData) {
    return userAPI.addUser(userData)
  },
  addMultiUsers(context, userData) {
    return userAPI.addMultiUsers(userData)
  },
  updateUser(context, payload) {
    const { userId, userData } = payload
    return userAPI.updateUser(userId, userData)
  },
  updateUsers(context, payload) {
    const { usersData } = payload
    return userAPI.updateUsers(usersData)
  },
  deleteUser(context, userId) {
    return userAPI.deleteUser(userId)
  }
}

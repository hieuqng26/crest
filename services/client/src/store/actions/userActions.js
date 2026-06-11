import { userAPI } from '@/api'

export const userActions = {
  getAllUsers(context) {
    return userAPI.getAllUsers(context.state.jwt.accessToken)
  },
  getIsLocalSystemAdmin(context, userId) {
    return userAPI.getIsLocalSystemAdmin(userId, context.state.jwt.accessToken)
  },
  getUserById(context, userId) {
    return userAPI.getUserById(userId, context.state.jwt.accessToken)
  },
  getUserByEmail(context, email) {
    return userAPI.getUserByEmail(email, context.state.jwt.accessToken)
  },
  addUser(context, userData) {
    return userAPI.addUser(userData, context.state.jwt.accessToken)
  },
  addMultiUsers(context, userData) {
    return userAPI.addMultiUsers(userData, context.state.jwt.accessToken)
  },
  updateUser(context, payload) {
    const { userId, userData } = payload
    return userAPI.updateUser(userId, userData, context.state.jwt.accessToken)
  },
  updateUsers(context, payload) {
    const { usersData } = payload
    return userAPI.updateUsers(usersData, context.state.jwt.accessToken)
  },
  deleteUser(context, userId) {
    return userAPI.deleteUser(userId, context.state.jwt.accessToken)
  }
}

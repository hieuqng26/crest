import { authActions } from './authActions'
import { userActions } from './userActions'
import { logActions } from './logActions'

export const actions = {
  ...authActions,
  ...userActions,
  ...logActions
}

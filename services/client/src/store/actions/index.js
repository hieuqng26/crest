import { authActions } from './authActions'
import { userActions } from './userActions'
import { roleActions } from './roleActions'
import { logActions } from './logActions'

export const actions = {
  ...authActions,
  ...userActions,
  ...roleActions,
  ...logActions
}

import { authActions } from './authActions'
import { userActions } from './userActions'
import { roleActions } from './roleActions'
import { jobActions } from './jobActions'
import { logActions } from './logActions'
import { fileActions } from './fileActions'
import { dataActions } from './dataActions'

export const actions = {
  ...authActions,
  ...userActions,
  ...roleActions,
  ...jobActions,
  ...logActions,
  ...fileActions,
  ...dataActions
}

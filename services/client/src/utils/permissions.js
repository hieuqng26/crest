export function can(permissions, permission) {
  if (!permissions || permissions.length === 0) return false
  if (permissions.includes('*')) return true
  return permissions.includes(permission)
}

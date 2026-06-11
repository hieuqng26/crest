export function isValidJwt(jwt) {
  if (!jwt || jwt.split('.').length < 3) {
    return false
  }
  const data = JSON.parse(atob(jwt.split('.')[1]))
  const exp = new Date(data.exp * 1000)
  const now = new Date()
  return now < exp
}

export function formatDate(date, include_time = false) {
  if (!date) {
    return ''
  }
  if (typeof date === 'string') {
    date = new Date(date)
  }
  const year = date.getFullYear()

  // Months are zero-based in JavaScript, so add 1 and pad with zero if needed
  const month = String(date.getMonth() + 1).padStart(2, '0')

  // Pad the day with zero if needed
  const day = String(date.getDate()).padStart(2, '0')

  if (include_time) {
    // Get the hours, minutes, and seconds
    const hours = String(date.getHours()).padStart(2, '0')
    const minutes = String(date.getMinutes()).padStart(2, '0')
    const seconds = String(date.getSeconds()).padStart(2, '0')

    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
  }

  return `${year}-${month}-${day}`
}

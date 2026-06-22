import httpClient from '@/api/httpClient'

const roleAPI = {
  list: () => httpClient.get('/roles/'),
  catalog: () => httpClient.get('/roles/catalog'),
  create: (payload) => httpClient.post('/roles/', payload),
  update: (name, payload) => httpClient.put(`/roles/${name}`, payload),
  remove: (name) => httpClient.delete(`/roles/${name}`)
}
export default roleAPI

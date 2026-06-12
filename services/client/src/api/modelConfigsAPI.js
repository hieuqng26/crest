import { httpClient } from './httpClient'

const modelConfigsAPI = {
  registry: ()     => httpClient.get('/model-configs/registry'),
  list:     ()     => httpClient.get('/model-configs/'),
  get:      (id)   => httpClient.get(`/model-configs/${id}`),
  create:   (body) => httpClient.post('/model-configs/', body),
}

export default modelConfigsAPI

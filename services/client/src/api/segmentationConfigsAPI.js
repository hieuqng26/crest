import { httpClient } from './httpClient'

const segmentationConfigsAPI = {
  list:   ()         => httpClient.get('/segmentation-configs/'),
  get:    (id)       => httpClient.get(`/segmentation-configs/${id}`),
  create: (body)     => httpClient.post('/segmentation-configs/', body),
  update: (id, body) => httpClient.patch(`/segmentation-configs/${id}`, body),
  refs:   (id)       => httpClient.get(`/segmentation-configs/${id}/refs`),
  delete: (id)       => httpClient.delete(`/segmentation-configs/${id}`),
}

export default segmentationConfigsAPI

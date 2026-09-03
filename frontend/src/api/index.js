import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' }
})

// 请求拦截器 - 添加 workspace header
api.interceptors.request.use((config) => {
  const ws = localStorage.getItem('currentWorkspace')
  if (ws) {
    config.headers['X-Workspace-Id'] = ws
  }
  return config
})

// Workspace API
export const workspaceApi = {
  list: () => api.get('/workspaces'),
  create: (data) => api.post('/workspaces', data),
  get: (id) => api.get(`/workspaces/${id}`),
  update: (id, data) => api.put(`/workspaces/${id}`, data),
  delete: (id) => api.delete(`/workspaces/${id}`)
}

// Config API
export const configApi = {
  get: () => api.get('/config'),
  listProviders: () => api.get('/config/providers'),
  getDefault: () => api.get('/config/default'),
  setDefault: (name) => api.post('/config/default', { default: name }),
  addProvider: (data) => api.post('/config/provider', data),
  updateProvider: (name, data) => api.put(`/config/provider/${name}`, data),
  deleteProvider: (name) => api.delete(`/config/provider/${name}`),
  test: (name) => api.post('/config/test', { name })
}

// Agent API
export const agentApi = {
  list: (wsId) => api.get('/agents', { params: { workspace_id: wsId } }),
  get: (id) => api.get(`/agents/${id}`),
  create: (wsId, data) => api.post('/agents', data),
  update: (id, data) => api.put(`/agents/${id}`, data),
  delete: (id) => api.delete(`/agents/${id}`),
  versions: (agentId) => api.get(`/agents/${agentId}/versions`),
  createVersion: (agentId, data) => api.post(`/agents/${agentId}/versions`, data || {}),
  publish: (agentId, data) => api.post(`/agents/${agentId}/publish`, data || {}),
  test: (agentId, data) => api.post(`/agents/${agentId}/test`, data),
  runs: (agentId) => api.get(`/agents/${agentId}/runs`),
  uploadAvatar: (agentId, file) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post(`/agents/${agentId}/avatar`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  listModels: () => api.get('/agents/models/available')
}

// Chat API
export const chatApi = {
  send: (data) => api.post('/chat', data)
}

// Knowledge API
export const knowledgeApi = {
  list: (params = {}) => api.get('/knowledge', { params }),
  create: (data) => api.post('/knowledge', data),
  detail: (id) => api.get(`/knowledge/${id}`),
  delete: (id) => api.delete(`/knowledge/${id}`),
  addDoc: (kbId, data) => api.post(`/knowledge/${kbId}/documents`, data),
  uploadFile: (kbId, file) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post(`/knowledge/${kbId}/upload`, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
  deleteDoc: (kbId, docId) => api.delete(`/knowledge/${kbId}/documents/${docId}`),
}

// Tool API
export const toolApi = {
  list: () => api.get('/tools'),
  create: (data) => api.post('/tools', data),
  delete: (id) => api.delete(`/tools/${id}`)
}

// Workflow API
export const workflowApi = {
  list: () => api.get('/workflows'),
  create: (data) => api.post('/workflows', data),
  delete: (id) => api.delete(`/workflows/${id}`)
}

// Task API
export const taskApi = {
  list: () => api.get('/tasks'),
  create: (data) => api.post('/tasks', data),
  delete: (id) => api.delete(`/tasks/${id}`)
}

// Conversation API
export const conversationApi = {
  list: () => api.get('/conversations'),
  create: (data) => api.post('/conversations', data),
  get: (id) => api.get(`/conversations/${id}`),
  messages: (convId) => api.get(`/conversations/${convId}/messages`),
  sendMessage: (convId, data) => api.post(`/conversations/${convId}/messages`, data),
  delete: (convId) => api.delete(`/conversations/${convId}`)
}


// Meeting API
export const meetingApi = {
  list: () => api.get('/meetings'),
  create: (data) => api.post('/meetings', data),
  detail: (id) => api.get(`/meetings/${id}`),
  messages: (id) => api.get(`/meetings/${id}/messages`),
  conclusion: (id) => api.get(`/meetings/${id}/conclusion`),
  todos: (id) => api.get(`/meetings/${id}/todos`),
  start: (id) => api.post(`/meetings/${id}/start`),
  cancel: (id) => api.post(`/meetings/${id}/cancel`),
  uploadFile: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post('/meetings/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
}

export default api

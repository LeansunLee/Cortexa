import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'AgentDevStu' }
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
  test: (name) => api.post('/config/test', { name }),
  saveEmbedding: (data) => api.post('/config/embedding', data),
  saveConversationDebug: (enabled) => api.post('/config/conversation-debug', { enabled })
}

// Agent API
export const agentApi = {
  resources: id => api.get(`/agents/${id}/resources`),
  list: (wsId) => api.get('/agents', { params: { workspace_id: wsId } }),
  get: (id) => api.get(`/agents/${id}`),
  create: (wsId, data) => api.post('/agents', data),
  update: (id, data) => api.put(`/agents/${id}`, data),
  delete: (id) => api.delete(`/agents/${id}`),
  versions: (agentId) => api.get(`/agents/${agentId}/versions`),
  createVersion: (agentId, data) => api.post(`/agents/${agentId}/versions`, data || {}),
  publish: (agentId, data) => api.post(`/agents/${agentId}/publish`, data || {}),
  resolveInput: (agentId, data) => api.post(`/agents/${agentId}/resolve-input`, data, { timeout: 120000 }),
  runs: (agentId) => api.get(`/agents/${agentId}/runs`),
  uploadAvatar: (agentId, file) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post(`/agents/${agentId}/avatar`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  searchStatus: () => api.get('/agents/tools/web-search'),
  listModels: () => api.get('/agents/models/available')
}

export const agentOpsApi = {
  summary: id => api.get(`/agent-operations/${id}/summary`),
  knowledge: (id, ids) => api.patch(`/agent-operations/${id}/knowledge-bindings`, { knowledge_base_ids: ids }),
  createKnowledge: (id, data) => api.post(`/agent-operations/${id}/knowledge-bases`, data),
  tools: (id, ids) => api.patch(`/agent-operations/${id}/tool-bindings`, { tool_ids: ids }),
  bindData: (id, capability) => api.post(`/agent-operations/${id}/data-bindings`, { data_capability_id: capability }),
  unbindData: (id, binding) => api.delete(`/agent-operations/${id}/data-bindings/${binding}`),
  createMemory: (id, data) => api.post(`/agent-operations/${id}/memories`, data),
  updateMemory: (id, memory, data) => api.patch(`/agent-operations/${id}/memories/${memory}`, data),
  archiveMemory: (id, memory) => api.delete(`/agent-operations/${id}/memories/${memory}`),
}

// Chat API
export const chatApi = {
  send: (data) => api.post('/chat', data)
}

// Knowledge API
export const knowledgeApi = {
  list: (params = {}) => api.get('/knowledge', { params }),
  create: (data) => api.post('/knowledge', data),
  rename: (id, name) => api.patch('/knowledge/' + id + '/name', { name }),
  updateStatus: (id, status) => api.patch('/knowledge/' + id + '/status', { status }),
  detail: (id) => api.get(`/knowledge/${id}`),
  delete: (id) => api.delete(`/knowledge/${id}`),
  addDoc: (kbId, data) => api.post(`/knowledge/${kbId}/documents`, data),
  listFolders: (kbId) => api.get(`/knowledge/${kbId}/folders`),
  createFolder: (kbId, data) => api.post(`/knowledge/${kbId}/folders`, data),
  renameFolder: (kbId, folderId, name) => api.patch(`/knowledge/${kbId}/folders/${folderId}`, { name }),
  moveFolder: (kbId, folderId, parentId) => api.patch(`/knowledge/${kbId}/folders/${folderId}/move`, { parent_id: parentId }),
  deleteFolder: (kbId, folderId) => api.delete(`/knowledge/${kbId}/folders/${folderId}`),
  moveDocs: (kbId, documentIds, folderId) => api.post(`/knowledge/${kbId}/documents/move`, { document_ids: documentIds, folder_id: folderId }),
  moveResources: (kbId, documentIds, folderIds, folderId) => api.post(`/knowledge/${kbId}/resources/move`, { document_ids: documentIds, folder_ids: folderIds, folder_id: folderId }),
  renameDoc: (kbId, docId, name) => api.patch('/knowledge/' + kbId + '/documents/' + docId + '/name', { name }),
  uploadFile: (kbId, file, onUploadProgress, signal, folderId = null) => {
    const fd = new FormData()
    fd.append('file', file)
    if (folderId) fd.append('folder_id', folderId)
    return api.post(`/knowledge/${kbId}/upload`, fd, { headers: { 'Content-Type': 'multipart/form-data' }, onUploadProgress, signal, timeout: 300000 })
  },
  extractDoc: (kbId, docId) => api.post(`/knowledge/${kbId}/documents/${docId}/extract`),
  updateDocValidity: (kbId, docId, validUntil) => api.patch(`/knowledge/${kbId}/documents/${docId}/validity`, { valid_until: validUntil }),
  updateDocSummary: (kbId, docId, content) => api.patch(`/knowledge/${kbId}/documents/${docId}/summary`, { content }),
  regenDocSummary: (kbId, docId) => api.post(`/knowledge/${kbId}/documents/${docId}/regenerate-summary`, null, { timeout: 90000 }),
  reindexDoc: (kbId, docId) => api.post(`/knowledge/${kbId}/documents/${docId}/reindex`),
  reprocessPendingPdfs: () => api.post('/knowledge/reprocess-pending-pdfs', null, { timeout: 300000 }),
  getDocContent: (kbId, docId) => api.get(`/knowledge/${kbId}/documents/${docId}/content`),
  updateDocContent: (kbId, docId, content) => api.put(`/knowledge/${kbId}/documents/${docId}/content`, { content }, { timeout: 60000 }),
  batchDownloadDocs: (kbId, documentIds) => api.post(`/knowledge/${kbId}/documents/batch-download`, { document_ids: documentIds }, { responseType: 'blob', timeout: 300000 }),
  batchDeleteDocs: (kbId, documentIds) => api.post(`/knowledge/${kbId}/documents/batch-delete`, { document_ids: documentIds }),
  batchDeleteResources: (kbId, documentIds, folderIds) => api.post(`/knowledge/${kbId}/resources/batch-delete`, { document_ids: documentIds, folder_ids: folderIds }),
  pushDoc: (kbId, docId, targetKbId) => api.post(`/knowledge/${kbId}/documents/${docId}/push`, { target_kb_id: targetKbId }, { timeout: 300000 }),
  deleteDoc: (kbId, docId) => api.delete(`/knowledge/${kbId}/documents/${docId}`),
  previewDoc: (kbId, docId, options = {}) => api.get(`/knowledge/${kbId}/documents/${docId}/preview`, options),
  previewPage: (kbId, docId, page, options = {}) => api.get(`/knowledge/${kbId}/documents/${docId}/pages/${page}`, options),
  downloadDoc: (kbId, docId) => api.get(`/knowledge/${kbId}/documents/${docId}/raw`, { responseType: 'blob', timeout: 300000 }),
  rawDoc: (kbId, docId) => `/api/knowledge/${kbId}/documents/${docId}/raw`,
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
  update: (id, data) => api.patch(`/conversations/${id}`, data),
  messages: (convId) => api.get(`/conversations/${convId}/messages`),
  sendMessage: (convId, data) => api.post(`/conversations/${convId}/messages`, data, { timeout: 610000 }),
  regenerate: (convId) => api.post(`/conversations/${convId}/regenerate`, {}, { timeout: 610000 }),
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

// Memory API
export const memoryApi = {
  list: (params = {}) => api.get('/memories', { params }),
  get: (id) => api.get(`/memories/${id}`),
  create: (data) => api.post('/memories', data),
  update: (id, data) => api.patch(`/memories/${id}`, data),
  delete: (id) => api.delete(`/memories/${id}`),
}

// Chat File Upload
export const chatUploadApi = {
  uploadFile: (convId, file) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post(`/conversations/${convId}/upload`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  }
}

// Agent Collaboration API
export const collaborationApi = {
  background: (payload) => api.post('/collaboration/background', payload),
  inputSnapshot: (conversationId, snapshotId) => api.get(`/collaboration/input/${conversationId}`, {params: {snapshot_id: snapshotId}}),
  draftOptions: (agentId) => api.get('/collaboration/draft-options', {params: {agent_id: agentId}}),
  preview: (payload) => api.post('/collaboration/preview', payload),
  listAgents: (excludeAgentId) => api.get('/collaboration/agents', { params: excludeAgentId ? { exclude_agent_id: excludeAgentId } : {} }),
  getHistory: (convId) => api.get(`/collaboration/history/${convId}`),
  getLimits: (convId) => api.get(`/collaboration/limits/${convId}`),
}

export default api

// Data Capability API
export const dataApi = {
  // Data Sources
  listSources: () => api.get('/data/sources'),
  createSource: (data) => api.post('/data/sources', data),
  getSource: (id) => api.get(`/data/sources/${id}`),
  updateSource: (id, data) => api.put(`/data/sources/${id}`, data),
  deleteSource: (id) => api.delete(`/data/sources/${id}`),
  testSource: (id) => api.post(`/data/sources/${id}/test`),
  syncSchema: (id) => api.post(`/data/sources/${id}/sync-schema`),
  getSchema: (id) => api.get(`/data/sources/${id}/schema`),
  // Credentials
  listCredentials: () => api.get('/data/credentials'),
  createCredential: (data) => api.post('/data/credentials', data),
  updateCredential: (id, data) => api.put(`/data/credentials/${id}`, data),
  deleteCredential: (id) => api.delete(`/data/credentials/${id}`),
  // Capabilities
  listCapabilities: (params = {}) => api.get('/data/capabilities', { params }),
  createCapability: (data) => api.post('/data/capabilities', data),
  getCapability: (id) => api.get(`/data/capabilities/${id}`),
  deleteCapability: (id) => api.delete(`/data/capabilities/${id}`),
  updateCapability: (id, data) => api.put(`/data/capabilities/${id}`, data),
  updateCapabilityStatus: (id, status) => api.patch(`/data/capabilities/${id}/status`, { status }),
  // Bindings
  listBindings: (params = {}) => api.get('/data/bindings', { params }),
  createBinding: (data) => api.post('/data/bindings', data),
  deleteBinding: (id) => api.delete(`/data/bindings/${id}`),
  deleteBindingByAgentCap: (agentId, capId) => api.delete('/data/bindings', { params: { agent_id: agentId, data_capability_id: capId } }),
  // Query
  executeQuery: (data) => api.post('/data/query', data),
  listQueries: (params = {}) => api.get('/data/queries', { params }),
}

api.interceptors.response.use(response => response, error => {
  if (!error.config?.skipAuthRedirect) {
    if (error.response?.status === 401 && location.pathname !== '/login') location.assign('/login')
    if (error.response?.status === 403 && error.response?.data?.detail === '首次登录请先修改密码') location.assign('/change-password')
  }
  return Promise.reject(error)
})
export const usableAgentApi = { list: () => api.get('/auth/agents') }

export const workApi = {
  recommendations: data => api.post('/works/assignee-recommendations', data),
  members: () => api.get('/works/members'),
  list: params => api.get('/works', { params }),
  get: id => api.get(`/works/${id}`),
  create: data => api.post('/works', data),
  update: (id, data) => api.patch(`/works/${id}`, data),
  action: (id, action, comment = '') => api.post(`/works/${id}/${action}`, { comment }),
  submit: (id, data) => api.post(`/works/${id}/submit`, data, { headers: {'Content-Type':'multipart/form-data'}, timeout:300000 }),
  createLog: (id, data) => api.post(`/works/${id}/logs`, data),
  updateLog: (id, logId, data) => api.patch(`/works/${id}/logs/${logId}`, data),
  activities: id => api.get(`/works/${id}/activities`),
  deliverables: id => api.get(`/works/${id}/deliverables`),
  download: (id, d) => api.get(`/works/${id}/deliverables/${d}/download`, {responseType:'blob'}),
  knowledge: (id, d, kb) => api.post(`/works/${id}/deliverables/${d}/knowledge`, {knowledge_base_id:kb}, {timeout:300000}),
  memory: (id, data) => api.post(`/works/${id}/memory`, data),
  candidates: id => api.get(`/conversations/${id}/work-candidates`),
  extract: (id, message_id) => api.post(`/conversations/${id}/work-candidates/extract`, { message_id }),
  accept: (id, data) => api.post(`/work-candidates/${id}/accept`, data),
  ignore: id => api.post(`/work-candidates/${id}/reject`),
}

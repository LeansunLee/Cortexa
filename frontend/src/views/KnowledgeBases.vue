<template>
  <div class="knowledge-page">
    <div class="page-header">
      <div>
        <h1>📚 空间知识库</h1>
        <p class="subtitle">管理当前工作空间的共享知识库，同空间的智能体均可使用</p>
      </div>
      <button class="btn btn-primary" @click="showCreate = true">+ 创建知识库</button>
    </div>

    <!-- Create modal -->
    <div v-if="showCreate" class="modal-overlay" @click.self="showCreate = false">
      <div class="modal">
        <h3>创建空间知识库</h3>
        <div class="form-group">
          <label>名称 *</label>
          <input v-model="newName" placeholder="例如：产品文档库" @keydown.enter="createKB" />
        </div>
        <div class="form-group">
          <label>描述</label>
          <textarea v-model="newDesc" rows="3" placeholder="知识库用途描述"></textarea>
        </div>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="showCreate = false">取消</button>
          <button class="btn btn-primary" @click="createKB" :disabled="!newName.trim()">创建</button>
        </div>
      </div>
    </div>

    <!-- KB List -->
    <div v-if="loading" class="empty-state">加载中...</div>
    <div v-else-if="knowledgeBases.length === 0" class="empty-state">
      <div class="empty-icon">📚</div>
      <p>暂无空间知识库</p>
    </div>
    <div v-else class="kb-list">
      <div v-for="kb in knowledgeBases" :key="kb.id" class="kb-card">
        <div class="kb-card-header">
          <div class="kb-card-info">
            <div class="kb-card-name">📁 {{ kb.name }}</div>
            <div class="kb-card-meta">
              {{ kbDocs[kb.id]?.length || 0 }} 个文档
              <span v-if="kb.description"> · {{ kb.description }}</span>
            </div>
          </div>
          <div class="kb-card-actions">
            <label class="btn btn-ghost btn-sm">
              📤 上传文件
              <input type="file" multiple style="display:none" @change="(e) => uploadFile(e, kb.id)" />
            </label>
            <button class="btn btn-ghost btn-sm" @click="toggleExpand(kb.id)">
              {{ expandedKB === kb.id ? '收起' : '展开' }}
            </button>
            <button class="btn btn-danger btn-sm" @click="deleteKB(kb.id)">删除</button>
          </div>
        </div>
        <!-- Expanded doc list -->
        <div v-if="expandedKB === kb.id" class="kb-docs">
          <div v-if="!kbDocs[kb.id] || kbDocs[kb.id].length === 0" class="empty-hint">暂无文档</div>
          <div v-for="doc in kbDocs[kb.id]" :key="doc.id" class="kb-doc-item">
            <span class="kb-doc-name">📄 {{ doc.name || doc.filename || '未命名' }}</span>
            <span class="kb-doc-meta" v-if="doc.metadata_json?.size">{{ formatSize(doc.metadata_json.size) }}</span>
            <button class="btn btn-ghost btn-xs" @click="deleteDoc(kb.id, doc.id)">🗑️</button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="toast.show" :class="['toast', 'toast-' + toast.type]">{{ toast.message }}</div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { knowledgeApi } from '../api'

const knowledgeBases = ref([])
const kbDocs = ref({})
const loading = ref(true)
const showCreate = ref(false)
const newName = ref('')
const newDesc = ref('')
const expandedKB = ref(null)
const toast = ref({ show: false, message: '', type: 'success' })

const showToast = (message, type = 'success') => {
  toast.value = { show: true, message, type }
  setTimeout(() => { toast.value.show = false }, 3000)
}

const loadKBs = async () => {
  loading.value = true
  try {
    const { data } = await knowledgeApi.list({ scope: 'workspace' })
    knowledgeBases.value = data
    // Load docs for each KB
    for (const kb of data) {
      try {
        const { data: detail } = await knowledgeApi.detail(kb.id)
        kbDocs.value[kb.id] = detail.documents || []
      } catch { kbDocs.value[kb.id] = [] }
    }
  } catch (e) {
    showToast('加载失败: ' + (e.response?.data?.detail || e.message), 'error')
  }
  loading.value = false
}

const createKB = async () => {
  if (!newName.value.trim()) return
  try {
    await knowledgeApi.create({ name: newName.value.trim(), description: newDesc.value.trim() || null })
    newName.value = ''
    newDesc.value = ''
    showCreate.value = false
    await loadKBs()
    showToast('创建成功')
  } catch (e) {
    showToast('创建失败: ' + (e.response?.data?.detail || e.message), 'error')
  }
}

const deleteKB = async (kbId) => {
  if (!confirm('确定删除该知识库？')) return
  try {
    await knowledgeApi.delete(kbId)
    await loadKBs()
    showToast('删除成功')
  } catch (e) {
    showToast('删除失败', 'error')
  }
}

const toggleExpand = async (kbId) => {
  if (expandedKB.value === kbId) {
    expandedKB.value = null
    return
  }
  expandedKB.value = kbId
  if (!kbDocs.value[kbId]) {
    try {
      const { data: detail } = await knowledgeApi.detail(kbId)
      kbDocs.value[kbId] = detail.documents || []
    } catch { kbDocs.value[kbId] = [] }
  }
}

const uploadFile = async (event, kbId) => {
  const files = event.target.files
  if (!files) return
  for (const file of files) {
    try {
      await knowledgeApi.uploadFile(kbId, file)
      const { data: detail } = await knowledgeApi.detail(kbId)
      kbDocs.value[kbId] = detail.documents || []
      showToast(`上传成功: ${file.name}`)
    } catch (e) {
      showToast(`上传失败: ${file.name}`, 'error')
    }
  }
  event.target.value = ''
}

const deleteDoc = async (kbId, docId) => {
  try {
    await knowledgeApi.deleteDoc(kbId, docId)
    const { data: detail } = await knowledgeApi.detail(kbId)
    kbDocs.value[kbId] = detail.documents || []
    showToast('文档已删除')
  } catch (e) {
    showToast('删除失败', 'error')
  }
}

const formatSize = (bytes) => {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

onMounted(loadKBs)
</script>

<style scoped>
.knowledge-page { padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-header h1 { margin: 0; font-size: 24px; }
.subtitle { color: #666; margin: 4px 0 0; font-size: 14px; }
.empty-state { text-align: center; padding: 60px 20px; color: #999; }
.empty-icon { font-size: 48px; margin-bottom: 12px; }
.kb-list { display: flex; flex-direction: column; gap: 12px; }
.kb-card { background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; }
.kb-card-header { display: flex; justify-content: space-between; align-items: center; }
.kb-card-name { font-weight: 600; font-size: 16px; }
.kb-card-meta { font-size: 13px; color: #888; margin-top: 2px; }
.kb-card-actions { display: flex; gap: 8px; align-items: center; }
.kb-docs { margin-top: 12px; padding-top: 12px; border-top: 1px solid #f0f0f0; }
.kb-doc-item { display: flex; align-items: center; justify-content: space-between; padding: 6px 0; }
.kb-doc-name { font-size: 14px; }
.kb-doc-meta { font-size: 12px; color: #999; margin-left: 8px; }
.empty-hint { color: #999; font-size: 13px; padding: 8px 0; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal { background: #fff; border-radius: 12px; padding: 24px; width: 480px; max-width: 90vw; }
.modal h3 { margin: 0 0 16px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.form-group { margin-bottom: 12px; }
.form-group label { display: block; font-weight: 500; margin-bottom: 4px; font-size: 14px; }
.form-group input, .form-group textarea { width: 100%; padding: 8px 12px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 14px; box-sizing: border-box; }
.btn { padding: 8px 16px; border-radius: 8px; border: none; cursor: pointer; font-size: 14px; }
.btn-primary { background: #3b82f6; color: #fff; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-ghost { background: transparent; color: #374151; border: 1px solid #d1d5db; }
.btn-danger { background: transparent; color: #ef4444; border: 1px solid #fecaca; }
.btn-sm { padding: 4px 10px; font-size: 13px; }
.btn-xs { padding: 2px 6px; font-size: 12px; }
.toast { position: fixed; bottom: 24px; right: 24px; padding: 12px 20px; border-radius: 8px; color: #fff; font-size: 14px; z-index: 2000; }
.toast-success { background: #10b981; }
.toast-error { background: #ef4444; }
</style>

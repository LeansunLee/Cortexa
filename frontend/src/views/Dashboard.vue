<template>
  <div class="dashboard">
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-icon"><AppIcon name="Building2" /></div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.workspaces }}</div>
          <div class="stat-label">工作空间</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon"><Bot :size="24" /></div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.agents }}</div>
          <div class="stat-label">智能体</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon"><AppIcon name="RefreshCw" /></div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.workflows }}</div>
          <div class="stat-label">工作流</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon"><FileText :size="24" /></div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.tasks }}</div>
          <div class="stat-label">任务</div>
        </div>
      </div>
    </div>

    <div class="section-header">
      <h2>快速操作</h2>
    </div>
    <div class="action-grid">
      <div v-if="can('workspaces.create')" class="action-card" @click="showCreateModal = true">
        <span class="action-icon"><AppIcon name="Building2" /></span>
        <span class="action-text">创建工作空间</span>
      </div>
      <router-link v-if="can('agent.create')" to="/agents" class="action-card">
        <span class="action-icon"><Bot :size="18" /></span>
        <span class="action-text">创建智能体</span>
      </router-link>
      <router-link v-if="can('workflows.manage')" to="/workflows" class="action-card">
        <span class="action-icon"><AppIcon name="RefreshCw" /></span>
        <span class="action-text">创建工作流</span>
      </router-link>
      <router-link v-if="can('config.manage')" to="/settings" class="action-card">
        <span class="action-icon"><Settings :size="18" /></span>
        <span class="action-text">系统配置</span>
      </router-link>
    </div>

    <div class="workspace-section">
      <div class="section-header">
        <h2>工作空间</h2>
        <button v-if="can('workspaces.create')" class="btn btn-primary btn-sm" @click="showCreateModal = true">+ 新建</button>
      </div>
      <div class="workspace-list" v-if="workspaces.length > 0">
        <div v-for="ws in workspaces" :key="ws.id" class="workspace-item" @click="selectWorkspace(ws)">
          <div class="ws-name"><AppIcon name="Building2" /> {{ ws.name }}</div>
          <div class="ws-desc">{{ ws.description || '暂无描述' }}</div>
          <div class="ws-meta">
            <span v-if="ws.default_model_provider">{{ ws.default_model_provider }}</span>
            <span>创建于 {{ formatDate(ws.created_at) }}</span>
          </div>
        </div>
      </div>
      <div v-else class="empty-state">
        <p>尚未加入工作空间，请联系管理员分配。</p>
      </div>
    </div>

    <!-- Edit Workspace Modal -->
    <div v-if="showEditModal && editingWorkspace" class="modal-overlay" @click.self="showEditModal = false">
      <div class="modal-box">
        <div class="modal-header">
          <h3>编辑工作空间</h3>
          <button class="modal-close" @click="showEditModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>工作空间名称</label>
            <input v-model="editingWorkspace.name" placeholder="例如：产品设计团队" />
          </div>
          <div class="form-group">
            <label>描述（可选）</label>
            <textarea v-model="editingWorkspace.description" rows="3" placeholder="工作空间的用途描述"></textarea>
          </div>
          <div class="form-group">
            <label>默认模型供应商</label>
            <SearchSelect
              v-model="editingWorkspace.default_model_provider"
              :options="providerOptions"
              placeholder="不设置（使用全局默认）"
              aria-label="编辑工作空间默认模型供应商"
            />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost" @click="showEditModal = false">取消</button>
          <button class="btn btn-primary" @click="saveWorkspaceEdit">保存</button>
        </div>
      </div>
    </div>

    <!-- Create Workspace Modal -->
    <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
      <div class="modal-box">
        <div class="modal-header">
          <h3>创建工作空间</h3>
          <button class="modal-close" @click="showCreateModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>工作空间名称</label>
            <input v-model="newWorkspace.name" placeholder="例如：产品设计团队" />
          </div>
          <div class="form-group">
            <label>描述（可选）</label>
            <textarea v-model="newWorkspace.description" rows="3" placeholder="工作空间的用途描述"></textarea>
          </div>
          <div class="form-group">
            <label>默认模型供应商</label>
            <SearchSelect
              v-model="newWorkspace.default_model_provider"
              :options="providerOptions"
              placeholder="不设置（使用全局默认）"
              aria-label="新建工作空间默认模型供应商"
            />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost" @click="showCreateModal = false">取消</button>
          <button class="btn btn-primary" @click="createWorkspace">创建</button>
        </div>
      </div>
    </div>

    <!-- Toast -->
  </div>
</template>

<script setup>
import { LayoutDashboard, Users, MessageSquare, BookOpen, Activity } from 'lucide-vue-next'

import { computed, ref, onMounted } from 'vue'
import { can, auth } from '../auth'
import { workspaceApi, configApi } from '../api'

const workspaces = ref([])
const stats = ref({ workspaces: 0, agents: 0, workflows: 0, tasks: 0 })
const showCreateModal = ref(false)
const showEditModal = ref(false)
const editingWorkspace = ref(null)
const newWorkspace = ref({ name: '', description: '', default_model_provider: '' })
const providers = ref({})

const providerOptions = computed(() => [
  { value: '', label: '不设置（使用全局默认）' },
  ...Object.entries(providers.value).map(([name, p]) => ({
    value: name,
    label: name + ' (' + (p.model || '未设置模型') + ')',
  })),
])

const showToast = (message, type = 'success') => {
  window.dispatchEvent(new CustomEvent('toast', { detail: { message, type } }))
}

const formatDate = (date) => {
  return new Date(date).toLocaleDateString('zh-CN')
}

const loadWorkspaces = async () => {
  try {
    const { data } = await workspaceApi.list()
    workspaces.value = data
    stats.value.workspaces = data.length
  } catch (e) {
    console.error(e)
  }
}

const loadProviders = async () => {
  if (!can('config.manage')) return
  try {
    const { data } = await configApi.listProviders()
    providers.value = data.providers || {}
  } catch (e) {
    console.error('Failed to load providers:', e)
  }
}

const createWorkspace = async () => {
  if (!newWorkspace.value.name) {
    alert('请输入工作空间名称')
    return
  }
  try {
    await workspaceApi.create(newWorkspace.value)
    showCreateModal.value = false
    newWorkspace.value = { name: '', description: '', default_model_provider: '' }
    await loadWorkspaces()
    showToast('工作空间创建成功')
    window.dispatchEvent(new CustomEvent('workspace-changed'))
  } catch (e) {
    alert('创建失败: ' + (e.response?.data?.detail || e.message))
  }
}

const editWorkspace = (ws) => {
  editingWorkspace.value = { ...ws }
  showEditModal.value = true
}

const saveWorkspaceEdit = async () => {
  if (!editingWorkspace.value.name) {
    alert('请输入工作空间名称')
    return
  }
  try {
    await workspaceApi.update(editingWorkspace.value.id, {
      name: editingWorkspace.value.name,
      description: editingWorkspace.value.description,
      default_model_provider: editingWorkspace.value.default_model_provider
    })
    showEditModal.value = false
    editingWorkspace.value = null
    await loadWorkspaces()
    showToast('工作空间更新成功')
    window.dispatchEvent(new CustomEvent('workspace-changed'))
  } catch (e) {
    alert('更新失败: ' + (e.response?.data?.detail || e.message))
  }
}

const selectWorkspace = (ws) => {
  localStorage.setItem('currentWorkspace', ws.id)
  window.dispatchEvent(new CustomEvent('workspace-changed', { detail: ws.id }))
  if (auth.user?.memberships.find(m => m.workspace_id === ws.id)?.permissions.includes('workspace.manage')) editWorkspace(ws)
}

onMounted(() => {
  loadWorkspaces()
  loadProviders()
  window.addEventListener('workspace-changed', loadWorkspaces)
})
</script>

<style scoped>
.dashboard { display: flex; flex-direction: column; gap: 32px; }
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px 28px;
  display: flex;
  align-items: center;
  gap: 18px;
}
.stat-icon { font-size: 32px; }
.stat-info { flex: 1; }
.stat-value { font-size: 32px; font-weight: 700; color: var(--text); }
.stat-label { font-size: 14px; color: var(--text2); margin-top: 2px; }

.section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.section-header h2 { font-size: 18px; font-weight: 600; color: var(--text); margin: 0; }

.action-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.action-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 36px 24px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  text-decoration: none;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  cursor: pointer;
  min-height: 110px;
}
.action-card:hover {
  border-color: var(--primary);
  transform: translateY(-3px);
  box-shadow: 0 8px 24px rgba(0,0,0,0.08);
}
.action-icon { font-size: 36px; line-height: 1; }
.action-text { font-size: 15px; font-weight: 600; color: var(--text); white-space: nowrap; }

.workspace-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 20px; }
.workspace-item {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px;
  cursor: pointer;
  transition: all 0.2s;
}
.workspace-item:hover { border-color: var(--primary); box-shadow: var(--shadow); }
.ws-name { font-weight: 600; font-size: 16px; color: var(--text); margin-bottom: 4px; }
.ws-desc { font-size: 14px; color: var(--text2); margin-bottom: 8px; }
.ws-meta { font-size: 12px; color: var(--text3); }
.empty-state { text-align: center; padding: 48px 20px; color: var(--text3); font-size: 14px; }

.modal-overlay {
  display: flex;
  align-items: center;
  justify-content: center;
  position: fixed;
  inset: 0;
  background: var(--overlay);
  z-index: 9999;
}
.modal-box {
  background: var(--surface-dialog);
  border-radius: var(--radius);
  width: 520px;
  max-width: 90vw;
  box-shadow: var(--shadow-dialog);
}
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  border-bottom: 1px solid var(--border);
}
.modal-header h3 { font-size: 16px; font-weight: 600; }
.modal-close {
  background: none;
  border: none;
  font-size: 24px;
  color: var(--text3);
  cursor: pointer;
  padding: 4px;
  line-height: 1;
  border-radius: 4px;
  transition: all 0.15s;
}
.modal-close:hover { background: var(--surface2); color: var(--text); }
.modal-body { padding: 24px; }
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid var(--border);
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px 20px;
  border: none;
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-primary { background: var(--primary); color: var(--primary-text); }
.btn-primary:hover { background: var(--primary-hover); }
.btn-ghost { background: transparent; color: var(--text2); border: 1px solid var(--border); }
.btn-ghost:hover { background: var(--surface2); }
.btn-sm { padding: 7px 14px; font-size: 13px; }

.form-group { margin-bottom: 16px; }
.form-group label { display: block; font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 6px; }
.form-group input, .form-group textarea {
  width: 100%;
  padding: 10px 14px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  font-size: 14px;
}
.form-group input:focus, .form-group textarea:focus {
  outline: none;
  border-color: var(--primary);
}

.toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  padding: 12px 20px;
  background: var(--text);
  color: var(--primary-text);
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-weight: 500;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  z-index: 10000;
}
.toast-success { background: var(--success); }

/* Theme Variables */
.page-wrap { padding: 0; }
.page-wrap h1 { font-size: 24px; font-weight: 700; margin: 0; }
.page-wrap .subtitle { color: var(--text3); margin: 4px 0 24px; font-size: 14px; }
.page-wrap .card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; margin-bottom: 16px; }
.page-wrap .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.page-wrap .card-title { font-size: 16px; font-weight: 600; }
.page-wrap .btn { padding: 8px 16px; border-radius: var(--radius-sm); border: none; cursor: pointer; font-size: 14px; font-weight: 500; transition: all var(--transition); }
.page-wrap .btn:disabled { opacity: 0.5; cursor: not-allowed; }
.page-wrap .btn-primary { background: var(--primary); color: #fff; }
.page-wrap .btn-primary:hover:not(:disabled) { background: var(--primary-hover); }
.page-wrap .btn-ghost { background: transparent; color: var(--text2); }
.page-wrap .btn-ghost:hover { background: var(--surface2); }
.page-wrap .btn-danger { background: transparent; color: var(--danger); }
.page-wrap .btn-danger:hover { background: var(--danger-bg); }
.page-wrap .btn-sm { padding: 5px 12px; font-size: 13px; }
.page-wrap .empty-state { text-align: center; padding: 48px 20px; color: var(--text3); }

</style>

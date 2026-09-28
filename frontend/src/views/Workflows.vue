<template>
  <div class="workflows-page page-wrap">
    <PageHeader><button class="btn btn-primary" @click="showCreateModal = true">+ 创建工作流</button>
    </PageHeader>

    <div v-if="workflows.length > 0" class="workflows-list">
      <div v-for="wf in workflows" :key="wf.id" class="workflow-card">
        <div class="wf-header">
          <span class="wf-icon"><AppIcon name="RefreshCw" /></span>
          <div class="wf-info">
            <div class="wf-name">{{ wf.name }}</div>
            <div class="wf-desc">{{ wf.description || '暂无描述' }}</div>
          </div>
        </div>
        <div class="wf-pipeline">
          <span v-for="(step, i) in (wf.steps || ['研究员', '写作者'])" :key="i" class="pipeline-step">
            {{ step }}
            <span v-if="i < (wf.steps || []).length - 1" class="pipeline-arrow"> → </span>
          </span>
        </div>
        <div class="wf-actions">
          <button class="btn btn-ghost btn-sm" @click="deleteWorkflow(wf.id)">删除</button>
        </div>
      </div>
    </div>
    <div v-else class="empty-state">
      <div class="empty-icon"><AppIcon name="RefreshCw" /></div>
      <p>暂无工作流，点击上方按钮创建</p>
    </div>

    <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
      <div class="modal-box">
        <div class="modal-header">
          <h3>创建工作流</h3>
          <button class="modal-close" @click="showCreateModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>名称</label>
            <input v-model="form.name" placeholder="例如：内容创作流程" />
          </div>
          <div class="form-group">
            <label>描述</label>
            <textarea v-model="form.description" rows="3" placeholder="工作流的用途描述"></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost" @click="showCreateModal = false">取消</button>
          <button class="btn btn-primary" @click="createWorkflow">创建</button>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { workflowApi } from '../api'

const workflows = ref([])
const showCreateModal = ref(false)
const form = ref({ name: '', description: '' })

const currentWorkspace = () => localStorage.getItem('currentWorkspace')

const showToast = (message, type = 'success') => {
  window.dispatchEvent(new CustomEvent('toast', { detail: { message, type } }))
}

const loadWorkflows = async () => {
  const ws = currentWorkspace()
  if (!ws) return
  try {
    const { data } = await workflowApi.list(ws)
    workflows.value = data
  } catch (e) {
    console.error(e)
  }
}

const createWorkflow = async () => {
  const ws = currentWorkspace()
  if (!ws) { alert('请先选择工作空间'); return }
  if (!form.value.name) { alert('请输入名称'); return }
  try {
    await workflowApi.create(ws, form.value)
    showCreateModal.value = false
    form.value = { name: '', description: '' }
    await loadWorkflows()
    showToast('工作流创建成功')
  } catch (e) {
    alert('创建失败: ' + (e.response?.data?.detail || e.message))
  }
}

const deleteWorkflow = async (id) => {
  const ws = currentWorkspace()
  if (!ws) return
  if (!confirm('确定删除此工作流吗？')) return
  try {
    await workflowApi.delete(ws, id)
    await loadWorkflows()
    showToast('工作流已删除')
  } catch (e) {
    alert('删除失败')
  }
}

onMounted(() => {
  loadWorkflows()
  window.addEventListener('workspace-changed', loadWorkflows)
})
</script>

<style scoped>
.page-header {
  display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 32px;
}
.page-header h1 { font-size: 24px; font-weight: 700; margin-bottom: 4px; }
.subtitle { font-size: 14px; color: var(--text2); }

.workflows-list { display: flex; flex-direction: column; gap: 16px; }
.workflow-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 20px; transition: all 0.2s;
}
.workflow-card:hover { border-color: var(--primary); }
.wf-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.wf-icon { font-size: 32px; }
.wf-name { font-weight: 600; font-size: 15px; }
.wf-desc { font-size: 13px; color: var(--text2); }
.wf-pipeline {
  display: flex; align-items: center; gap: 4px;
  padding: 12px 16px; background: var(--surface2); border-radius: var(--radius-sm);
  margin-bottom: 12px; font-size: 13px;
}
.pipeline-step { color: var(--text); }
.pipeline-arrow { color: var(--text3); margin: 0 4px; }
.wf-actions { display: flex; justify-content: flex-end; }

.empty-state { text-align: center; padding: 80px 20px; color: var(--text3); }
.empty-icon { font-size: 48px; margin-bottom: 16px; }

.modal-overlay {
  display: flex; align-items: center; justify-content: center;
  position: fixed; inset: 0;
  background: var(--overlay); z-index: 9999;
}
.modal-box {
  background: var(--surface-dialog); border-radius: var(--radius);
  width: 480px; max-width: 90vw; box-shadow: var(--shadow-dialog);
}
.modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 20px 24px; border-bottom: 1px solid var(--border);
}
.modal-header h3 { font-size: 16px; font-weight: 600; }
.modal-close { background: none; border: none; font-size: 24px; color: var(--text3); cursor: pointer; }
.modal-body { padding: 24px; }
.modal-footer { display: flex; justify-content: flex-end; gap: 12px; padding: 16px 24px; border-top: 1px solid var(--border); }

.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 10px 20px; border: none; border-radius: var(--radius-sm);
  font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.2s;
}
.btn-primary { background: var(--primary); color: var(--primary-text); }
.btn-primary:hover { background: var(--primary-hover); }
.btn-ghost { background: transparent; color: var(--text2); border: 1px solid var(--border); }
.btn-ghost:hover { background: var(--surface2); }
.btn-sm { padding: 7px 14px; font-size: 13px; }

.form-group { margin-bottom: 16px; }
.form-group label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 6px; }
.form-group input, .form-group textarea {
  width: 100%; padding: 10px 14px;
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: var(--radius-sm); color: var(--text); font-size: 14px;
}
.form-group input:focus, .form-group textarea:focus { outline: none; border-color: var(--primary); }

.toast {
  position: fixed; bottom: 24px; right: 24px;
  padding: 12px 20px; background: var(--text); color: var(--primary-text);
  border-radius: var(--radius-sm); font-size: 14px; z-index: 10000;
}
.toast-success { background: var(--success); }

/* Theme Variables */
.page-wrap { }
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

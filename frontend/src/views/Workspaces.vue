<template>
  <div class="page-wrap">
    <div class="workspace-current">
      <div class="workspace-card">
        <div class="workspace-card-header">
          <h3>{{ workspace?.name || '当前工作空间' }}</h3>
          <span class="workspace-id">{{ workspaceId }}</span>
        </div>

        <div class="form-group">
          <label>空间名称</label>
          <input v-model="form.name" placeholder="工作空间名称" />
        </div>

        <div class="form-group">
          <label>空间描述</label>
          <textarea v-model="form.description" rows="2" placeholder="描述工作空间的用途"></textarea>
        </div>

        <div class="form-group">
          <label>系统提示词</label>
          <p class="form-hint">配置空间级别的系统提示词，将注入到该空间内所有 Agent 的 prompt 中，用于统一空间目标和行为准则。</p>
          <textarea v-model="form.system_prompt" rows="6" placeholder="例如：你是一个专业的营销团队，负责品牌推广和渠道建设..."></textarea>
        </div>

        <div class="form-actions">
          <button class="btn btn-primary" @click="save" :disabled="saving">
            {{ saving ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { auth } from '../auth'
import { workspaceApi } from '../api'

const workspaceId = computed(() => auth.workspaceId)
const workspace = ref(null)
const form = ref({ name: '', description: '', system_prompt: '' })
const saving = ref(false)

onMounted(() => {
  loadWorkspace()
})

async function loadWorkspace() {
  if (!workspaceId.value) return
  try {
    const { data } = await workspaceApi.get(workspaceId.value)
    workspace.value = data
    form.value = {
      name: data.name || '',
      description: data.description || '',
      system_prompt: data.system_prompt || '',
    }
  } catch (e) {
    console.error('Failed to load workspace:', e)
  }
}

async function save() {
  if (!workspaceId.value) return
  saving.value = true
  try {
    await workspaceApi.update(workspaceId.value, form.value)
    window.dispatchEvent(new CustomEvent('toast', { detail: { message: '保存成功', type: 'success' } }))
  } catch (e) {
    console.error('Failed to save workspace:', e)
    window.dispatchEvent(new CustomEvent('toast', { detail: { message: '保存失败', type: 'error' } }))
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.page-wrap { padding: 0; max-width: 800px; }
.page-header { margin-bottom: 24px; }
.page-header h1 { font-size: 24px; font-weight: 700; margin: 0; }
.subtitle { color: var(--text3); font-size: 14px; margin: 4px 0 0; }

.workspace-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px;
}
.workspace-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}
.workspace-card-header h3 { margin: 0; font-size: 18px; }
.workspace-id { font-size: 12px; color: var(--text3); font-family: monospace; }

.form-group { margin-bottom: 20px; }
.form-group label { display: block; font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 6px; }
.form-hint { font-size: 12px; color: var(--text3); margin-bottom: 8px; }
.form-group input,
.form-group textarea {
  width: 100%;
  padding: 10px 14px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  font-size: 14px;
  font-family: inherit;
  resize: vertical;
}
.form-group input:focus,
.form-group textarea:focus {
  outline: none;
  border-color: var(--primary);
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  border: none;
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-primary { background: var(--primary); color: white; }
.btn-primary:hover:not(:disabled) { background: var(--primary-hover); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>

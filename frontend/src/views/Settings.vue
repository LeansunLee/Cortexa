<template>
  <div class="settings">
    <h1>LLM 供应商配置</h1>
    <p class="subtitle">管理 API Key、切换供应商、调整模型参数</p>

    <div class="card">
      <div class="card-header">
        <span class="card-title">当前默认供应商</span>
        <span v-if="defaultProvider" class="badge badge-active">使用中</span>
      </div>
      <div class="default-selector">
        <select v-model="selectedDefault" class="select">
          <option value="">选择供应商</option>
          <option v-for="(p, name) in providers" :key="name" :value="name">{{ name }} ({{ p.model }})</option>
        </select>
        <button class="btn btn-primary" @click="saveDefault">保存</button>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <span class="card-title">供应商列表</span>
        <button class="btn btn-primary btn-sm" @click="openAddModal">+ 添加供应商</button>
      </div>
      <div class="provider-table-wrap">
        <table class="provider-table" v-if="Object.keys(providers).length > 0">
          <thead>
            <tr>
              <th>名称</th>
              <th>类型</th>
              <th>模型</th>
              <th>状态</th>
              <th style="text-align:right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(p, name) in providers" :key="name" :class="{ 'row-active': name === defaultProvider }" @click="editProvider(name, p)">
              <td class="col-name">{{ name }}</td>
              <td>{{ p.kind }}</td>
              <td>{{ p.model }}</td>
              <td>
                <span :class="['badge', name === defaultProvider ? 'badge-active' : 'badge-inactive']">
                  {{ name === defaultProvider ? '默认' : '可用' }}
                </span>
              </td>
              <td class="col-actions" @click.stop>
                <button class="btn btn-ghost btn-sm" @click="testProvider(name)" :disabled="testing[name]">{{ testing[name] ? "测试中..." : "测试" }}</button>
                <button class="btn btn-danger btn-sm" @click="deleteProvider(name)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty-state">
          <p>暂无供应商，点击上方按钮添加</p>
        </div>
      </div>
    </div>

    <!-- Add/Edit Modal -->
    <div v-if="showModal" class="modal" @click.self="showModal = false">
      <div class="modal-box modal-lg">
        <div class="modal-header">
          <h3>{{ editMode ? '编辑供应商' : '添加供应商' }}</h3>
          <button class="modal-close" @click="showModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-group">
              <label>名称</label>
              <input v-model="form.name" :disabled="editMode" placeholder="my-provider" />
            </div>
            <div class="form-group">
              <label>类型</label>
              <select v-model="form.kind">
                <option value="openai">OpenAI 兼容</option>
                <option value="anthropic">Anthropic</option>
                <option value="ollama">Ollama (本地)</option>
              </select>
            </div>
          </div>
          <div class="form-group">
            <label>模型</label>
            <input v-model="form.model" placeholder="deepseek-chat" />
          </div>
          <div class="form-group">
            <label>Base URL（OpenAI 兼容必填）</label>
            <input v-model="form.base_url" placeholder="https://api.deepseek.com/v1" />
          </div>
          <div class="form-group">
            <label>API Key</label>
            <input v-model="form.api_key" type="password" placeholder="sk-..." />
          </div>
          <div class="form-row-3">
            <div class="form-group">
              <label>Temperature</label>
              <input v-model.number="form.temperature" type="number" step="0.1" min="0" max="2" />
            </div>
            <div class="form-group">
              <label>Max Tokens</label>
              <input v-model.number="form.max_tokens" type="number" min="256" max="128000" />
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost" @click="showModal = false">取消</button>
          <button class="btn btn-primary" @click="saveProvider">保存</button>
        </div>
      </div>
    </div>

    <!-- Toast -->
    <div v-if="toast.show" :class="['toast', 'toast-' + toast.type]">{{ toast.message }}</div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { configApi } from '../api'

const testing = ref({})

const providers = ref({})
const defaultProvider = ref('')
const selectedDefault = ref('')
const showModal = ref(false)
const editMode = ref(false)
const editingName = ref('')
const toast = ref({ show: false, message: '', type: 'success' })

const form = ref({
  name: '',
  kind: 'openai',
  model: '',
  base_url: '',
  api_key: '',
  temperature: 0.2,
  max_tokens: 4096
})

const showToast = (message, type = 'success') => {
  toast.value = { show: true, message, type }
  setTimeout(() => { toast.value.show = false }, 3000)
}

const loadConfig = async () => {
  try {
    const { data } = await configApi.get()
    providers.value = data.providers || {}
    defaultProvider.value = data.default_provider || ''
    selectedDefault.value = data.default_provider || ''
  } catch (e) {
    console.error(e)
  }
}

const openAddModal = () => {
  editMode.value = false
  editingName.value = ''
  form.value = { name: '', kind: 'openai', model: '', base_url: '', api_key: '', temperature: 0.2, max_tokens: 4096 }
  showModal.value = true
}

const editProvider = (name, p) => {
  editMode.value = true
  editingName.value = name
  form.value = { name, kind: p.kind, model: p.model, base_url: p.base_url || '', api_key: p.api_key || '', temperature: p.temperature || 0.2, max_tokens: p.max_tokens || 4096 }
  showModal.value = true
}

const saveProvider = async () => {
  if (!form.value.name || !form.value.model) {
    alert('请填写名称和模型')
    return
  }
  try {
    if (editMode.value) {
      await configApi.updateProvider(editingName.value, { ...form.value })
    } else {
      await configApi.addProvider({ ...form.value })
    }
    showModal.value = false
    await loadConfig()
    showToast('供应商保存成功')
  } catch (e) {
    alert('保存失败: ' + (e.response?.data?.detail || e.message))
  }
}

const deleteProvider = async (name) => {
  if (!confirm(`确定删除供应商 "${name}" 吗？`)) return
  try {
    await configApi.deleteProvider(name)
    await loadConfig()
    showToast('供应商已删除')
  } catch (e) {
    alert('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

const testProvider = async (name) => {
  testing.value[name] = true
  try {
    const { data } = await configApi.test(name)
    if (data.status === 'ok') {
      showToast(data.message, 'success')
    } else {
      showToast(data.message || '测试失败', 'error')
    }
  } catch (e) {
    showToast('请求失败: ' + (e.response?.data?.detail || e.message), 'error')
  } finally {
    testing.value[name] = false
  }
}

const saveDefault = async () => {
  try {
    await configApi.setDefault(selectedDefault.value)
    defaultProvider.value = selectedDefault.value
    showToast('默认供应商已更新')
  } catch (e) {
    alert('保存失败: ' + (e.response?.data?.detail || e.message))
  }
}

onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.settings h1 { font-size: 26px; font-weight: 700; margin-bottom: 4px; }
.subtitle { font-size: 14px; color: var(--text2); margin-bottom: 20px; }

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 24px;
  margin-bottom: 16px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.card-title { font-size: 15px; font-weight: 600; }

.default-selector { display: flex; gap: 12px; align-items: center; }
.select {
  flex: 1;
  padding: 10px 14px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 14px;
  color: var(--text);
}

.provider-table-wrap { overflow-x: auto; }
.provider-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}
.provider-table th {
  text-align: left;
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 1px solid var(--border);
}
.provider-table td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
  color: var(--text2);
}
.provider-table tbody tr {
  cursor: pointer;
  transition: background 0.15s;
}
.provider-table tbody tr:hover { background: var(--surface2); }
.provider-table tbody tr.row-active { background: var(--surface2); }
.provider-table .col-name { font-weight: 600; color: var(--text); }
.provider-table .col-actions { text-align: right; white-space: nowrap; }

.badge { padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 500; }
.badge-active { background: var(--success-bg); color: var(--success); }
.badge-inactive { background: var(--surface2); color: var(--text3); }

.empty-state { text-align: center; padding: 32px 20px; color: var(--text3); font-size: 14px; }

.modal {
  display: flex;
  align-items: center;
  justify-content: center;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.5);
  backdrop-filter: blur(4px);
  z-index: 9999;
}
.modal-box {
  background: var(--surface);
  border-radius: var(--radius);
  width: 480px;
  max-width: 90vw;
  box-shadow: 0 20px 60px rgba(0,0,0,0.2);
}
.modal-lg { width: 620px; }
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
}
.modal-close:hover { color: var(--text); }
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
.btn-danger { background: var(--danger-bg); color: var(--danger); border: 1px solid rgba(185,28,28,0.2); }
.btn-danger:hover { background: #FEE2E2; }
.btn-sm { padding: 7px 14px; font-size: 13px; }

.form-group { margin-bottom: 16px; }
.form-group label { display: block; font-size: 14px; font-weight: 600; margin-bottom: 8px; }
.form-group input, .form-group select, .form-group textarea {
  width: 100%;
  padding: 12px 16px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  font-size: 14px;
}
.form-group input:focus, .form-group select:focus {
  outline: none;
  border-color: var(--primary);
}
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.form-row-3 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

.toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  padding: 12px 20px;
  background: var(--text);
  color: var(--primary-text);
  border-radius: var(--radius-sm);
  font-size: 14px;
  z-index: 10000;
}
.toast-success { background: var(--success); }
</style>

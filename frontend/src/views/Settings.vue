<template>
  <div class="settings">
    <section class="card feature-card" aria-labelledby="conversation-debug-heading">
      <div class="feature-row">
        <div class="feature-copy">
          <h2 id="conversation-debug-heading" class="card-title"><Bug :size="18" /> 对话调试窗口</h2>
          <p class="card-desc">记录并展示每轮对话的上下文组装、知识库与记忆检索、工具调用和 Agent 协作传递过程。关闭后不再采集新轨迹，已保存的历史轨迹不会删除。</p>
        </div>
        <label class="switch" :title="conversationDebugEnabled ? '关闭对话调试' : '开启对话调试'">
          <input v-model="conversationDebugEnabled" type="checkbox" :disabled="savingConversationDebug" @change="saveConversationDebug" />
          <span class="switch-track"><span class="switch-thumb"></span></span>
          <span class="switch-label">{{ conversationDebugEnabled ? '已开启' : '已关闭' }}</span>
        </label>
      </div>
    </section>

    <!-- LLM Providers -->
    <section class="card llm-provider-card" aria-labelledby="llm-provider-heading">
      <div class="card-header llm-provider-header">
        <div>
          <h2 id="llm-provider-heading" class="card-title"><Server :size="18" /> LLM 供应商配置</h2>
          <p class="card-desc">管理 API 供应商和模型配置。</p>
        </div>
        <button class="btn btn-primary btn-sm" @click="openAddModal">+ 添加供应商</button>
      </div>
      <div class="provider-default-section">
        <div class="provider-section-label">
          <label for="default-provider">当前默认供应商</label>
          <span v-if="defaultProvider" class="badge badge-active">使用中</span>
        </div>
        <div class="default-selector">
          <SearchSelect
            id="default-provider"
            v-model="selectedDefault"
            class="select"
            :options="defaultProviderOptions"
            placeholder="选择供应商"
            aria-label="当前默认供应商"
          />
          <button class="btn btn-primary" @click="saveDefault">保存</button>
        </div>
      </div>
      <div class="provider-list-heading">
        <h3>供应商列表</h3>
        <span>{{ Object.keys(providers).length }} 个供应商</span>
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
    </section>

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
              <SearchSelect
                v-model="form.kind"
                :options="providerKindOptions"
                placeholder="选择供应商类型"
                aria-label="供应商类型"
              />
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
              <label>最大输出词元</label>
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
  </div>
</template>

<script setup>
import { Server, Bug } from 'lucide-vue-next'

import { computed, ref, onMounted } from 'vue'
import { configApi } from '../api'

const testing = ref({})
const conversationDebugEnabled = ref(false)
const savingConversationDebug = ref(false)


const providers = ref({})
const defaultProvider = ref('')
const selectedDefault = ref('')
const showModal = ref(false)
const editMode = ref(false)
const editingName = ref('')

const form = ref({
  name: '',
  kind: 'openai',
  model: '',
  base_url: '',
  api_key: '',
  temperature: 0.2,
  max_tokens: 4096
})

const providerKindOptions = [
  { value: 'openai', label: 'OpenAI 兼容' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'ollama', label: 'Ollama (本地)' },
]

const defaultProviderOptions = computed(() => [
  { value: '', label: '选择供应商' },
  ...Object.entries(providers.value).map(([name, p]) => ({
    value: name,
    label: name + ' (' + (p.model || '未设置模型') + ')',
  })),
])

const showToast = (message, type = 'success') => {
  window.dispatchEvent(new CustomEvent('toast', { detail: { message, type } }))
}

const loadConfig = async () => {
  // Theme is already initialized from ref defaults

  try {
    const { data } = await configApi.get()
    providers.value = data.providers || {}
    defaultProvider.value = data.default_provider || ''
    selectedDefault.value = data.default_provider || ''
    conversationDebugEnabled.value = Boolean(data.conversation_debug_enabled)
  } catch (e) {
    console.error(e)
  }
}

const saveConversationDebug = async () => {
  const enabled = conversationDebugEnabled.value
  savingConversationDebug.value = true
  try {
    await configApi.saveConversationDebug(enabled)
    window.dispatchEvent(new CustomEvent('conversation-debug-config', { detail: { enabled } }))
    showToast(enabled ? '对话调试窗口已开启' : '对话调试窗口已关闭')
  } catch (error) {
    conversationDebugEnabled.value = !enabled
    showToast('保存失败: ' + (error.response?.data?.detail || error.message), 'error')
  } finally {
    savingConversationDebug.value = false
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
.settings { padding: 0; max-width: 900px; }
.settings h1 { font-size: 24px; font-weight: 700; margin: 0; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; margin-bottom: 16px; }
.feature-row { display: flex; align-items: center; justify-content: space-between; gap: 24px; }
.feature-copy { min-width: 0; }
.feature-copy .card-title { display: flex; align-items: center; gap: 8px; margin: 0; }
.feature-copy .card-desc { max-width: 660px; margin: 7px 0 0; line-height: 1.65; }
.switch { display: inline-flex; align-items: center; gap: 9px; flex-shrink: 0; cursor: pointer; }
.switch input { position: absolute; opacity: 0; pointer-events: none; }
.switch-track { width: 42px; height: 24px; padding: 2px; box-sizing: border-box; border-radius: 999px; background: var(--border); transition: background var(--transition); }
.switch-thumb { display: block; width: 20px; height: 20px; border-radius: 50%; background: var(--surface); box-shadow: 0 1px 3px rgba(0,0,0,.2); transition: transform var(--transition); }
.switch input:checked + .switch-track { background: var(--primary); }
.switch input:checked + .switch-track .switch-thumb { transform: translateX(18px); }
.switch input:focus-visible + .switch-track { outline: 2px solid var(--primary); outline-offset: 2px; }
.switch input:disabled + .switch-track { opacity: .55; }
.switch-label { min-width: 42px; color: var(--text2); font-size: 12px; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.card-title { font-size: 16px; font-weight: 600; }
.card-desc { font-size: 13px; color: var(--text3); margin: 0 0 16px; }
.default-selector { display: flex; gap: 8px; align-items: center; }
.select { flex: 1; padding: 8px 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); font-size: 14px; }
.provider-table-wrap { overflow-x: auto; }
.provider-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.provider-table th { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); font-weight: 500; color: var(--text2); font-size: 13px; }
.provider-table td { padding: 10px 12px; border-bottom: 1px solid var(--border); }
.provider-table tr:hover { background: var(--surface2); }
.col-name { font-weight: 500; }
.col-actions { text-align: right; }
.row-active { background: var(--primary-light) !important; }
.badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 500; }
.badge-active { background: var(--success-bg); color: var(--success); }
.badge-inactive { background: var(--surface2); color: var(--text3); }
.empty-state { text-align: center; padding: 32px; color: var(--text3); }
.btn { padding: 8px 16px; border-radius: var(--radius-sm); border: none; cursor: pointer; font-size: 14px; font-weight: 500; transition: all var(--transition); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: var(--primary); color: #fff; }
.btn-primary:hover:not(:disabled) { background: var(--primary-hover); }
.btn-ghost { background: transparent; color: var(--text2); }
.btn-ghost:hover { background: var(--surface2); }
.btn-danger { background: transparent; color: var(--danger); }
.btn-danger:hover { background: var(--danger-bg); }
.btn-sm { padding: 5px 12px; font-size: 13px; }
.form-group { margin-bottom: 16px; }
.form-group label { display: block; font-size: 13px; font-weight: 500; margin-bottom: 6px; color: var(--text); }
.form-group input, .form-group select, .form-group textarea {
  width: 100%; padding: 10px 14px; border: 1px solid var(--border); border-radius: 10px;
  font-size: 14px; box-sizing: border-box; transition: all var(--transition);
}
.form-group input:focus, .form-group select:focus, .form-group textarea:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(139,92,246,0.1);
}
.form-row { display: flex; gap: 16px; }
.form-row .form-group { flex: 1; }
.modal { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal-box { background: var(--surface); color: var(--text); border-radius: var(--radius); padding: 0; width: 560px; max-width: 90vw; max-height: 85vh; overflow-y: auto; box-shadow: var(--shadow-md); }
.modal-lg { width: 640px; }
.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid var(--border); }
.modal-header h3 { margin: 0; font-size: 18px; font-weight: 600; }
.modal-close { background: none; border: none; font-size: 20px; cursor: pointer; color: var(--text3); padding: 4px 8px; }
.modal-body { padding: 20px; }
.modal-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 16px 20px; border-top: 1px solid var(--border); }
.test-result-box { margin-top: 12px; padding: 12px; border-radius: var(--radius-sm); font-size: 13px; }
.test-result-box.success { background: var(--success-bg); color: var(--success); }
.test-result-box.error { background: var(--danger-bg); color: var(--danger); }

.llm-provider-header { align-items: flex-start; gap: 16px; margin-bottom: 20px; }
.llm-provider-header .card-title { display: flex; align-items: center; gap: 8px; margin: 0; line-height: 24px; }
.llm-provider-header .card-desc { margin: 6px 0 0; line-height: 20px; }
.llm-provider-header > button { flex-shrink: 0; }
.provider-default-section { padding: 16px; background: var(--surface2); border-radius: 8px; }
.provider-section-label { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 13px; font-weight: 550; }
.provider-default-section .default-selector select { min-width: 0; }
.provider-default-section .default-selector button { flex-shrink: 0; }
.provider-list-heading { display: flex; align-items: center; gap: 10px; margin: 24px 0 8px; }
.provider-list-heading h3 { margin: 0; font-size: 14px; font-weight: 600; }
.provider-list-heading > span { color: var(--text3); font-size: 12px; }
.llm-provider-card .provider-table tbody tr:last-child td { border-bottom: 0; }
@media (max-width: 640px) {
  .feature-row { align-items: flex-start; flex-direction: column; gap: 14px; }
  .llm-provider-header { flex-wrap: wrap; }
  .provider-default-section { padding: 12px; }
  .llm-provider-card .provider-table { min-width: 580px; }
}
</style>

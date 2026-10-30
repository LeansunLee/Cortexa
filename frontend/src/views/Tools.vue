<template>
  <div class="tools-page">
    <div class="section-header">
      <h3>工具</h3>
      <div class="header-actions">
        <button class="btn btn-ghost btn-sm" @click="showImport = true">导入清单</button>
        <button class="btn btn-primary btn-sm" @click="openCreate">+ 注册工具</button>
      </div>
    </div>
    <p class="page-hint">外部工具经 manifest 注册后即可绑定到智能体；执行走服务端代理，凭证加密存储、不进入提示词与日志。工具返回内容按不可信数据处理。</p>

    <div v-if="tools.length === 0" class="empty-hint">暂无注册工具。联网搜索为内置工具，可在智能体编辑页开启。</div>

    <div v-for="tool in tools" :key="tool.id" class="card">
      <div class="card-header">
        <div>
          <div class="card-name">
            <span :class="['type-badge', 'provider-' + tool.provider_type]">{{ providerLabel(tool.provider_type) }}</span>
            {{ tool.name }}
            <span v-if="tool.status === 'disabled'" class="status-badge status-disabled">已停用</span>
            <span v-else class="status-badge status-active">启用</span>
            <span :class="['health-badge', 'health-' + tool.health_status]">{{ healthLabel(tool.health_status) }}</span>
          </div>
          <div class="card-meta">{{ tool.description }}</div>
          <div class="card-meta mono">{{ endpointSummary(tool) }}</div>
        </div>
        <div class="card-actions" v-if="tool.provider_type !== 'builtin'">
          <button class="btn btn-ghost btn-sm" @click="testTool(tool)"><Zap :size="14" /> 测连</button>
          <button class="btn btn-ghost btn-sm" @click="openBind(tool)"><Plug :size="14" /> 绑定</button>
          <button class="btn btn-ghost btn-sm" @click="openEdit(tool)"><Edit :size="14" /> 编辑</button>
          <button class="btn btn-ghost btn-sm" @click="toggleStatus(tool)">{{ tool.status === 'active' ? '停用' : '启用' }}</button>
          <button class="btn btn-danger btn-sm" @click="deleteTool(tool.id)">删除</button>
        </div>
        <div class="card-actions" v-else>
          <span class="builtin-note">内置工具 · 在智能体编辑页管理</span>
        </div>
      </div>
      <div v-if="tool._testResult" :class="['test-result', tool._testResult.ok ? 'success' : 'error']">
        {{ tool._testResult.detail }}<template v-if="tool._testResult.latency_ms != null"> · {{ tool._testResult.latency_ms }}ms</template>
      </div>
    </div>

    <!-- Create / Edit Modal -->
    <div v-if="showEditor" class="modal-overlay" @click.self="showEditor = false">
      <div class="modal modal-wide">
        <div class="modal-heading">
          <h3>{{ editingId ? '编辑工具' : '注册工具' }}</h3>
          <button type="button" class="modal-close" aria-label="关闭工具编辑弹窗" @click="showEditor = false">×</button>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>工具名 * <LlmContextHint text="会作为模型可见的工具调用名；小写字母/数字/下划线，如 weather_query。" /></label>
            <input v-model="form.name" placeholder="例如：weather_query" />
          </div>
          <div class="form-group">
            <label>提供方类型 *</label>
            <select v-model="form.provider_type" class="select-field">
              <option value="http">HTTP API</option>
              <option value="mcp">MCP 服务器</option>
            </select>
          </div>
        </div>
        <div class="form-group">
          <label>描述 * <LlmContextHint text="逐字注入模型工具列表，模型据此决定何时调用；请写清适用场景与不适用场景。" /></label>
          <textarea v-model="form.description" rows="2" placeholder="说明工具做什么、何时应该调用、输入是什么。"></textarea>
        </div>

        <template v-if="form.provider_type === 'http'">
          <div class="form-row">
            <div class="form-group">
              <label>端点 URL * <LlmContextHint text="仅管理员可配；默认必须公网地址，内网服务需显式勾选允许内网。" /></label>
              <input v-model="form.http.url" placeholder="https://api.example.com/v1/query" />
            </div>
            <div class="form-group form-narrow">
              <label>方法</label>
              <select v-model="form.http.method" class="select-field">
                <option value="GET">GET</option>
                <option value="POST">POST</option>
              </select>
            </div>
          </div>
          <div class="form-row">
            <div class="form-group form-narrow">
              <label>认证方式</label>
              <select v-model="form.http.auth_type" class="select-field">
                <option value="none">无</option>
                <option value="bearer">Bearer</option>
                <option value="header">自定义头</option>
              </select>
            </div>
            <div class="form-group form-narrow" v-if="form.http.auth_type === 'header'">
              <label>认证头名称</label>
              <input v-model="form.http.auth_header" placeholder="X-API-KEY" />
            </div>
            <div class="form-group">
              <label>凭证 <span v-if="editingHasSecret" class="secret-note">已保存（留空则不修改）</span></label>
              <input v-model="form.secret" type="password" autocomplete="new-password" placeholder="API Key / Token" />
            </div>
          </div>
          <label class="checkbox-row">
            <input type="checkbox" v-model="form.http.allow_private" />
            允许内网地址 <small>（仅限自建/企业内网服务，请确认网络边界后再开启）</small>
          </label>
        </template>

        <template v-else>
          <div class="form-row">
            <div class="form-group">
              <label>MCP 服务器 URL * <LlmContextHint text="streamable HTTP 传输；工具名将加前缀 mcp__前缀__原工具名。" /></label>
              <input v-model="form.mcp.url" placeholder="https://mcp.example.com/mcp" />
            </div>
            <div class="form-group form-narrow">
              <label>工具名前缀</label>
              <input v-model="form.mcp.tool_prefix" placeholder="留空则用工具名" />
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>凭证 <span v-if="editingHasSecret" class="secret-note">已保存（留空则不修改）</span></label>
              <input v-model="form.secret" type="password" autocomplete="new-password" placeholder="Bearer Token" />
            </div>
          </div>
          <label class="checkbox-row">
            <input type="checkbox" v-model="form.mcp.allow_private" />
            允许内网地址
          </label>
        </template>

        <div class="form-group">
          <label>参数定义 <LlmContextHint text="会导出为 JSON Schema 供模型填写；参数说明请写业务含义，模型据此生成入参。" /></label>
          <div v-for="(param, index) in form.parameters" :key="index" class="param-row">
            <input v-model="param.name" placeholder="参数名" class="param-input" />
            <select v-model="param.type" class="select-field param-input">
              <option value="string">string</option>
              <option value="integer">integer</option>
              <option value="number">number</option>
              <option value="boolean">boolean</option>
            </select>
            <label class="checkbox-row param-required"><input type="checkbox" v-model="param.required" /> 必填</label>
            <input v-model="param.description" placeholder="参数说明" class="param-input param-desc" />
            <button class="btn btn-ghost btn-sm" @click="form.parameters.splice(index, 1)"><X :size="14" /></button>
          </div>
          <button class="btn btn-ghost btn-sm" @click="form.parameters.push({ name: '', type: 'string', required: false, description: '', default: null })">+ 添加参数</button>
        </div>

        <div class="form-row">
          <div class="form-group form-narrow">
            <label>风险等级</label>
            <select v-model="form.risk_level" class="select-field">
              <option value="low">低</option>
              <option value="high">高（执行需确认）</option>
            </select>
          </div>
          <div class="form-group form-narrow">
            <label>超时(秒)</label>
            <input type="number" v-model.number="form.timeout" min="1" max="60" />
          </div>
          <div class="form-group form-narrow">
            <label>单目标次数上限</label>
            <input type="number" v-model.number="form.quota_per_goal" min="1" max="20" />
          </div>
          <div class="form-group form-narrow">
            <label>响应注入上限(字符)</label>
            <input type="number" v-model.number="form.input_budget" min="500" max="20000" />
          </div>
        </div>
        <div class="form-group">
          <label>使用规则 <LlmContextHint text="注入提示词的安全与使用条款，如引用要求、禁止行为；返回内容一律按参考数据处理，不会当作指令执行。" /></label>
          <textarea v-model="form.usage_rules" rows="2" placeholder="例如：引用结果需标注来源；失败时如实说明，不得编造。"></textarea>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>别名（逗号分隔）</label>
            <input v-model="aliasesText" placeholder="天气, 气象" />
          </div>
          <div class="form-group">
            <label>领域（逗号分隔）</label>
            <input v-model="domainsText" placeholder="天气, 出行" />
          </div>
        </div>

        <div v-if="formError" class="error-msg">{{ formError }}</div>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="showEditor = false">取消</button>
          <button class="btn btn-primary" @click="save" :disabled="!form.name || !form.description">{{ editingId ? '保存' : '注册' }}</button>
        </div>
      </div>
    </div>

    <!-- Import manifest modal -->
    <div v-if="showImport" class="modal-overlay" @click.self="showImport = false">
      <div class="modal">
        <div class="modal-heading">
          <h3>导入工具清单</h3>
          <button type="button" class="modal-close" aria-label="关闭导入清单弹窗" @click="showImport = false">×</button>
        </div>
        <div class="form-group">
          <label>Manifest JSON</label>
          <textarea v-model="importText" rows="12" class="mono" placeholder='{"name":"...","description":"...","provider_type":"http","http":{"url":"...","method":"POST"},"parameters":[...]}'></textarea>
        </div>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="showImport = false">取消</button>
          <button class="btn btn-ghost" @click="validateImport" :disabled="!importText">校验</button>
          <button class="btn btn-primary" @click="importManifest" :disabled="!importText">导入并编辑</button>
        </div>
      </div>
    </div>

    <!-- Bind agents modal -->
    <div v-if="binding" class="modal-overlay" @click.self="binding = null">
      <div class="modal">
        <div class="modal-heading">
          <h3>绑定智能体 · {{ binding.name }}</h3>
          <button type="button" class="modal-close" aria-label="关闭绑定弹窗" @click="binding = null">×</button>
        </div>
        <div v-if="agents.length === 0" class="empty-hint">当前空间暂无智能体</div>
        <div v-for="agent in agents" :key="agent.id" class="checkbox-row">
          <label>
            <input type="checkbox" :value="agent.id" v-model="bindingAgentIds" />
            {{ agent.name }}
          </label>
        </div>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="binding = null">取消</button>
          <button class="btn btn-primary" @click="saveBind">保存绑定</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Zap, Edit, X, Plug } from 'lucide-vue-next'
import { ref, computed, onMounted } from 'vue'
import { toolApi } from '../api'
import LlmContextHint from '../components/LlmContextHint.vue'

const tools = ref([])
const agents = ref([])
const showEditor = ref(false)
const showImport = ref(false)
const importText = ref('')
const editingId = ref(null)
const editingHasSecret = ref(false)
const formError = ref('')
const binding = ref(null)
const bindingAgentIds = ref([])

const emptyForm = () => ({
  name: '',
  description: '',
  provider_type: 'http',
  http: { url: '', method: 'POST', auth_type: 'bearer', auth_header: 'X-API-KEY', allow_private: false },
  mcp: { url: '', tool_prefix: '', allow_private: false },
  secret: '',
  parameters: [],
  risk_level: 'low',
  timeout: 10,
  quota_per_goal: 5,
  input_budget: 4000,
  usage_rules: '',
  aliases: [],
  domains: []
})
const form = ref(emptyForm())

const aliasesText = computed({
  get: () => (form.value.aliases || []).join(', '),
  set: value => { form.value.aliases = value.split(/[,，]/).map(item => item.trim()).filter(Boolean) }
})
const domainsText = computed({
  get: () => (form.value.domains || []).join(', '),
  set: value => { form.value.domains = value.split(/[,，]/).map(item => item.trim()).filter(Boolean) }
})

const showToast = (msg, type = 'success') => {
  window.dispatchEvent(new CustomEvent('toast', { detail: { message: msg, type } }))
}

const providerLabel = type => ({ builtin: '内置', http: 'HTTP', mcp: 'MCP' })[type] || type
const healthLabel = status => ({ healthy: '健康', unhealthy: '异常', unknown: '未测' })[status] || status
const endpointSummary = tool => {
  if (tool.provider_type === 'http') return `${tool.endpoint?.method || 'POST'} ${tool.endpoint?.url || ''}`
  if (tool.provider_type === 'mcp') return `MCP ${tool.endpoint?.url || ''}`
  return '系统内置'
}

const buildManifest = () => {
  const manifest = {
    name: form.value.name.trim(),
    description: form.value.description.trim(),
    provider_type: form.value.provider_type,
    parameters: form.value.parameters.filter(p => p.name.trim()).map(p => ({
      name: p.name.trim(), type: p.type, required: !!p.required,
      description: (p.description || '').trim(), ...(p.default !== null && p.default !== '' ? { default: p.default } : {})
    })),
    risk_level: form.value.risk_level,
    timeout: Number(form.value.timeout) || 10,
    quota: { per_goal: Number(form.value.quota_per_goal) || 5 },
    input_budget: Number(form.value.input_budget) || 4000
  }
  if (form.value.usage_rules.trim()) manifest.usage_rules = form.value.usage_rules.trim()
  if (form.value.aliases.length) manifest.aliases = form.value.aliases
  if (form.value.domains.length) manifest.domains = form.value.domains
  if (form.value.provider_type === 'http') {
    manifest.http = {
      url: form.value.http.url.trim(), method: form.value.http.method,
      auth: { type: form.value.http.auth_type, header: form.value.http.auth_header || 'Authorization', prefix: 'Bearer' },
      allow_private: !!form.value.http.allow_private
    }
  } else {
    manifest.mcp = {
      url: form.value.mcp.url.trim(), tool_prefix: (form.value.mcp.tool_prefix || '').trim(),
      allow_private: !!form.value.mcp.allow_private
    }
  }
  return manifest
}

const loadTools = async () => {
  try { const { data } = await toolApi.list(); tools.value = data } catch {}
}

const loadAgents = async () => {
  try { const { data } = await toolApi.agentsLookup(); agents.value = data } catch {}
}

const openCreate = () => {
  editingId.value = null
  editingHasSecret.value = false
  form.value = emptyForm()
  formError.value = ''
  showEditor.value = true
}

const openEdit = tool => {
  editingId.value = tool.id
  editingHasSecret.value = !!tool.has_secret
  formError.value = ''
  const manifest = tool.manifest || {}
  const http = tool.endpoint || {}
  const auth = http.auth || {}
  form.value = {
    name: tool.name,
    description: tool.description || '',
    provider_type: tool.provider_type,
    http: { url: http.url || '', method: http.method || 'POST', auth_type: auth.type || 'none', auth_header: auth.header || 'X-API-KEY', allow_private: !!http.allow_private },
    mcp: { url: http.url || '', tool_prefix: http.tool_prefix || '', allow_private: !!http.allow_private },
    secret: '',
    parameters: (manifest.parameters || []).map(p => ({ name: p.name, type: p.type, required: !!p.required, description: p.description || '', default: p.default ?? null })),
    risk_level: manifest.risk_level || 'low',
    timeout: manifest.timeout || 10,
    quota_per_goal: manifest.quota?.per_goal || 5,
    input_budget: manifest.input_budget || 4000,
    usage_rules: manifest.usage_rules || '',
    aliases: manifest.aliases || [],
    domains: manifest.domains || []
  }
  showEditor.value = true
}

const save = async () => {
  formError.value = ''
  const payload = { manifest: buildManifest(), secret: form.value.secret }
  try {
    if (editingId.value) {
      await toolApi.update(editingId.value, payload)
      showToast('已保存')
    } else {
      await toolApi.create(payload)
      showToast('已注册')
    }
    showEditor.value = false
    await loadTools()
  } catch (e) {
    formError.value = e.response?.data?.detail || e.message
  }
}

const toggleStatus = async tool => {
  const next = tool.status === 'active' ? 'disabled' : 'active'
  try { await toolApi.status(tool.id, next); await loadTools(); showToast(next === 'active' ? '已启用' : '已停用') }
  catch (e) { showToast(e.response?.data?.detail || '操作失败', 'error') }
}

const deleteTool = async id => {
  if (!window.confirm('删除后已绑定的智能体将无法再调用该工具，确定删除？')) return
  try { await toolApi.delete(id); await loadTools(); showToast('已删除') }
  catch (e) { showToast(e.response?.data?.detail || '删除失败', 'error') }
}

const testTool = async tool => {
  tool._testResult = { ok: null, detail: '测试中…' }
  try {
    const { data } = await toolApi.test(tool.id)
    tool._testResult = data
    await loadTools()
  } catch (e) {
    tool._testResult = { ok: false, detail: e.response?.data?.detail || '请求失败' }
  }
}

const openBind = async tool => {
  binding.value = tool
  bindingAgentIds.value = agents.value.filter(agent => (agent.tool_ids || []).includes(tool.id)).map(agent => agent.id)
  if (agents.value.length === 0) await loadAgents()
  bindingAgentIds.value = agents.value.filter(agent => (agent.tool_ids || []).includes(tool.id)).map(agent => agent.id)
}

const saveBind = async () => {
  try {
    await toolApi.bind(binding.value.id, bindingAgentIds.value)
    showToast('绑定已保存')
    binding.value = null
    await loadAgents()
  } catch (e) { showToast(e.response?.data?.detail || '保存失败', 'error') }
}

const validateImport = async () => {
  try {
    const { data } = await toolApi.validate({ manifest: JSON.parse(importText.value) })
    showToast(`清单有效：${data.name}`)
  } catch (e) { showToast(e.response?.data?.detail || '清单无效', 'error') }
}

const importManifest = async () => {
  let manifest
  try { manifest = JSON.parse(importText.value) } catch { showToast('JSON 解析失败', 'error'); return }
  editingId.value = null
  editingHasSecret.value = false
  formError.value = ''
  const http = manifest.http || {}
  const auth = http.auth || {}
  const mcp = manifest.mcp || {}
  form.value = {
    name: manifest.name || '',
    description: manifest.description || '',
    provider_type: manifest.provider_type || 'http',
    http: { url: http.url || '', method: http.method || 'POST', auth_type: auth.type || 'none', auth_header: auth.header || 'X-API-KEY', allow_private: !!http.allow_private },
    mcp: { url: mcp.url || '', tool_prefix: mcp.tool_prefix || '', allow_private: !!mcp.allow_private },
    secret: '',
    parameters: (manifest.parameters || []).map(p => ({ name: p.name, type: p.type, required: !!p.required, description: p.description || '', default: p.default ?? null })),
    risk_level: manifest.risk_level || 'low',
    timeout: manifest.timeout || 10,
    quota_per_goal: manifest.quota?.per_goal || 5,
    input_budget: manifest.input_budget || 4000,
    usage_rules: manifest.usage_rules || '',
    aliases: manifest.aliases || [],
    domains: manifest.domains || []
  }
  showImport.value = false
  showEditor.value = true
}

onMounted(() => { loadTools(); loadAgents() })
</script>

<style scoped>
.tools-page { max-width: 900px; }
.section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.section-header h3 { margin: 0; }
.header-actions { display: flex; gap: 8px; }
.page-hint { color: var(--text-secondary, #888); font-size: 12px; margin: 4px 0 16px; }
.empty-hint { color: var(--text-secondary, #888); padding: 32px 0; text-align: center; }
.card { border: 1px solid var(--border-color, #e5e7eb); border-radius: 10px; padding: 14px 16px; margin-bottom: 12px; background: var(--card-bg, #fff); }
.card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.card-name { font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.card-meta { color: var(--text-secondary, #888); font-size: 12px; margin-top: 4px; }
.mono { font-family: ui-monospace, monospace; }
.card-actions { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.builtin-note { color: var(--text-secondary, #888); font-size: 12px; }
.type-badge { font-size: 11px; padding: 1px 7px; border-radius: 999px; color: #fff; }
.provider-http { background: #3b82f6; }
.provider-mcp { background: #8b5cf6; }
.provider-builtin { background: #6b7280; }
.status-badge { font-size: 11px; padding: 1px 7px; border-radius: 999px; }
.status-active { background: #dcfce7; color: #15803d; }
.status-disabled { background: #f3f4f6; color: #6b7280; }
.health-badge { font-size: 11px; padding: 1px 7px; border-radius: 999px; background: #f3f4f6; color: #6b7280; }
.health-healthy { background: #dcfce7; color: #15803d; }
.health-unhealthy { background: #fee2e2; color: #b91c1c; }
.test-result { margin-top: 10px; padding: 6px 10px; border-radius: 8px; font-size: 12px; }
.test-result.success { background: #dcfce7; color: #15803d; }
.test-result.error { background: #fee2e2; color: #b91c1c; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.4); display: flex; align-items: center; justify-content: center; z-index: 50; }
.modal { background: var(--card-bg, #fff); border-radius: 12px; padding: 20px 22px; width: 520px; max-height: 85vh; overflow-y: auto; }
.modal-wide { width: 680px; }
.modal-heading { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.modal-heading h3 { margin: 0; }
.modal-close { border: none; background: none; font-size: 18px; cursor: pointer; color: var(--text-secondary, #888); }
.form-group { margin-bottom: 12px; flex: 1; }
.form-group label { display: block; font-size: 13px; margin-bottom: 4px; }
.form-group input, .form-group textarea, .select-field { width: 100%; box-sizing: border-box; border: 1px solid var(--border-color, #d1d5db); border-radius: 8px; padding: 7px 10px; font-size: 13px; background: var(--input-bg, #fff); color: var(--text-primary, #111); }
.form-row { display: flex; gap: 12px; }
.form-narrow { flex: 0 0 auto; width: 160px; }
.form-group small { color: var(--text-secondary, #888); }
.secret-note { color: #15803d; font-size: 12px; }
.checkbox-row { display: flex; align-items: center; gap: 6px; font-size: 13px; margin: 6px 0; }
.param-row { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
.param-input { flex: 1; min-width: 0; }
.param-desc { flex: 2; }
.param-required { flex: 0 0 auto; white-space: nowrap; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.error-msg { background: #fee2e2; color: #b91c1c; padding: 8px 10px; border-radius: 8px; font-size: 12px; margin-top: 8px; white-space: pre-wrap; }
</style>

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

      <section v-if="can('workspace.manage')" class="workspace-card runtime-card" aria-labelledby="runtime-policy-title">
        <div class="workspace-card-header">
          <div>
            <h3 id="runtime-policy-title"><SlidersHorizontal :size="19" /> Runtime Policy <small>运行策略</small></h3>
            <p class="form-hint">控制本工作空间内 Agent 的执行预算与协作权限；Agent 默认动态继承。</p>
          </div>
        </div>
        <template v-if="runtimeLoaded">
          <div class="runtime-section-title"><Gauge :size="17" /> Execution Budget <small>执行预算</small></div>
          <div class="budget-grid">
            <div v-for="field in budgetFields" :key="field.key" class="budget-field">
              <label :for="`budget-${field.key}`" class="budget-label"><component :is="field.icon" :size="15" /> {{ field.label }} <small>{{ field.zh }}</small><small class="budget-range">{{ runtimeUnlimited[field.key] ? '不限' : `${field.min}–${runtimeLimits[field.key]}` }}</small></label>
              <div class="budget-control">
                <input :id="`budget-${field.key}`" v-model.number="runtimeBudget[field.key]" type="number" :min="field.min" :max="runtimeLimits[field.key]" :disabled="runtimeUnlimited[field.key]" :aria-invalid="Boolean(runtimeErrors[field.key])" :aria-describedby="runtimeErrors[field.key] ? `budget-error-${field.key}` : undefined" :data-budget-key="field.key" step="1" />
                <label class="budget-unlimited"><input v-model="runtimeUnlimited[field.key]" type="checkbox" :aria-label="`${field.zh}不限`" />不限</label>
              </div>
              <small v-if="!runtimeUnlimited[field.key] && field.suggest" class="budget-hint">建议不超过 {{ field.suggest }}{{ field.suggestNote ? `（${field.suggestNote}）` : '' }}</small>
              <small v-if="runtimeErrors[field.key]" :id="`budget-error-${field.key}`" class="budget-error">{{ runtimeErrors[field.key] }}</small>
            </div>
          </div>
          <div class="runtime-section-title"><UsersRound :size="17" /> Collaboration Mode <small>协作方式</small></div>
          <div class="form-group runtime-collaboration-field">
            <label>Allowed Collaboration Mode <small>允许的最高协作方式</small></label>
            <SearchSelect v-model="runtimeMode" :options="collaborationOptions" aria-label="允许的最高协作方式" />
            <p class="form-hint">对话默认「不主动」。选择「询问」时，对话可选不主动或询问；选择「主动」时，三种方式均可选。用户明确 @ 的 Agent 仍受权限与预算约束。</p>
          </div>
          <div class="form-actions">
            <button class="btn btn-primary" type="button" :disabled="runtimeSaving" @click="saveRuntimePolicy">
              <Save :size="16" /> {{ runtimeSaving ? '保存中...' : 'Save Runtime Policy · 保存运行策略' }}
            </button>
          </div>
        </template>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { Gauge, SlidersHorizontal, UsersRound, Save, Clock3, BrainCircuit, Wrench, Repeat2, Globe2, Network, Layers3, MessagesSquare, ListChecks, RefreshCw, ShieldAlert } from 'lucide-vue-next'
import { auth, can } from '../auth'
import { workspaceApi } from '../api'

const workspaceId = computed(() => auth.workspaceId)
const workspace = ref(null)
const form = ref({ name: '', description: '', system_prompt: '' })
const saving = ref(false)
const runtimeLoaded = ref(false)
const runtimeSaving = ref(false)
const runtimeBudget = ref({})
const runtimeUnlimited = ref({})
const runtimeDefaults = ref({})
const runtimeLimits = ref({})
const runtimeMode = ref('EXPLICIT_ONLY')
const runtimeCollaboration = ref({})
const runtimeErrors = computed(() => Object.fromEntries(budgetFields.map(field => {
  if (runtimeUnlimited.value[field.key]) return [field.key, '']
  const value = runtimeBudget.value[field.key]
  const max = runtimeLimits.value[field.key]
  const valid = value !== '' && value !== null && value !== undefined &&
    Number.isSafeInteger(Number(value)) && Number(value) >= field.min && Number(value) <= max
  return [field.key, valid ? '' : `请输入 ${field.min}–${max} 的整数`]
})))
const collaborationOptions = [
  { value: 'EXPLICIT_ONLY', label: '不主动 · 仅用户主动 @ 的 Agent 可以协作' },
  { value: 'ASK_BEFORE_COLLABORATION', label: '询问 · 需要其他 Agent 协作时询问用户' },
  { value: 'AUTONOMOUS', label: '主动 · 由 Agent 自行决策' },
]
const budgetFields = [
  { key: 'duration', label: 'Max Duration', zh: '最长执行时间（秒）', icon: Clock3, min: 1, suggest: 600, suggestNote: '常规任务 180 足够' },
  { key: 'llm_calls', label: 'Max LLM Calls', zh: '模型调用次数', icon: BrainCircuit, min: 0, suggest: 20 },
  { key: 'tool_calls', label: 'Max Tool Calls', zh: '工具调用次数', icon: Wrench, min: 0, suggest: 30 },
  { key: 'tool_iterations', label: 'Max Tool Iterations', zh: '工具执行轮次', icon: Repeat2, min: 0, suggest: 8 },
  { key: 'web_calls', label: 'Max Web Calls', zh: '网页搜索次数', icon: Globe2, min: 0, suggest: 8, suggestNote: '深度对比类可到 10' },
  { key: 'agent_calls', label: 'Max Agent Calls', zh: '协作调用次数', icon: UsersRound, min: 0, suggest: 8 },
  { key: 'agent_depth', label: 'Max Agent Depth', zh: '协作层级', icon: Network, min: 0, suggest: 2, suggestNote: '每层开销成倍放大' },
  { key: 'context_tokens', label: 'Max Context Tokens', zh: '单次上下文额度', icon: Layers3, min: 256, suggest: 128000, suggestNote: '不超过模型上下文窗口' },
  { key: 'output_tokens', label: 'Max Output Tokens', zh: '累计输出额度', icon: MessagesSquare, min: 0, suggest: 32768 },
  { key: 'max_steps', label: 'Max Steps', zh: '目标步骤', icon: ListChecks, min: 1, suggest: 64 },
  { key: 'max_replans', label: 'Max Replans', zh: '重新规划次数', icon: RefreshCw, min: 0, suggest: 3 },
  { key: 'max_failures', label: 'Max Failures', zh: '失败次数', icon: ShieldAlert, min: 1, suggest: 5 },
  { key: 'max_collaborators', label: 'Max Collaborators', zh: '参与协作的 Agent 数量', icon: UsersRound, min: 0, suggest: 3, suggestNote: '每增加一名成本显著上升' },
]

onMounted(() => {
  loadWorkspace()
  if (can('workspace.manage')) loadRuntimePolicy()
})

async function loadRuntimePolicy() {
  if (!workspaceId.value) return
  try {
    const { data } = await workspaceApi.runtimePolicy(workspaceId.value)
    runtimeDefaults.value = data.platform_defaults || {}
    runtimeLimits.value = data.platform_limits || data.platform_defaults || {}
    runtimeBudget.value = { ...runtimeDefaults.value, ...Object.fromEntries(Object.entries(data.budget || {}).filter(([, value]) => value !== null)) }
    runtimeUnlimited.value = Object.fromEntries(budgetFields.map(field => [field.key, data.budget?.[field.key] === null]))
    runtimeCollaboration.value = data.collaboration || {}
    runtimeMode.value = runtimeCollaboration.value.max_autonomy || 'EXPLICIT_ONLY'
    runtimeLoaded.value = true
  } catch (e) {
    console.error('Failed to load Runtime Policy:', e)
  }
}

async function saveRuntimePolicy() {
  if (!workspaceId.value) return
  const firstInvalid = budgetFields.find(field => runtimeErrors.value[field.key])
  if (firstInvalid) {
    document.querySelector(`[data-budget-key="${firstInvalid.key}"]`)?.focus()
    window.dispatchEvent(new CustomEvent('toast', { detail: { message: `${firstInvalid.zh}：${runtimeErrors.value[firstInvalid.key]}`, type: 'error' } }))
    return
  }
  runtimeSaving.value = true
  try {
    const budget = Object.fromEntries(budgetFields.map(field => [field.key, runtimeUnlimited.value[field.key] ? null : Number(runtimeBudget.value[field.key])]))
    const { data } = await workspaceApi.saveRuntimePolicy(workspaceId.value, {
      budget,
      collaboration: { ...runtimeCollaboration.value, max_autonomy: runtimeMode.value },
    })
    runtimeBudget.value = { ...runtimeDefaults.value, ...Object.fromEntries(Object.entries(data.budget || {}).filter(([, value]) => value !== null)) }
    runtimeUnlimited.value = Object.fromEntries(budgetFields.map(field => [field.key, data.budget?.[field.key] === null]))
    runtimeCollaboration.value = data.collaboration || {}
    window.dispatchEvent(new CustomEvent('toast', { detail: { message: '运行策略已保存', type: 'success' } }))
  } catch (e) {
    console.error('Failed to save Runtime Policy:', e)
    window.dispatchEvent(new CustomEvent('toast', { detail: { message: e.response?.data?.detail || '运行策略保存失败', type: 'error' } }))
  } finally {
    runtimeSaving.value = false
  }
}

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
.workspace-card-header h3, .runtime-section-title { display: flex; align-items: center; gap: 8px; }
.workspace-card-header h3 small, .runtime-section-title small, .budget-field small, .form-group label small { color: var(--text3); font-size: 12px; font-weight: 400; }
.runtime-card { margin-top: 18px; }
.runtime-section-title { margin: 20px 0 12px; color: var(--text); font-size: 14px; font-weight: 650; }
.budget-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.budget-field { display: grid; gap: 6px; color: var(--text); font-size: 13px; }
.budget-label { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.budget-field .budget-range { margin-left: auto; font-variant-numeric: tabular-nums; }
.budget-control { display: flex; align-items: center; gap: 10px; }
.budget-control > input[type=number] { flex: 1; }
.budget-unlimited { display: inline-flex; align-items: center; gap: 5px; flex: none; cursor: pointer; white-space: nowrap; font-size: 12px; }
.budget-unlimited input { width: 15px; height: 15px; margin: 0; accent-color: var(--primary); }
.budget-field .budget-error { color: var(--danger); font-size: 12px; }
.budget-field .budget-hint { color: var(--text3); font-size: 12px; }
.budget-control > input[type=number] { width: 100%; min-width: 0; padding: 9px 11px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface2); color: var(--text); font-size: 14px; }
.runtime-card .form-group { margin-top: 6px; }
.runtime-card .runtime-collaboration-field :deep(.search-select-trigger) { min-height: 40px; font-size: 14px; }
.runtime-card .btn { display: inline-flex; align-items: center; gap: 7px; }
@media (max-width: 640px) { .budget-grid { grid-template-columns: 1fr; } }
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

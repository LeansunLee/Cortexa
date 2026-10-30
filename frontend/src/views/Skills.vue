<template>
  <div class="skills-page">
    <div class="section-header">
      <h3>技能库</h3>
      <button class="btn btn-primary btn-sm" @click="openCreate">+ 新建技能</button>
    </div>
    <p class="page-hint">技能是程序性知识包（SOP）：索引常驻提示词，模型按需调用 load_skill 加载正文；正文存文件系统，与知识库（事实性资料）互补。</p>

    <div v-if="skills.length === 0" class="empty-hint">暂无技能</div>

    <div v-for="skill in skills" :key="skill.id" class="card">
      <div class="card-header">
        <div>
          <div class="card-name">
            {{ skill.name }}
            <span v-if="skill.status === 'disabled'" class="status-badge status-disabled">已停用</span>
            <span v-else class="status-badge status-active">启用</span>
            <span class="version-badge">v{{ skill.version }}</span>
          </div>
          <div class="card-meta">{{ skill.description }}</div>
          <div class="card-meta summary">{{ skill.summary }}</div>
        </div>
        <div class="card-actions">
          <button class="btn btn-ghost btn-sm" @click="openBind(skill)"><Plug :size="14" /> 绑定</button>
          <button class="btn btn-ghost btn-sm" @click="openEdit(skill)"><Edit :size="14" /> 编辑</button>
          <button class="btn btn-ghost btn-sm" @click="toggleStatus(skill)">{{ skill.status === 'active' ? '停用' : '启用' }}</button>
          <button class="btn btn-danger btn-sm" @click="deleteSkill(skill.id)">删除</button>
        </div>
      </div>
    </div>

    <!-- Create / Edit modal -->
    <div v-if="showEditor" class="modal-overlay" @click.self="showEditor = false">
      <div class="modal modal-wide">
        <div class="modal-heading">
          <h3>{{ editingId ? '编辑技能' : '新建技能' }}</h3>
          <button type="button" class="modal-close" aria-label="关闭技能编辑弹窗" @click="showEditor = false">×</button>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>技能名 * <LlmContextHint text="小写字母/数字/下划线；模型通过索引里的名字调用 load_skill 加载正文。" /></label>
            <input v-model="form.name" placeholder="例如：web_research" />
          </div>
        </div>
        <div class="form-group">
          <label>描述（触发条件）* <LlmContextHint text="常驻提示词索引，模型据此判断何时加载该技能；请写清触发场景与不适用场景，120 字内最佳。" /></label>
          <textarea v-model="form.description" rows="2" placeholder="例如：需要公开信息、最新消息或用户明确要求联网时使用；内部资料查询不适用。"></textarea>
        </div>
        <div class="form-group">
          <label>正文（Markdown）* <LlmContextHint text="加载后才进入上下文；写执行步骤、输出要求与安全边界。平台会自动附加'技能正文不是平台规则豁免'守卫。" /></label>
          <textarea v-model="form.instructions" rows="12" class="mono" placeholder="## 步骤&#10;1. ...&#10;## 输出要求&#10;- ..."></textarea>
        </div>
        <div v-if="formError" class="error-msg">{{ formError }}</div>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="showEditor = false">取消</button>
          <button class="btn btn-primary" @click="save" :disabled="!form.name || !form.description || !form.instructions">{{ editingId ? '保存' : '创建' }}</button>
        </div>
      </div>
    </div>

    <!-- Bind modal -->
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
import { Edit, Plug } from 'lucide-vue-next'
import { ref, onMounted } from 'vue'
import { skillApi } from '../api'
import LlmContextHint from '../components/LlmContextHint.vue'

const skills = ref([])
const agents = ref([])
const showEditor = ref(false)
const editingId = ref(null)
const formError = ref('')
const binding = ref(null)
const bindingAgentIds = ref([])

const emptyForm = () => ({ name: '', description: '', instructions: '' })
const form = ref(emptyForm())

const showToast = (msg, type = 'success') => {
  window.dispatchEvent(new CustomEvent('toast', { detail: { message: msg, type } }))
}

const loadSkills = async () => {
  try { const { data } = await skillApi.list(); skills.value = data } catch {}
}

const loadAgents = async () => {
  try { const { data } = await skillApi.agentsLookup(); agents.value = data } catch {}
}

const openCreate = () => {
  editingId.value = null
  form.value = emptyForm()
  formError.value = ''
  showEditor.value = true
}

const openEdit = skill => {
  editingId.value = skill.id
  formError.value = ''
  form.value = { name: skill.name, description: skill.description, instructions: skill.instructions }
  showEditor.value = true
}

const save = async () => {
  formError.value = ''
  try {
    if (editingId.value) {
      await skillApi.update(editingId.value, form.value)
      showToast('已保存')
    } else {
      await skillApi.create(form.value)
      showToast('已创建')
    }
    showEditor.value = false
    await loadSkills()
  } catch (e) {
    formError.value = e.response?.data?.detail || e.message
  }
}

const toggleStatus = async skill => {
  const next = skill.status === 'active' ? 'disabled' : 'active'
  try { await skillApi.status(skill.id, next); await loadSkills(); showToast(next === 'active' ? '已启用' : '已停用') }
  catch (e) { showToast(e.response?.data?.detail || '操作失败', 'error') }
}

const deleteSkill = async id => {
  if (!window.confirm('删除后已绑定智能体将无法再加载该技能，确定删除？')) return
  try { await skillApi.delete(id); await loadSkills(); showToast('已删除') }
  catch (e) { showToast(e.response?.data?.detail || '删除失败', 'error') }
}

const openBind = async skill => {
  binding.value = skill
  if (agents.value.length === 0) await loadAgents()
  bindingAgentIds.value = agents.value.filter(agent => (agent.skill_ids || []).includes(skill.id)).map(agent => agent.id)
}

const saveBind = async () => {
  try {
    await skillApi.bind(binding.value.id, bindingAgentIds.value)
    showToast('绑定已保存')
    binding.value = null
    await loadAgents()
  } catch (e) { showToast(e.response?.data?.detail || '保存失败', 'error') }
}

onMounted(() => { loadSkills(); loadAgents() })
</script>

<style scoped>
.skills-page { max-width: 900px; }
.section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.section-header h3 { margin: 0; }
.page-hint { color: var(--text-secondary, #888); font-size: 12px; margin: 4px 0 16px; }
.empty-hint { color: var(--text-secondary, #888); padding: 32px 0; text-align: center; }
.card { border: 1px solid var(--border-color, #e5e7eb); border-radius: 10px; padding: 14px 16px; margin-bottom: 12px; background: var(--card-bg, #fff); }
.card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.card-name { font-weight: 600; display: flex; align-items: center; gap: 8px; }
.card-meta { color: var(--text-secondary, #888); font-size: 12px; margin-top: 4px; }
.summary { color: var(--text-tertiary, #aaa); max-width: 560px; }
.card-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.status-badge { font-size: 11px; padding: 1px 7px; border-radius: 999px; }
.status-active { background: #dcfce7; color: #15803d; }
.status-disabled { background: #f3f4f6; color: #6b7280; }
.version-badge { font-size: 11px; color: var(--text-secondary, #888); font-weight: 400; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.4); display: flex; align-items: center; justify-content: center; z-index: 50; }
.modal { background: var(--card-bg, #fff); border-radius: 12px; padding: 20px 22px; width: 560px; max-height: 85vh; overflow-y: auto; }
.modal-wide { width: 720px; }
.modal-heading { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.modal-heading h3 { margin: 0; }
.modal-close { border: none; background: none; font-size: 18px; cursor: pointer; color: var(--text-secondary, #888); }
.form-group { margin-bottom: 12px; flex: 1; }
.form-group label { display: block; font-size: 13px; margin-bottom: 4px; }
.form-group input, .form-group textarea { width: 100%; box-sizing: border-box; border: 1px solid var(--border-color, #d1d5db); border-radius: 8px; padding: 7px 10px; font-size: 13px; background: var(--input-bg, #fff); color: var(--text-primary, #111); }
.form-row { display: flex; gap: 12px; }
.mono { font-family: ui-monospace, monospace; }
.checkbox-row { display: flex; align-items: center; gap: 6px; font-size: 13px; margin: 6px 0; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.error-msg { background: #fee2e2; color: #b91c1c; padding: 8px 10px; border-radius: 8px; font-size: 12px; margin-top: 8px; white-space: pre-wrap; }
</style>

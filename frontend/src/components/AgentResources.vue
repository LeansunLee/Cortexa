<template>
  <div class="agent-resources">
    <p v-if="error" class="error notice" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <p v-if="loading" class="empty">正在加载 Agent 资源…</p>
    <p v-if="management && ['knowledge', 'tools'].includes(tab)" class="save-hint">绑定调整需保存并发布后生效。</p>
    <template v-if="resources">
      <section v-show="tab === 'knowledge'" class="resource-stack">
        <div class="resource-panel">
          <div class="section-heading">
            <div><h3>独立知识库</h3><p class="hint">当前 Agent 专用，文档与内容修改即时生效。</p></div>
            <button v-if="canKnowledge" class="btn btn-primary" :disabled="!!busy" @click="showCreateKnowledge = true"><Plus :size="16" />创建知识库</button>
          </div>
          <p v-if="!privateKnowledge.length" class="empty">暂无独立知识库，创建后即可添加文档。</p>
          <div v-else class="knowledge-list">
            <KnowledgeBaseCard v-for="kb in privateKnowledge" :key="kb.id" :kb="kb" :can-manage="canKnowledge" :can-use="canKnowledge" :can-push="can('knowledge.manage') || can('knowledge.use')" @deleted="removeKnowledge(kb.id)" @pushed="publicKBRevision++" />
          </div>
        </div>
        <div class="resource-panel">
          <div class="section-heading"><div><h3>空间知识库</h3><p class="hint">选择此 Agent 可使用的空间知识库，禁用的知识库不参与检索。</p></div></div>
          <div v-if="sharedKnowledge.length && canReadSharedKnowledge" class="knowledge-list">
            <KnowledgeBaseCard v-for="kb in sharedKnowledge" :key="kb.id" :kb="kb" readonly :refresh-key="publicKBRevision">
              <template #actions><label class="check binding-check"><input v-model="knowledgeIds" type="checkbox" :value="kb.id" :aria-label="'使用知识库 ' + kb.name" :disabled="!!busy || loading || !canEdit" />使用</label></template>
            </KnowledgeBaseCard>
          </div>
          <div v-else-if="sharedKnowledge.length" class="choices">
            <label v-for="kb in sharedKnowledge" :key="kb.id" class="choice"><input v-model="knowledgeIds" type="checkbox" :value="kb.id" :disabled="!!busy || loading || !canEdit" /><span><strong>{{ kb.name }}</strong><small>{{ kb.description || '空间知识库' }}{{ kb.status !== 'active' ? ' · 已禁用' : '' }}</small></span></label>
          </div>
          <p v-else class="empty">暂无空间知识库</p>
          <div v-if="!management && sharedKnowledge.length" class="panel-actions"><button class="btn btn-primary" :disabled="!!busy || !canEdit || !knowledgeChanged" @click="saveKnowledge">{{ busy === 'knowledge' ? '保存中…' : '保存知识库绑定' }}</button></div>
        </div>
      </section>
      <section v-show="tab === 'tools'" class="resource-stack tools-section">
        <slot name="tools-prefix" />
        <form class="resource-panel tools-panel" @submit.prevent="saveTools">
          <div class="section-heading"><div><h3>工具</h3><p class="hint">选择此 Agent 可使用的工具。</p></div></div>
          <fieldset :disabled="!!busy || loading || !canEdit">
            <div v-if="selectableTools.length" class="choices"><label v-for="tool in selectableTools" :key="tool.id" class="choice"><input v-model="toolIds" type="checkbox" :value="tool.id" /><span><strong>{{ tool.name }}</strong><small>{{ tool.description || tool.type }}{{ tool.status !== 'active' ? ' · 已禁用' : '' }}</small></span></label></div>
            <p v-else class="empty">暂无可绑定的工具</p>
            <div v-if="!management && selectableTools.length" class="panel-actions"><button class="btn btn-primary" :disabled="!canEdit || !toolsChanged">{{ busy === 'tools' ? '保存中…' : '保存工具绑定' }}</button></div>
          </fieldset>
        </form>
      </section>
      <section v-show="tab === 'data'" class="resource-panel">
        <div class="section-heading"><div><h3>数据能力</h3><p class="hint">绑定已配置的数据能力，调整即时生效。</p></div></div>
        <form v-if="canData && unboundCapabilities.length" class="inline-form data-binding-form" @submit.prevent="bindData">
          <SearchSelect v-model="capabilityId" :options="unboundCapabilities.map(c => ({ value: c.id, label: c.name + ' · ' + c.data_source_name }))" placeholder="选择数据能力" :disabled="!!busy" />
          <button class="btn btn-primary" :disabled="!!busy || !capabilityId">绑定数据能力</button>
        </form>
        <p v-if="!resources.bindings.length" class="empty">{{ unboundCapabilities.length ? '尚未绑定数据能力' : '暂无可绑定的数据能力，请先在数据源中配置。' }}</p>
        <div v-else class="resource-list">
          <article v-for="binding in resources.bindings" :key="binding.id" class="resource-row data-row">
            <div class="row-copy"><strong>{{ capability(binding).name || '数据能力已不可用' }}</strong><p>{{ capability(binding).data_source_name }}<span v-if="capability(binding).status !== 'active'"> · 已禁用或不可用</span></p><small v-if="capability(binding).description">{{ capability(binding).description }}</small></div>
            <button v-if="canData" class="btn btn-ghost row-action" :disabled="!!busy" @click="unbindData(binding)">解绑</button>
          </article>
        </div>
      </section>
      <section v-if="tab === 'memory'" class="resource-panel">
        <AgentMemory v-if="can('agent.operate')" :agent-id="agentId" />
        <p v-else class="hint">需要 Agent 运维权限才能管理认知；使用 Agent 时会自动召回授权范围内的记忆。</p>
      </section>
    </template>
    <CreateAgentKnowledgeDialog v-if="showCreateKnowledge" :agent-id="agentId" :management="management" @close="showCreateKnowledge = false" @created="knowledgeCreated" />
  </div>
</template>
<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Plus } from 'lucide-vue-next'
import AgentMemory from './AgentMemory.vue'
import { agentOpsApi, agentApi, dataApi } from '../api'
import { can } from '../auth'
import KnowledgeBaseCard from '../components/knowledge/KnowledgeBaseCard.vue'
import CreateAgentKnowledgeDialog from './knowledge/CreateAgentKnowledgeDialog.vue'
import SearchSelect from '../components/SearchSelect.vue'
const props = defineProps({ agentId: {type: String, required: true}, section: {type: String, required: true}, mode: {type: String, default: 'operations'}, agent: Object })
const emit = defineEmits(['bindings-change'])
const agentId = props.agentId
const management = props.mode === 'management'
const tab = computed(() => props.section)
const canKnowledge = computed(() => management ? can('knowledge.manage') : can('agent.operate'))
const canReadSharedKnowledge = computed(() => can('knowledge.manage') || can('knowledge.use'))
const canEdit = computed(() => management ? can('agent.update') : can('agent.operate'))
const canData = computed(() => management ? can('data.manage') : can('agent.operate'))
const publicKBRevision = ref(0)
const resources = ref(null), loading = ref(false), busy = ref(''), error = ref(''), notice = ref('')
watch(tab, () => { notice.value = ''; error.value = '' })
const knowledgeIds = ref([]), toolIds = ref([]), showCreateKnowledge = ref(false), capabilityId = ref('')
const sharedKnowledge = computed(() => (resources.value?.knowledge_bases || []).filter(k => !k.agent_id))
const privateKnowledge = computed(() => (resources.value?.knowledge_bases || []).filter(k => k.agent_id === agentId))
const selectableTools = computed(() => (resources.value?.tools || []).filter(tool => !management || tool.name !== 'web_search'))
// Management bindings belong to the agent draft and are saved by the page header.
watch(knowledgeIds, ids => {
  if (management && resources.value) {
    resources.value.knowledge_base_ids = [...privateKnowledge.value.map(k => k.id), ...ids]
    emit('bindings-change', { knowledge_base_ids: [...resources.value.knowledge_base_ids] })
  }
}, { deep: true })
watch(toolIds, ids => {
  if (management && resources.value) emit('bindings-change', { tool_ids: [...ids] })
}, { deep: true })
watch(() => props.agent?.tool_ids, ids => {
  if (management && ids && different(ids, toolIds.value)) toolIds.value = [...ids]
}, { deep: true })
watch(() => props.agent?.knowledge_base_ids, ids => {
  if (!management || !ids || !resources.value) return
  const sharedIds = sharedKnowledge.value.filter(k => ids.includes(k.id)).map(k => k.id)
  if (different(sharedIds, knowledgeIds.value)) knowledgeIds.value = sharedIds
}, { deep: true })
const different = (a, b) => JSON.stringify([...a].sort()) !== JSON.stringify([...b].sort())
const knowledgeChanged = computed(() => different(knowledgeIds.value, sharedKnowledge.value.filter(k => resources.value.knowledge_base_ids.includes(k.id)).map(k => k.id)))
const toolsChanged = computed(() => different(toolIds.value, resources.value?.tool_ids || []))
const unboundCapabilities = computed(() => (resources.value?.capabilities || []).filter(c => c.status === 'active' && !resources.value.bindings.some(b => b.data_capability_id === c.id)))
const capability = binding => resources.value.capabilities.find(c => c.id === binding.data_capability_id) || {}
const formatDate = value => value ? new Date(value).toLocaleString('zh-CN') : ''
function report(e) { const detail = e.response?.data?.detail; error.value = typeof detail === 'string' ? detail : '操作失败，请稍后重试' }
async function load() {
  loading.value = true; error.value = ''; notice.value = ''
  try {
    resources.value = (await (management ? agentApi.resources(agentId) : agentOpsApi.summary(agentId))).data
    if (management) {
      resources.value.knowledge_base_ids = [...(props.agent.knowledge_base_ids || [])]
      resources.value.tool_ids = [...(props.agent.tool_ids || [])]
    }
    knowledgeIds.value = sharedKnowledge.value.filter(k => resources.value.knowledge_base_ids.includes(k.id)).map(k => k.id)
    toolIds.value = [...resources.value.tool_ids]
  } catch (e) { resources.value = null; report(e) } finally { loading.value = false }
}
async function perform(key, action, message) {
  if (busy.value) return
  busy.value = key; error.value = ''; notice.value = ''
  try { await action(); notice.value = message } catch (e) { report(e) } finally { busy.value = '' }
}
const saveKnowledge = () => perform('knowledge', async () => { if (management) {
    resources.value.knowledge_base_ids = [...privateKnowledge.value.map(k => k.id), ...knowledgeIds.value]
    emit('bindings-change', { knowledge_base_ids: [...resources.value.knowledge_base_ids] })
  } else resources.value.knowledge_base_ids = (await agentOpsApi.knowledge(agentId, knowledgeIds.value)).data.knowledge_base_ids }, '知识库绑定已保存')
const saveTools = () => perform('tools', async () => { if (management) {
    resources.value.tool_ids = [...toolIds.value]
    emit('bindings-change', {tool_ids: [...toolIds.value]})
  } else resources.value.tool_ids = (await agentOpsApi.tools(agentId, toolIds.value)).data.tool_ids }, '工具绑定已保存')
function knowledgeCreated(data) {
  resources.value.knowledge_bases.unshift(data)
  resources.value.knowledge_base_ids.push(data.id)
  if (management) emit('bindings-change', { knowledge_base_ids: [...resources.value.knowledge_base_ids] })
  showCreateKnowledge.value = false
  notice.value = '独立知识库已创建'
}
function removeKnowledge(id) { resources.value.knowledge_bases = resources.value.knowledge_bases.filter(k => k.id !== id); resources.value.knowledge_base_ids = resources.value.knowledge_base_ids.filter(k => k !== id); if (management) emit('bindings-change', {knowledge_base_ids: [...resources.value.knowledge_base_ids]}) }
const bindData = () => perform('data', async () => { const { data } = await (management ? dataApi.createBinding({agent_id: agentId, data_capability_id: capabilityId.value}) : agentOpsApi.bindData(agentId, capabilityId.value)); resources.value.bindings.push(data); capabilityId.value = '' }, '数据能力已绑定')
const unbindData = binding => perform('data', async () => { await (management ? dataApi.deleteBinding(binding.id) : agentOpsApi.unbindData(agentId, binding.id)); resources.value.bindings = resources.value.bindings.filter(b => b.id !== binding.id) }, '数据能力已解绑')
onMounted(load)
</script>

<style scoped>
.agent-resources { width: 100%; min-width: 0; color: var(--text); }
.resource-stack { display: grid; gap: 20px; min-width: 0; }
.resource-panel { min-width: 0; padding: 20px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface); }
.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px 20px; flex-wrap: wrap; }
.section-heading > div { flex: 1 1 240px; min-width: 0; }
h3 { margin: 0; font-size: 16px; font-weight: 600; line-height: 24px; }h4 { margin: 0 0 16px; font-size: 14px; line-height: 22px; }
.hint, .save-hint { color: var(--text2); font-size: 13px; line-height: 22px; overflow-wrap: anywhere; }.hint { margin: 4px 0 0; }.save-hint { margin: 0 0 16px; }
.agent-resources .btn { flex-shrink: 0; white-space: nowrap; justify-content: center; line-height: 20px; }.agent-resources .btn > :deep(svg) { flex-shrink: 0; }
fieldset { border: 0; margin: 0; padding: 0; min-width: 0; }
.knowledge-list { display: grid; gap: 12px; margin-top: 16px; min-width: 0; }
.choices { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(230px, 100%), 1fr)); gap: 12px; margin-top: 16px; }.choice { display: flex; gap: 10px; align-items: flex-start; border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 14px; min-width: 0; }.choice input { margin-top: 4px; flex-shrink: 0; }.choice span { min-width: 0; overflow-wrap: anywhere; }.choice strong, .row-copy strong { display: block; font-size: 14px; line-height: 22px; font-weight: 600; }.choice small { display: block; margin-top: 4px; }
small { display: block; color: var(--text2); font-size: 12px; line-height: 20px; }
.empty { margin: 16px 0 0; padding: 16px; background: var(--surface2); border-radius: var(--radius-sm); color: var(--text3); font-size: 13px; line-height: 22px; overflow-wrap: anywhere; }
.notice { padding: 10px 14px; background: var(--surface2); border-radius: var(--radius-sm); font-size: 13px; line-height: 22px; margin: 0 0 16px; overflow-wrap: anywhere; }.error { color: var(--danger); }
.actions, .inline-form, .resource-tabs, .memory-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.inline-form { margin-top: 16px; }.inline-form > :deep(.search-select) { flex: 1 1 240px; min-width: 0; max-width: 100%; }.panel-actions { margin-top: 16px; }
.resource-list { margin-top: 16px; }.resource-row { display: flex; align-items: flex-start; gap: 16px; padding: 16px 0; border-top: 1px solid var(--border); }.resource-row:last-child { padding-bottom: 0; }.row-copy { flex: 1; min-width: 0; overflow-wrap: anywhere; }.row-copy p { margin: 4px 0; color: var(--text2); font-size: 13px; line-height: 22px; }.row-action, .memory-row > .actions { flex-shrink: 0; }.row-copy .memory-content { white-space: pre-wrap; color: var(--text); margin: 8px 0; }
.memory-toolbar { justify-content: space-between; margin-top: 16px; gap: 12px 20px; }.resource-tabs { gap: 6px; }.resource-tabs .active { color: var(--primary); background: var(--primary-light); border-color: var(--primary); }.check { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; line-height: 20px; white-space: nowrap; }.check input { flex-shrink: 0; margin: 0; }.binding-check { flex-shrink: 0; }
.memory-form { padding: 16px; border: 1px solid var(--border); background: var(--surface2); border-radius: var(--radius-sm); margin-top: 16px; }.memory-form label { display: grid; gap: 8px; font-size: 13px; line-height: 20px; min-width: 0; }.memory-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-bottom: 16px; align-items: start; }.memory-fields input { width: 100%; height: 38px; margin: 0; }.memory-form textarea { width: 100%; resize: vertical; line-height: 22px; }.memory-form .actions { margin-top: 16px; }
@media (max-width: 700px) { .resource-panel { padding: 16px; }.resource-stack { gap: 16px; }.memory-row { flex-wrap: wrap; }.memory-row .row-copy { flex-basis: 100%; }.memory-fields { grid-template-columns: 1fr; }.resource-row { gap: 12px; }.resource-tabs { gap: 4px; }.resource-tabs .btn { padding: 6px 10px; }.choices { grid-template-columns: 1fr; } }
@media (max-width: 700px) {
  .data-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 12px; }
  .data-row .row-copy { display: contents; }
  .data-row strong, .data-row p { grid-column: 1; overflow-wrap: anywhere; }
  .data-row small { grid-column: 1 / -1; overflow-wrap: anywhere; }
  .data-row .row-action { grid-column: 2; grid-row: 1 / 3; align-self: start; }
}
</style>

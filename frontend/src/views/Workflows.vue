<template>
  <div class="workflows-page">
    <PageHeader><button class="btn btn-primary" @click="showCreate = true">创建工作流</button></PageHeader>
    <p v-if="error" class="feedback error" role="alert">{{ error }}</p>
    <p v-if="notice" class="feedback" role="status">{{ notice }}</p>
    <div v-if="!workflows.length" class="empty">暂无工作流。创建后添加 Agent 步骤并发布，即可运行。</div>
    <div v-else class="workflow-list">
      <article v-for="wf in workflows" :key="wf.id" class="workflow-card">
        <div class="card-heading"><div><h2>{{ wf.name }}</h2><p>{{ wf.description || '暂无描述' }}</p></div><span class="status">{{ statusLabel(wf.status) }}</span></div>
        <p class="steps">{{ wf.nodes?.length ? ordered(wf).map(node => node.name).join(' → ') : '尚未添加步骤' }}</p>
        <div class="actions">
          <button class="btn btn-ghost" @click="open(wf)">编辑步骤</button>
          <button v-if="wf.status !== 'active'" class="btn btn-primary" @click="changeStatus(wf, 'active')">发布</button>
          <button v-else class="btn btn-ghost" @click="changeStatus(wf, 'disabled')">禁用</button>
          <button class="btn btn-ghost" :disabled="wf.status !== 'active'" @click="open(wf, true)">运行</button>
          <button class="btn btn-danger" @click="remove(wf)">删除</button>
        </div>
      </article>
    </div>

    <section v-if="selected" class="editor" aria-label="工作流编辑">
      <div class="card-heading"><h2>{{ selected.name }}</h2><button class="btn btn-ghost" @click="selected = null">关闭</button></div>
      <div class="fields"><label>名称<input v-model="editName" maxlength="255" /></label><label>描述<input v-model="editDescription" /></label><button class="btn btn-ghost" @click="saveInfo">保存信息</button></div>
      <h3>执行步骤</h3>
      <p class="hint">目前支持顺序执行已发布的 Agent。每步会收到任务输入和前面步骤的输出。</p>
      <ol class="node-list"><li v-for="(node, index) in ordered(selected)" :key="node.id"><span>{{ node.name }}</span><button class="btn btn-danger" @click="removeNode(node)">移除</button><button v-if="index < selected.nodes.length - 1" class="btn btn-ghost" @click="toggleEdge(node, ordered(selected)[index + 1])">{{ edgeBetween(node, ordered(selected)[index + 1]) ? '断开下一步' : '连接下一步' }}</button></li></ol>
      <div class="fields"><label>步骤名称<input v-model="nodeName" placeholder="例如：研究" /></label><label>执行 Agent<SearchSelect v-model="nodeAgentId" :options="agents.map(a => ({ value: a.id, label: a.name }))" placeholder="选择已发布的 Agent" /></label><button class="btn btn-primary" :disabled="!nodeName.trim() || !nodeAgentId" @click="addStep">添加步骤</button></div>
      <div class="run-panel"><h3>运行工作流</h3><textarea v-model="runInput" rows="3" placeholder="输入要完成的任务" /><button class="btn btn-primary" :disabled="selected.status !== 'active' || running || !runInput.trim()" @click="run">{{ running ? '运行中…' : '运行' }}</button><p v-if="selected.status !== 'active'" class="hint">连接步骤并发布后可以运行。</p><pre v-if="runResult">{{ runResult }}</pre></div>
    </section>

    <div v-if="showCreate" class="modal-overlay" @click.self="showCreate = false"><div class="modal" role="dialog" aria-modal="true" aria-label="创建工作流"><h2>创建工作流</h2><label>名称<input v-model="form.name" maxlength="255" /></label><label>描述<textarea v-model="form.description" rows="2" /></label><div class="actions"><button class="btn btn-ghost" @click="showCreate = false">取消</button><button class="btn btn-primary" :disabled="!form.name.trim()" @click="create">创建</button></div></div></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import api, { workflowApi } from '../api'
const workflows = ref([]), agents = ref([]), selected = ref(null)
const showCreate = ref(false), form = ref({ name: '', description: '' })
const editName = ref(''), editDescription = ref(''), nodeName = ref(''), nodeAgentId = ref('')
const runInput = ref(''), runResult = ref(''), running = ref(false), error = ref(''), notice = ref('')
const detail = e => typeof e.response?.data?.detail === 'string' ? e.response.data.detail : e.message || '操作失败'
const statusLabel = value => ({ draft: '草稿', active: '已发布', disabled: '已禁用' })[value] || value
function ordered(wf) {
  const nodes = wf.nodes || [], edges = wf.edges || []
  const targets = new Set(edges.map(edge => edge.target_node_id))
  const next = new Map(edges.map(edge => [edge.source_node_id, edge.target_node_id]))
  const byId = new Map(nodes.map(node => [node.id, node]))
  const result = [], seen = new Set()
  for (const start of [...nodes.filter(node => !targets.has(node.id)), ...nodes]) {
    let cursor = start.id
    while (byId.has(cursor) && !seen.has(cursor)) { result.push(byId.get(cursor)); seen.add(cursor); cursor = next.get(cursor) }
  }
  return result
}
async function load() {
  try {
    workflows.value = (await workflowApi.list()).data
    agents.value = (await api.get('/auth/agents')).data
    if (selected.value) selected.value = workflows.value.find(w => w.id === selected.value.id) || null
  } catch (e) { error.value = detail(e) }
}
function open(wf, focusRun = false) { selected.value = wf; editName.value = wf.name; editDescription.value = wf.description || ''; runResult.value = ''; if (focusRun) requestAnimationFrame(() => document.querySelector('.run-panel')?.scrollIntoView({ behavior: 'smooth' })) }
async function create() {
  error.value = ''
  try { const { data } = await workflowApi.create({ name: form.value.name.trim(), description: form.value.description }); showCreate.value = false; form.value = { name: '', description: '' }; await load(); open(workflows.value.find(w => w.id === data.id) || data) }
  catch (e) { error.value = detail(e) }
}
async function saveInfo() { try { await workflowApi.update(selected.value.id, { name: editName.value.trim(), description: editDescription.value }); await load(); notice.value = '工作流信息已保存' } catch (e) { error.value = detail(e) } }
async function changeStatus(wf, status) { error.value = ''; try { await workflowApi.update(wf.id, { status }); await load(); notice.value = status === 'active' ? '工作流已发布' : '工作流已禁用' } catch (e) { error.value = detail(e) } }
async function addStep() {
  error.value = ''
  try { const previous = ordered(selected.value).at(-1); const { data } = await workflowApi.addNode(selected.value.id, { name: nodeName.value.trim(), agent_id: nodeAgentId.value }); if (previous) await workflowApi.addEdge(selected.value.id, previous.id, data.id); nodeName.value = ''; nodeAgentId.value = ''; await load() }
  catch (e) { await load(); error.value = detail(e) }
}
async function removeNode(node) { if (!confirm(`移除步骤“${node.name}”？`)) return; try { await workflowApi.deleteNode(selected.value.id, node.id); await load() } catch (e) { error.value = detail(e) } }
function edgeBetween(a, b) { return selected.value.edges.find(edge => edge.source_node_id === a.id && edge.target_node_id === b.id) }
async function toggleEdge(a, b) { try { const edge = edgeBetween(a, b); if (edge) await workflowApi.deleteEdge(selected.value.id, edge.id); else await workflowApi.addEdge(selected.value.id, a.id, b.id); await load() } catch (e) { error.value = detail(e) } }
async function run() { running.value = true; error.value = ''; runResult.value = ''; try { const { data } = await workflowApi.run(selected.value.id, { prompt: runInput.value.trim() }); runResult.value = data.status === 'completed' ? JSON.stringify(data.output_data, null, 2) : data.error_message || '运行失败'; await load() } catch (e) { error.value = detail(e) } finally { running.value = false } }
async function remove(wf) { if (!confirm(`删除工作流“${wf.name}”？`)) return; try { await workflowApi.delete(wf.id); if (selected.value?.id === wf.id) selected.value = null; await load() } catch (e) { error.value = detail(e) } }
onMounted(() => { load(); window.addEventListener('workspace-changed', load) })
onUnmounted(() => window.removeEventListener('workspace-changed', load))
</script>

<style scoped>
.workflow-list { display:grid; gap:14px; }.workflow-card,.editor { padding:20px; background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); }.workflow-card h2,.editor h2 { margin:0; font-size:17px; }.workflow-card p { margin:5px 0; color:var(--text2); }.card-heading { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }.status { color:var(--text2); font-size:12px; }.steps { padding:12px; background:var(--surface2); border-radius:var(--radius-sm); }.actions,.fields { display:flex; flex-wrap:wrap; align-items:end; gap:10px; margin-top:14px; }.fields label,.modal label { display:grid; gap:6px; min-width:180px; flex:1; color:var(--text2); font-size:13px; }.fields input,.modal input,.modal textarea,.run-panel textarea { width:100%; box-sizing:border-box; padding:9px 11px; background:var(--surface2); color:var(--text); border:1px solid var(--border); border-radius:var(--radius-sm); font:inherit; }.editor { margin-top:20px; }.editor h3 { margin:22px 0 6px; font-size:15px; }.hint { color:var(--text2); font-size:13px; }.node-list { padding-left:26px; }.node-list li { margin:8px 0; padding:8px; border:1px solid var(--border); border-radius:var(--radius-sm); }.node-list li span { display:inline-block; min-width:140px; }.node-list button { margin-left:8px; }.run-panel { border-top:1px solid var(--border); margin-top:24px; }.run-panel textarea { display:block; margin:12px 0; }.run-panel pre { white-space:pre-wrap; overflow-wrap:anywhere; padding:12px; background:var(--surface2); border-radius:var(--radius-sm); }.feedback,.empty { padding:12px; background:var(--surface2); border-radius:var(--radius-sm); color:var(--text2); }.error { color:var(--danger); }.btn { display:inline-flex; align-items:center; justify-content:center; padding:8px 14px; border:1px solid var(--border); border-radius:var(--radius-sm); cursor:pointer; background:var(--surface2); color:var(--text); font:inherit; font-size:13px; }.btn:disabled { opacity:.5; cursor:not-allowed; }.btn-primary { color:var(--primary-text); border-color:var(--primary); background:var(--primary); }.btn-ghost { background:transparent; }.btn-danger { color:var(--danger); }.modal-overlay { position:fixed; inset:0; display:grid; place-items:center; z-index:1000; background:var(--overlay); }.modal { width:min(480px,90vw); padding:24px; border-radius:var(--radius); background:var(--surface-dialog); box-shadow:var(--shadow-dialog); }.modal h2 { margin:0 0 16px; }.modal label { margin:10px 0; }
</style>

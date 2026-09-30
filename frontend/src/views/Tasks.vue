<template>
  <div class="tasks-page">
    <PageHeader><button class="btn btn-primary" @click="showCreate = true">创建任务</button></PageHeader>
    <p v-if="error" class="feedback error" role="alert">{{ error }}</p>
    <p v-if="notice" class="feedback" role="status">{{ notice }}</p>
    <div v-if="!tasks.length" class="empty">暂无任务。创建任务并选择已发布的 Agent 后即可运行。</div>
    <article v-for="task in tasks" :key="task.id" class="task-card">
      <div class="heading"><div><h2>{{ task.name }}</h2><p>{{ task.description || '暂无描述' }}</p></div><span>{{ statusLabel(task.status) }}</span></div>
      <p class="agent">Agent：{{ agents.find(agent => agent.id === task.agent_id)?.name || '不可用' }}</p>
      <div class="actions"><button class="btn btn-primary" :disabled="busy === task.id || !task.agent_id" @click="run(task)">{{ busy === task.id ? '运行中…' : '运行' }}</button><button class="btn btn-ghost" @click="edit(task)">编辑</button><button class="btn btn-danger" @click="remove(task)">删除</button></div>
      <pre v-if="task.output_data && Object.keys(task.output_data).length">{{ JSON.stringify(task.output_data, null, 2) }}</pre>
    </article>
    <section v-if="editing" class="editor"><div class="heading"><h2>编辑任务</h2><button class="btn btn-ghost" @click="editing = null">关闭</button></div><label>名称<input v-model="form.name" /></label><label>描述<textarea v-model="form.description" rows="2" /></label><label>任务输入<textarea v-model="form.prompt" rows="3" /></label><button class="btn btn-primary" @click="save">保存</button></section>
    <div v-if="showCreate" class="modal-overlay" @click.self="showCreate = false"><div class="modal" role="dialog" aria-modal="true" aria-label="创建任务"><h2>创建任务</h2><label>名称<input v-model="form.name" maxlength="255" /></label><label>描述<textarea v-model="form.description" rows="2" /></label><label>执行 Agent<SearchSelect v-model="form.agent_id" :options="agents.map(agent => ({ value: agent.id, label: agent.name }))" placeholder="选择已发布的 Agent" /></label><label>任务输入<textarea v-model="form.prompt" rows="3" /></label><div class="actions"><button class="btn btn-ghost" @click="showCreate = false">取消</button><button class="btn btn-primary" :disabled="!form.name.trim() || !form.agent_id" @click="create">创建</button></div></div></div>
  </div>
</template>
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import api, { taskApi } from '../api'
const tasks = ref([]), agents = ref([]), editing = ref(null), showCreate = ref(false), busy = ref(''), error = ref(''), notice = ref('')
const blank = () => ({ name: '', description: '', agent_id: '', prompt: '' })
const form = ref(blank())
const detail = e => typeof e.response?.data?.detail === 'string' ? e.response.data.detail : e.message || '操作失败'
const statusLabel = value => ({ pending: '待运行', running: '运行中', completed: '已完成', failed: '失败' })[value] || value
async function load() { try { tasks.value = (await taskApi.list()).data; agents.value = (await api.get('/auth/agents')).data } catch (e) { error.value = detail(e) } }
async function create() { error.value = ''; try { await taskApi.create({ name: form.value.name.trim(), description: form.value.description, agent_id: form.value.agent_id, input_data: { prompt: form.value.prompt.trim() } }); showCreate.value = false; form.value = blank(); await load(); notice.value = '任务已创建，可以运行' } catch (e) { error.value = detail(e) } }
function edit(task) { editing.value = task; form.value = { name: task.name, description: task.description || '', agent_id: task.agent_id, prompt: task.input_data?.prompt || '' } }
async function save() { try { await taskApi.update(editing.value.id, { name: form.value.name.trim(), description: form.value.description, input_data: { prompt: form.value.prompt.trim() } }); editing.value = null; form.value = blank(); await load(); notice.value = '任务已保存' } catch (e) { error.value = detail(e) } }
async function run(task) { busy.value = task.id; error.value = ''; try { const { data } = await taskApi.run(task.id); await load(); notice.value = data.status === 'completed' ? '任务运行完成' : data.error_message || '任务运行失败' } catch (e) { error.value = detail(e) } finally { busy.value = '' } }
async function remove(task) { if (!confirm(`删除任务“${task.name}”？`)) return; try { await taskApi.delete(task.id); await load() } catch (e) { error.value = detail(e) } }
onMounted(() => { load(); window.addEventListener('workspace-changed', load) })
onUnmounted(() => window.removeEventListener('workspace-changed', load))
</script>
<style scoped>
.task-card,.editor { margin-bottom:14px; padding:20px; border:1px solid var(--border); border-radius:var(--radius); background:var(--surface); }.heading { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }.heading h2 { margin:0; font-size:17px; }.heading p,.agent { color:var(--text2); font-size:13px; }.heading span { color:var(--text2); font-size:12px; }.actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; }.task-card pre { margin:16px 0 0; padding:12px; border-radius:var(--radius-sm); background:var(--surface2); white-space:pre-wrap; overflow-wrap:anywhere; }.editor label,.modal label { display:grid; gap:6px; margin:12px 0; color:var(--text2); font-size:13px; }.editor input,.editor textarea,.modal input,.modal textarea { box-sizing:border-box; width:100%; padding:9px 11px; background:var(--surface2); color:var(--text); border:1px solid var(--border); border-radius:var(--radius-sm); font:inherit; }.modal-overlay { position:fixed; inset:0; z-index:1000; display:grid; place-items:center; background:var(--overlay); }.modal { width:min(500px,90vw); padding:24px; background:var(--surface-dialog); border-radius:var(--radius); box-shadow:var(--shadow-dialog); }.modal h2 { margin:0 0 12px; }.feedback,.empty { padding:12px; margin-bottom:14px; background:var(--surface2); color:var(--text2); border-radius:var(--radius-sm); }.error { color:var(--danger); }.btn { padding:8px 14px; border:1px solid var(--border); border-radius:var(--radius-sm); background:var(--surface2); color:var(--text); cursor:pointer; font:inherit; font-size:13px; }.btn:disabled { opacity:.5; cursor:not-allowed; }.btn-primary { background:var(--primary); border-color:var(--primary); color:var(--primary-text); }.btn-ghost { background:transparent; }.btn-danger { color:var(--danger); }
</style>

<template>
  <div class="work-page" :aria-busy="loading">
    <PageHeader>
      <template #default><button v-if="route.params.id" @click="router.push('/works')">返回工作</button><button v-else class="primary btn btn-primary" @click="editing = {}">＋ 新建工作</button></template>
    </PageHeader>
    <p v-if="error" class="work-error" role="alert">{{ error }} <button @click="load">重新加载</button></p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <p v-if="loading && !hasLoaded" class="hint">正在加载工作…</p>
    <template v-else-if="!route.params.id">
      <div class="work-tabs"><button v-for="t in tabs" :key="t[0]" :class="{selected:filters.view === t[0]}" @click="filters.view = t[0]">{{ t[1] }}</button></div>
      <div class="work-filters">
        <input v-model="filters.search" type="search" placeholder="搜索标题或执行目标" aria-label="搜索工作" />
        <SearchSelect v-model="filters.status" :options="statusFilterOptions" placeholder="所有状态" aria-label="状态筛选" />
        <SearchSelect v-model="filters.assignee_id" :options="assigneeFilterOptions" placeholder="所有负责人" aria-label="负责人筛选" />
        <SearchSelect v-model="filters.priority" :options="priorityFilterOptions" placeholder="所有优先级" aria-label="优先级筛选" />
      </div>
      <div v-if="!rows.length" class="work-empty"><ClipboardList :size="36" /><h3>这里还没有工作</h3><p>创建一项工作，或在 Agent 对话中确认工作建议。</p><button class="btn btn-primary" @click="editing = {}">新建工作</button></div>
      <div class="work-grid">
        <router-link v-for="w in rows" :key="w.id" :to="`/works/${w.id}`" class="work-card">
          <WorkCard :item="w" />
        </router-link>
      </div>
      <div class="pagination" v-if="offset || rows.length === 100"><button :disabled="!offset" @click="offset -= 100; load()">上一页</button><span>第 {{ offset / 100 + 1 }} 页</span><button :disabled="rows.length < 100" @click="offset += 100; load()">下一页</button></div>
      <p class="hint list-hint">“全部”仅显示你有权查看的工作。</p>
    </template>
    <template v-else-if="work">
      <div class="work-detail-grid">
        <main class="detail-main">
          <section class="work-panel overview-panel">
            <header class="overview-header"><div class="overview-badges"><span class="priority" :class="work.priority">{{ work.priority }}</span><span class="status" :class="work.status">{{ states[work.status] }}</span></div>
              <div class="overview-actions"><button v-if="work.permissions.edit" @click="editing = work">编辑工作</button><button v-if="work.permissions.start" class="primary btn btn-primary" :disabled="busy" @click="action('start')">开始工作</button><button v-if="work.permissions.cancel" :disabled="busy" @click="cancelOpen = !cancelOpen">取消工作</button></div>
            </header>
            <div class="requirements-grid"><div><h3>执行目标</h3><p class="preserve">{{ work.goal }}</p></div><div><h3>交付要求</h3><p class="preserve">{{ work.deliverable_requirement || '未填写' }}</p></div></div>
            <details v-if="work.description" class="work-description"><summary>补充说明</summary><p class="preserve">{{ work.description }}</p></details>
            <form v-if="cancelOpen" @submit.prevent="action('cancel')" class="inline-form"><label>取消说明<input v-model="comment" maxlength="2000" /></label><button :disabled="busy">确认取消工作</button></form>
            <p v-if="work.assignee_type === 'agent'" class="hint">Agent 工作已保留，自动执行尚未开放，可在开始前改派给空间成员。</p>
          </section>
          <WorkLogs :work-id="work.id" :events="events" :can-write="work.permissions.log" @changed="load" />
          <section v-if="work.permissions.submit" class="work-panel"><h3>提交交付</h3><form @submit.prevent="submit">
            <label>交付说明<textarea v-model="submission" rows="3" maxlength="100000" placeholder="说明已完成的内容、结果及需要验收的要点" /></label>
            <label>交付文件（最大 50 MB）<input ref="fileInput" type="file" @change="file = $event.target.files[0]" /></label>
            <button class="primary btn btn-primary" :disabled="busy || (!submission.trim() && !file)">{{ busy ? '提交中…' : '提交验收' }}</button>
          </form></section>
          <section v-if="work.permissions.approve" class="work-panel"><h3>验收工作</h3><label>验收意见<textarea v-model="comment" maxlength="2000" rows="3" placeholder="退回时请说明需要补充或修改的内容" /></label><div class="work-actions"><button class="primary btn btn-primary" :disabled="busy" @click="action('approve')">验收通过</button><button :disabled="busy || !comment.trim()" @click="action('reject')">退回修改</button></div></section>
          <section class="work-panel deliveries-panel"><div class="section-heading"><h3>交付物 <span class="hint">{{ deliveries.length }}</span></h3></div><p v-if="!deliveries.length" class="hint">尚未提交交付物</p>
            <article v-for="d in deliveries" :key="d.id" class="delivery-item">
              <div class="delivery-row"><span class="delivery-icon"><FileText v-if="d.type === 'text'" :size="20" /><Paperclip v-else :size="20" /></span><div class="delivery-info"><strong>{{ d.type === 'file' ? d.filename : '交付说明' }}</strong><span>{{ format(d.created_at) }} · {{ d.type === 'text' ? '文本' : '文件' }}<template v-if="d.metadata_json?.size"> · {{ fileSize(d.metadata_json.size) }}</template></span></div><button @click="download(d)" :disabled="busy">下载</button></div>
              <details v-if="d.type === 'text'" class="delivery-preview"><summary>查看交付说明</summary><p class="preserve">{{ d.content }}</p></details>
              <div v-if="work.permissions.knowledge" class="delivery-knowledge"><SearchSelect v-model="kbTargets[d.id]" :options="knowledgeBaseOptions" placeholder="选择目标知识库" aria-label="目标知识库" /><button :disabled="busy || !kbTargets[d.id]" @click="saveKnowledge(d)">沉淀到知识库</button><span class="hint" v-if="Object.keys(d.metadata_json?.knowledge || {}).length">已沉淀至 {{ Object.keys(d.metadata_json.knowledge).length }} 个知识库</span></div>
            </article>
          </section>
          <WorkMemories v-if="work.permissions.memory" :work-id="work.id" :work-title="work.title" :agents="agents" :events="events" @changed="load" />
          <section class="work-panel"><h3>执行与验收记录</h3><ol class="timeline"><li v-for="a in auditEvents" :key="a.id"><div><strong>{{ a.actor_name }}</strong> {{ actions[a.action] || a.action }}<time>{{ format(a.created_at) }}</time></div><p v-if="a.data_json.comment || a.data_json.summary" class="preserve">{{ a.data_json.comment || a.data_json.summary }}</p><p v-if="a.data_json.filename" class="hint">{{ a.data_json.filename }}</p><p v-if="a.action === 'memory'" class="preserve">{{ a.data_json.source_deleted ? '来源已删除' : ('记忆治理：' + (a.data_json.outcome || '已提交') + ' · ' + a.data_json.memory_id) }}</p><details v-if="a.action === 'log_edited'"><summary>查看日志修改</summary><p class="preserve">修改前：{{ a.data_json.before }}</p><p class="preserve">修改后：{{ a.data_json.after }}</p></details><div v-if="a.action === 'edited'" class="hint"><p v-for="(change,key) in a.data_json" :key="key">{{ fieldLabels[key] || key }}：{{ change.before }} → {{ change.after }}</p></div></li></ol></section>
        </main>
        <aside><section class="work-panel"><h3>工作信息</h3><dl><dt>负责人</dt><dd>{{ work.assignee_name }}</dd><dt>创建人</dt><dd>{{ work.creator_name }}</dd><dt>验收人</dt><dd>{{ work.reviewer_name }}</dd><dt>截止时间</dt><dd :class="{overdue:isOverdue(work)}">{{ format(work.due_at) }}</dd><dt>创建时间</dt><dd>{{ format(work.created_at) }}</dd><template v-if="work.completed_at"><dt>完成时间</dt><dd>{{ format(work.completed_at) }}</dd></template></dl></section>
          <section class="work-panel"><h3>来源 · {{ sourceLabels[work.source_type] }}</h3><p>{{ work.source_label }}</p><blockquote v-if="work.source_excerpt">{{ work.source_excerpt }}</blockquote><router-link v-if="work.can_view_source" :to="{path:'/chat',query:{conversation:work.source_id,message:work.source_message_id}}">查看来源消息 →</router-link><p class="hint" v-else-if="work.source_id">原始对话为私有或已删除，已保留来源摘要。</p></section>
        </aside>
      </div>
    </template>
    <WorkEditor v-if="editing" :work="editing.id ? editing : undefined" @close="editing = null" @saved="saved" />
  </div>
</template>
<script setup>
import { computed, ref, reactive, onMounted, watch, onBeforeUnmount, inject } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ClipboardList, FileText, Paperclip } from 'lucide-vue-next'
import PageHeader from '../components/PageHeader.vue'
import WorkCard from '../components/WorkCard.vue'
import WorkLogs from '../components/WorkLogs.vue'
import WorkMemories from '../components/WorkMemories.vue'
import WorkEditor from '../components/WorkEditor.vue'
import { workApi, knowledgeApi, usableAgentApi } from '../api'
const route = useRoute(), router = useRouter()
const setPageTabTitle = inject('setPageTabTitle', () => {})
const hasLoaded = ref(false)
const rows = ref([]), work = ref(null), members = ref([]), deliveries = ref([]), events = ref([]), kbs = ref([]), agents = ref([])
watch(() => work.value?.title, title => { if (title) setPageTabTitle(title) })
const filters = reactive({view:'assigned',search:'',status:'',priority:'',assignee_id:''}), offset = ref(0)
const loading = ref(true), busy = ref(false), error = ref(''), notice = ref(''), editing = ref(null), cancelOpen = ref(false)
const submission = ref(''), file = ref(null), fileInput = ref(null), comment = ref(''), kbTargets = reactive({})
const tabs = [['assigned','我负责的'],['created','我创建的'],['review','待我验收'],['all','全部']]
const states = {draft:'草稿',pending:'待处理',todo:'待开始',in_progress:'进行中',review:'待验收',completed:'已完成',rejected:'退回修改',cancelled:'已取消'}
const sourceLabels = {manual:'人工创建',conversation:'Agent 对话',agent_collaboration:'Agent 协作',workflow:'工作流'}
const priorityFilterOptions = [
  { value: '', label: '所有优先级' },
  { value: 'P0', label: 'P0' },
  { value: 'P1', label: 'P1' },
  { value: 'P2', label: 'P2' },
  { value: 'P3', label: 'P3' },
]
const statusFilterOptions = computed(() => [
  { value: '', label: '所有状态' },
  ...Object.entries(states).map(([value, label]) => ({ value, label })),
])
const assigneeFilterOptions = computed(() => [
  { value: '', label: '所有负责人' },
  ...members.value.map(u => ({ value: u.id, label: u.name })),
])
const knowledgeBaseOptions = computed(() => [
  { value: '', label: '选择目标知识库', disabled: true },
  ...kbs.value.map(k => ({ value: k.id, label: k.name })),
])
const auditEvents = computed(() => events.value.filter(e=>e.action !== 'log'))
const fileSize = size => size < 1024 ? `${size} B` : size < 1048576 ? `${(size/1024).toFixed(1)} KB` : `${(size/1048576).toFixed(1)} MB`
const actions = {log_edited:'编辑工作日志',created:'创建工作',dispatched:'派发工作',started:'开始工作',edited:'修改工作',submitted:'提交交付',approved:'验收通过',rejected:'退回修改',cancelled:'取消工作',knowledge:'沉淀到知识库',memory:'保存 Agent 记忆'}
const fieldLabels = {title:'标题',goal:'目标',description:'说明',assignee_id:'负责人',reviewer_id:'验收人',assignee_type:'负责人类型',due_at:'截止时间',priority:'优先级',deliverable_requirement:'交付要求'}
const format = v => v ? new Date(v).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '未设置'
const isOverdue = w => w.due_at && !['completed','cancelled'].includes(w.status) && new Date(w.due_at) < new Date()
let revision = 0, timer
async function load() {
  const current = ++revision
  loading.value = true; error.value = ''
  try {
    if (route.params.id) {
      const [detail, ds, es] = await Promise.all([workApi.get(route.params.id),workApi.deliverables(route.params.id),workApi.activities(route.params.id)])
      if(current !== revision) return
      work.value = detail.data; deliveries.value = ds.data; events.value = es.data
      for (const d of deliveries.value) kbTargets[d.id] ??= ''
      if (work.value.permissions.knowledge) kbs.value = (await knowledgeApi.list({scope:'workspace'})).data
      if (work.value.permissions.memory) agents.value = (await usableAgentApi.list()).data
    } else {
      const {data} = await workApi.list({...filters,assignee_id:filters.assignee_id || undefined,offset:offset.value})
      if(current === revision) rows.value = data
    }
    if (current === revision) hasLoaded.value = true
  } catch(e) { if(current === revision) {error.value = message(e)} }
  finally {if(current === revision) loading.value = false}
}
function message(e) {return typeof e.response?.data?.detail === 'string' ? e.response.data.detail : '操作失败，请重试'}
async function run(fn, success) {if(busy.value) return;busy.value=true;error.value='';notice.value='';try{await fn();notice.value=success;await load()}catch(e){error.value=message(e)}finally{busy.value=false}}
async function action(name){await run(()=>workApi.action(work.value.id,name,comment.value), '工作状态已更新');comment.value='';cancelOpen.value=false}
async function submit(){if(file.value?.size > 50*1024*1024){error.value='文件不能超过 50 MB';return}const fd=new FormData();fd.append('content',submission.value);if(file.value)fd.append('file',file.value);await run(()=>workApi.submit(work.value.id,fd),'已提交，等待验收');if(!error.value){submission.value='';file.value=null;if(fileInput.value)fileInput.value.value=''}}
async function download(d){try{const {data}=await workApi.download(work.value.id,d.id);const url=URL.createObjectURL(data);const a=document.createElement('a');a.href=url;a.download=d.filename||'交付说明.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch{error.value='下载失败，请重试'}}
async function saveKnowledge(d){await run(()=>workApi.knowledge(work.value.id,d.id,kbTargets[d.id]),'已加入知识库，文件按现有知识处理流程解析')}
async function saved() {
  editing.value = null
  await load()
}
watch(filters,()=>{clearTimeout(timer);revision++;offset.value=0;timer=setTimeout(load,250)})
onMounted(async()=>{await load();try{members.value=(await workApi.members()).data}catch{error.value='无法加载成员筛选，请刷新重试'}})
onBeforeUnmount(()=>{clearTimeout(timer);revision++})
</script>
<style scoped>
.work-page{width:100%}.work-tabs{display:flex;gap:6px;margin-bottom:20px;flex-wrap:wrap}.work-tabs button{border-color:transparent;background:transparent;color:var(--text2)}.work-tabs .selected{background:var(--accent-light,#eef2ff);color:var(--accent);font-weight:600}.work-filters{display:flex;gap:10px;margin-bottom:22px;flex-wrap:wrap}.work-filters input{flex:1;min-width:200px}.work-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,280px),1fr));gap:16px}.work-card{display:block;min-width:0;text-decoration:none;color:var(--text);border-radius:14px}.work-card:focus-visible{outline:2px solid var(--primary);outline-offset:3px}
.card-top{display:flex;justify-content:space-between;align-items:center;gap:10px}
.priority,.status{font-size:12px;padding:4px 8px;border-radius:6px;background:var(--surface2);color:var(--text2)}
.P0,.P1{color:#b54708;background:#fff4e5}.in_progress{background:#eef2ff;color:#4f46e5}.review{background:#fff6dc;color:#a15c07}.completed{background:#ecfdf3;color:#027a48}
.overdue{color:#b42318}.work-empty{text-align:center;padding:70px 20px;border:1px dashed var(--border);border-radius:14px;color:var(--text3)}.work-empty h3{color:var(--text)}.list-hint{margin-top:20px}.work-detail-grid{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:24px}.work-panel{border:1px solid var(--border);background:var(--surface,#fff);border-radius:14px;padding:24px;margin-bottom:20px;overflow-wrap:anywhere}.work-panel h3{font-size:15px;margin:0 0 14px}.work-panel h3:not(:first-child){margin-top:24px}.work-panel p{line-height:1.8;font-size:14px}.preserve{white-space:pre-wrap;overflow-wrap:anywhere}.work-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.work-panel label{display:grid;gap:8px;font-size:13px;margin-bottom:16px}.work-panel textarea{width:100%;box-sizing:border-box;resize:vertical}.work-panel .search-select{max-width:100%}.delivery{border-top:1px solid var(--border);padding:18px 0}.delivery-heading{display:flex;justify-content:space-between;gap:10px;font-size:14px}.work-panel dl{font-size:13px;display:grid;grid-template-columns:70px 1fr;gap:18px 8px}.work-panel dt{color:var(--text3)}.work-panel dd{margin:0}blockquote{border-left:3px solid var(--border);padding-left:12px;margin:12px 0;font-size:13px;line-height:1.8;max-height:250px;overflow:auto;color:var(--text2)}aside a{color:var(--accent);font-size:13px}.timeline{padding-left:20px;margin-bottom:0}.timeline li{padding:0 0 20px 6px;font-size:13px}.timeline time{display:block;color:var(--text3);font-size:12px;margin-top:5px}.notice{padding:12px 16px;background:#ecfdf3;color:#027a48;border-radius:8px}.inline-form{margin-top:16px}.pagination{display:flex;gap:16px;align-items:center;justify-content:center;margin:20px}@media(max-width:1050px){.work-detail-grid{grid-template-columns:1fr}.work-detail-grid aside{grid-row:1;display:grid;grid-template-columns:1fr 1fr;gap:16px}.work-detail-grid aside .work-panel{margin:0}}@media(max-width:640px){.work-grid{grid-template-columns:1fr}.work-detail-grid aside{grid-template-columns:1fr}.work-panel{padding:18px}.work-filters .search-select{flex:1;min-width:140px}}
</style>
<style scoped>
/* Keep work content and native controls on the business-page type scale. */
.work-page { font-size: 14px; line-height: 22px; }
.work-page button,
.work-page input,
.work-page textarea { font-family: inherit; font-size: 13px; line-height: 20px; }
.work-tabs button { padding: 8px 14px; }
.work-filters input { padding: 9px 12px; }
.work-filters .search-select { min-width: 150px; }
.work-filters :deep(.search-select-trigger) { min-height: 40px; padding: 9px 12px; border-radius: 10px; }
.work-empty > svg { display: block; margin: 0 auto 12px; }
.work-empty h3 { margin: 0 0 8px; font-size: 16px; line-height: 24px; font-weight: 600; }
.work-empty p { margin: 0; font-size: 14px; line-height: 22px; }
.work-empty button { margin-top: 20px; }

.work-page .hint { font-size: 13px; line-height: 20px; }
</style>

<style scoped>
.detail-main, .work-detail-grid aside { min-width:0; }
.work-panel { padding:18px 20px; margin-bottom:16px; }
.work-panel h3,.work-panel h3:not(:first-child) { margin:0 0 12px; font-size:14px; line-height:22px; }
.work-panel p { font-size:13px; line-height:22px; }
.work-panel label { gap:6px; margin-bottom:12px; }
.work-panel textarea { padding:10px; border:1px solid var(--border); border-radius:8px; }
.work-panel button { padding:6px 12px; border-radius:8px; }
.work-panel :deep(.search-select-trigger) { padding:6px 10px; border-radius:8px; min-height:34px; }
.overview-header,.overview-badges,.overview-actions { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.overview-header { justify-content:space-between; margin-bottom:14px; }
.requirements-grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:20px; }
.requirements-grid>div+div { border-left:1px solid var(--border); padding-left:20px; }
.requirements-grid h3 { color:var(--text2); font-size:12px; margin-bottom:6px; font-weight:500; }
.requirements-grid p { margin:0; }
.work-description { margin-top:12px; border-top:1px solid var(--border); padding-top:10px; }
summary { cursor:pointer; font-size:12px; color:var(--text2); }
.section-heading { display:flex; align-items:center; justify-content:space-between; }
.delivery-item { padding:12px; border:1px solid var(--border); border-radius:10px; margin-top:10px; }
.delivery-row { display:flex; gap:10px; align-items:center; }
.delivery-icon { display:flex; align-items:center; justify-content:center; width:36px; height:36px; border-radius:8px; background:var(--surface2); color:var(--text2); flex-shrink:0; }
.delivery-info { flex:1; min-width:0; display:grid; gap:3px; }
.delivery-info strong { font-size:13px; overflow-wrap:anywhere; }
.delivery-info>span { font-size:12px; color:var(--text3); }
.delivery-row button { flex-shrink:0; }
.delivery-preview { margin-top:10px; padding:10px 12px; background:var(--surface2); border-radius:8px; }
.delivery-preview p { max-height:260px; overflow:auto; margin:10px 0 0; }
.delivery-knowledge { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:10px; padding-top:10px; border-top:1px solid var(--border); }
.delivery-knowledge .search-select { flex:1; max-width:260px; }
.delivery-knowledge .hint { font-size:12px; }
.work-panel dl { gap:12px 8px; }
.priority.P0 { color:var(--danger); background:var(--danger-bg); font-weight:700; }
.priority.P1 { color:var(--text); background:var(--surface2); }
.status.completed { color:var(--success); background:var(--success-bg); }
.overdue { color:var(--danger); }
.notice { color:var(--success); background:var(--success-bg); }
@media(max-width:1050px) { .work-detail-grid aside { grid-row:auto; } }
@media(max-width:640px) { .work-panel{padding:16px}.requirements-grid{grid-template-columns:1fr;gap:12px}.requirements-grid>div+div{border-left:0;border-top:1px solid var(--border);padding:12px 0 0}.delivery-knowledge .search-select{max-width:none;width:100%} }
</style>

<template>
  <section class="agent-memory" aria-label="Agent 记忆治理">
    <div class="memory-stats"><div v-for="(label,key) in statLabels" :key="key"><strong>{{ stats[key] ?? '—' }}</strong><span>{{ label }}</span></div></div>
    <p class="hint">记忆由当前 Agent 持有，所有有权使用此 Agent 的用户均可使用；原始依据仍单独鉴权。</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="notice" role="status" class="hint">{{ notice }}</p>
    <div class="toolbar">
      <button class="btn btn-ghost" :class="{active:tab==='issues'}" @click="tab='issues'">需要关注</button>
      <button class="btn btn-ghost" :class="{active:tab==='all'}" @click="tab='all'">全部记忆</button>
      <button class="btn btn-primary" :disabled="busy" @click="openCreate">＋ 补充记忆</button>
      <button class="btn btn-ghost" :disabled="busy" @click="consolidate">{{ consolidationCursor ? '继续整理下一批' : '整理记忆' }}</button>
      <button class="btn btn-ghost" :disabled="busy || !config" @click="openConfig">召回规则</button>
    </div>
    <MemoryDialog v-if="showConfig && configDraft" title="召回规则" :busy="busy" :error="error" @close="showConfig=false">
      <form :id="configFormId" @submit.prevent="saveConfig">
        <div class="fields">
          <div v-for="field in configFields" :key="field.key" class="rule-field">
            <label :for="configFormId+'-'+field.key">{{ field.label }}</label>
            <div class="field-help-row">
              <input :id="configFormId+'-'+field.key" v-model.number="configDraft[field.key]" type="number" :min="field.min" :max="field.max" :step="field.step || 1" required />
              <MemoryFieldHelp :label="field.label" :text="field.help" />
            </div>
          </div>
        </div>
        <div class="field-help-row">
          <label class="check"><input v-model="configDraft.semantic_judgment" type="checkbox" />写入时使用模型辅助治理</label>
          <MemoryFieldHelp label="写入时使用模型辅助治理" text="开启后，保存记忆时可调用 Agent 模型辅助判断重复、冲突或事实更新，可能增加等待时间和模型用量；不会在每轮召回时对全部记忆调用模型。" />
        </div>
      </form>
      <template #footer><button type="button" class="btn btn-ghost" :disabled="busy" @click="showConfig=false">取消</button><button :form="configFormId" type="submit" class="btn btn-primary" :disabled="busy">{{ busy?'保存中…':'保存规则' }}</button></template>
    </MemoryDialog>
    <MemoryDialog v-if="form" :title="form.mode==='create'?'补充记忆':form.mode==='supersede'?'事实发生变化':'纠正记忆'" :busy="busy" :error="error" @close="form=null">
      <form :id="memoryFormId" @submit.prevent="submitForm">
      <p v-if="form.mode!=='create'" class="hint">{{ form.mode==='correct'?'原记忆保留，记录纠正依据；正确内容留空可仅撤回错误记忆。':'原记忆保留，请填写变化后的内容及生效时间，系统会记录替代关系。' }}</p>
      <label>{{ form.mode==='create'?'记忆内容':'正确内容' }}<textarea v-model="form.content" rows="3" maxlength="2000" :required="form.mode!=='correct'" /></label>
      <div v-if="form.mode==='create'" class="fields">
        <label>分类<SearchSelect v-model="form.type" :options="categoryOptions" aria-label="分类" /></label>
        <label>业务类型<SearchSelect v-model="form.memory_kind" :options="[{value:'',label:'未知'},...kindOptions]" aria-label="业务类型" /></label>
        <label>关于谁或什么<input v-model="form.subject_name" maxlength="255" /></label>
        <label>重要性<input v-model.number="form.importance" type="number" min="0" max="1" step="0.1" /></label>
      </div>
      <p v-if="form.type==='focus'" class="hint">仅提高 Agent 后续相关场景的关注权重，不会创建监控、提醒或后台任务。</p>
      <label v-if="form.mode!=='create'">原因<textarea v-model="form.reason" required rows="2" maxlength="1000" /></label>
      <details><summary>时间信息（未知请留空）</summary><div class="fields">
        <label v-if="form.mode==='create'">发生时间<input v-model="form.occurred_at" type="datetime-local" /></label>
        <label>有效开始<input v-model="form.valid_from" type="datetime-local" :required="form.mode==='supersede'" /></label>
        <label>有效结束（不含）<input v-model="form.valid_to" type="datetime-local" /></label>
        <label v-if="form.mode==='create'">策略过期<input v-model="form.expires_at" type="datetime-local" /></label>
      </div></details>
      </form>
      <template #footer><button type="button" class="btn btn-ghost" :disabled="busy" @click="form=null">取消</button><button :form="memoryFormId" type="submit" class="btn btn-primary" :disabled="busy">{{ busy?'处理中…':'保存' }}</button></template>
    </MemoryDialog>
    <template v-if="tab==='all'">
      <form class="toolbar filters" @submit.prevent="loadList(false)">
        <input v-model="filters.q" aria-label="搜索记忆" placeholder="搜索记忆内容" maxlength="200" />
        <SearchSelect v-model="filters.type" :options="[{value:'',label:'全部分类'},...categoryOptions]" aria-label="分类筛选" @change="loadList(false)" />
        <SearchSelect v-model="filters.status" :options="[{value:'',label:'默认状态'},...statusOptions]" aria-label="状态筛选" @change="loadList(false)" />
        <button class="btn btn-ghost" :disabled="busy">搜索</button>
      </form>
      <details><summary>高级筛选</summary><div class="fields">
        <label>业务类型<SearchSelect v-model="filters.kind" :options="[{value:'',label:'全部'},...kindOptions]" aria-label="业务类型筛选" /></label>
        <label>关于<input v-model="filters.subject" maxlength="128" /></label>
        <label>最低可信度<SearchSelect v-model="filters.confidence_min" :options="[{value:'',label:'全部'},{value:'0.75',label:'高'},{value:'0.5',label:'中及以上'}]" aria-label="最低可信度" /></label>
        <button class="btn btn-ghost" :disabled="busy" @click="loadList(false)">应用筛选</button>
      </div></details>
      <div v-if="loading" role="status" class="hint">加载中…</div>
      <p v-else-if="!items.length" class="hint">没有符合筛选条件的记忆。</p>
      <article v-for="m in items" :key="m.id" class="memory-row"><button class="memory-open" @click="openDetail(m.id)"><span class="tags">{{ categories[m.type] }} · {{ kinds[m.memory_kind] || '类型未知' }} · {{ statuses[m.status] }} · {{ confidence(m.confidence) }}可信<span v-if="m.has_conflict"> · 存在冲突</span><span v-if="m.source_review_required"> · 依据需复核</span></span><p>{{ m.content_purged ? '[来源已删除，记忆正文已清除]' : m.content }}</p><small>{{ m.subject_name || '对象未知' }} · {{ date(m.updated_at) }}</small></button></article>
      <button v-if="nextCursor" class="btn btn-ghost" :disabled="loading" @click="loadList(true)">加载更多</button>
    </template>
    <template v-else>
      <p v-if="!issues.length" class="hint">暂无需要关注的事项。普通记忆由系统自动治理。</p>
      <article v-for="issue in issues" :key="issue.id" class="panel issue">
        <strong>{{ issueLabels[issue.issue_type] || issue.issue_type }}{{ issue.status==='deferred'?' · 已暂缓':'' }}</strong>
        <div class="conflict-grid"><div v-for="(m,index) in issue.memories" :key="m.id"><small>{{ String.fromCharCode(65+index) }} · {{ confidence(m.confidence) }}可信 · {{ statuses[m.status] }}</small><p>{{ m.content }}</p><button class="btn btn-ghost btn-sm" @click="openDetail(m.id)">查看记忆与依据</button></div></div>
        <button class="btn btn-ghost" @click="beginResolve(issue)">处理事项</button>
      </article>
      <button v-if="issueCursor" class="btn btn-ghost" :disabled="busy" @click="action(()=>loadIssues(true))">更多事项</button>
    </template>
    <section v-if="resolution" class="panel" aria-label="处理异常事项">
      <h4>处理异常事项</h4><form @submit.prevent="resolve">
        <label>处理方式<SearchSelect v-model="resolution.action" :options="resolutionOptions" aria-label="处理方式" /></label>
        <div v-if="resolution.action==='temporal'" class="fields"><fieldset v-for="(m,i) in resolution.issue.memories" :key="m.id"><legend>{{ String.fromCharCode(65+i) }} 有效区间</legend><label>开始<input v-model="resolution.periods[m.id].valid_from" type="datetime-local" required /></label><label>结束<input v-model="resolution.periods[m.id].valid_to" type="datetime-local" required /></label></fieldset></div>
        <label>裁决依据<textarea v-model="resolution.reason" required maxlength="1000" rows="2" /></label><div class="toolbar"><button class="btn btn-primary" :disabled="busy">确认处理</button><button type="button" class="btn btn-ghost" @click="resolution=null">取消</button></div>
      </form>
    </section>
    <MemoryDialog v-if="detail && !form" title="记忆详情" :busy="busy" :error="error" @close="detail=null">
      <p class="cognition">{{ detail.content_purged ? '[来源已删除，记忆正文已清除]' : detail.content }}</p><p class="hint">{{ categories[detail.type] }} · {{ kinds[detail.memory_kind] || '未知类型' }} · {{ statuses[detail.status] }} · {{ confidence(detail.confidence) }}可信 · {{ modes[detail.source_mode] || '来源方式未知' }}</p>
      <p v-if="detail.type==='focus'" class="hint">仅在相关场景提高关注权重；不表示系统正在监控。</p>
      <dl><template v-for="(label,key) in detailFields" :key="key"><template v-if="detail[key]"><dt>{{ label }}</dt><dd>{{ key.includes('_at')||key.startsWith('valid_')?date(detail[key]):detail[key] }}</dd></template></template></dl>
      <p v-if="detail.legacy_uncalibrated" class="hint">历史记忆：缺失的来源、时间和可信度依据未作推测回填。</p>
      <h4>为什么记得？</h4><p v-if="!evidence.length" class="hint">暂无结构化依据。</p>
      <article v-for="e in evidence" :key="e.id" class="evidence"><strong>{{ e.label }}</strong><template v-if="e.accessible"><p>{{ e.summary || '来源已记录' }}</p><RouterLink v-if="sourceLink(e)" :to="sourceLink(e)">查看来源</RouterLink><small>{{ date(e.recorded_at) }}</small></template><p v-else class="hint">{{ e.source_status==='deleted'?'来源已删除':e.source_status==='unverified'?'历史来源未验证':'原始内容无权查看或已不可用' }}</p></article>
      <button v-if="evidenceCursor" class="btn btn-ghost" @click="action(()=>loadEvidence(true))">更多依据</button>
      <h4>记忆变化</h4><article v-for="e in history" :key="e.id" class="history-row"><span>{{ eventLabels[e.event_type] || e.event_type }} · {{ date(e.created_at) }}</span><small v-if="e.reason">{{ e.reason }}</small></article>
      <button v-if="historyCursor" class="btn btn-ghost" @click="action(()=>loadHistory(true))">更多变化</button>
      <p v-for="r in detail.relations" :key="r.from_memory_id+r.to_memory_id+r.type"><button class="btn btn-ghost btn-sm" @click="openDetail(r.from_memory_id===detail.id?r.to_memory_id:r.from_memory_id)">{{ relationLabels[r.type] || r.type }} · 查看关联记忆</button></p>
      <div class="toolbar"><button v-if="detail.permissions.correct" class="btn btn-ghost" @click="openCorrection('correct')">纠正记忆</button><button v-if="detail.permissions.correct" class="btn btn-ghost" @click="openCorrection('supersede')">事实发生变化</button><button v-if="detail.permissions.archive" class="btn btn-ghost" :disabled="busy" @click="stateAction('archive')">归档</button><button v-if="detail.permissions.restore" class="btn btn-ghost" :disabled="busy" @click="stateAction('restore')">恢复</button><button v-if="detail.permissions.purge && !detail.content_purged" class="btn btn-ghost" @click="purgeConfirm=true">永久清除正文</button></div>
      <form v-if="purgeConfirm" @submit.prevent="stateAction('purge')"><p>将永久清除当前记忆正文及受影响的派生内容，无法通过恢复操作找回。</p><button class="btn btn-primary" :disabled="busy">确认永久清除</button><button type="button" class="btn btn-ghost" @click="purgeConfirm=false">取消</button></form>
      <template #footer><button type="button" class="btn btn-ghost" :disabled="busy" @click="detail=null">关闭详情</button></template>
    </MemoryDialog>
  </section>
</template>
<script setup>
import { computed, ref, reactive, onMounted, useId } from 'vue'
import SearchSelect from './SearchSelect.vue'
import MemoryDialog from './MemoryDialog.vue'
import MemoryFieldHelp from './MemoryFieldHelp.vue'
import { RouterLink } from 'vue-router'
import { memoryApi } from '../api'
const memoryFormId=useId(), configFormId=useId()
const props=defineProps({agentId:{type:String,required:true}})
const categories={semantic:'事实与偏好',episodic:'事件与结果',focus:'关注事项'}
const kinds={fact:'事实',preference:'偏好',relationship:'关系',decision:'决策',event:'事件',observation:'观察',outcome:'成果',concern:'关注',other:'其他'}
const statuses={candidate:'候选',active:'有效',superseded:'已替代',expired:'已过期',retracted:'已撤回',archived:'已归档',rejected:'已拒绝'}
const options = values => Object.entries(values).map(([value,label])=>({value,label}))
const categoryOptions=options(categories), kindOptions=options(kinds), statusOptions=options(statuses)
const configFields=[
  {key:'top_k',label:'最多注入条数',min:1,max:10,help:'每次回答最多使用多少条相关记忆，范围 1–10。实际条数还受相关性、有效性和上下文预算限制；调高不代表一定召回更多。'},
  {key:'token_budget',label:'上下文预算',min:200,max:2400,help:'记忆可占用的上下文预算，范围 200–2400。当前按字符保守估算，并非模型精确 Token 数；预算越大，可能提供更多记忆，也增加上下文开销。'},
  {key:'candidate_limit',label:'候选上限',min:20,max:500,help:'单次召回进入排序的候选规模上限，范围 20–500，分配给三类记忆。它不是最终注入条数；调高可能增加检索和排序耗时。'},
  {key:'relevance_threshold',label:'最低相关性',min:0.05,max:0.9,step:0.05,help:'记忆进入排序所需的最低相关性，范围 0.05–0.90。越高越严格，越低越容易召回；重要性再高也不能绕过此门槛。'}
]
const modes={explicit:'明确陈述',system:'系统确定事件',inferred:'推断'}
const statLabels={active:'有效记忆',created:'本周新增',merged:'本周合并',superseded:'本周更新',issues:'需要关注'}
const issueLabels={conflict:'存在冲突',high_risk:'高风险待核验',important_low_confidence:'重要记忆依据不足',possibly_outdated:'可能过时',governance_failure:'治理或来源需复核'}
const relationLabels={supersedes:'替代关系',corrects:'纠正关系',merged_into:'合并关系',conflicts_with:'冲突关系',derived_from:'派生关系'}
const eventLabels={created:'形成记忆',merged:'合并依据',superseded:'被新事实替代',corrected:'人工纠正',reprocessed:'重新治理',issue_resolved:'异常已处理',issue_opened:'发现异常',candidate_created:'形成候选',candidate_rejected:'拒绝候选',archived:'归档',restored:'恢复',expired:'过期',metadata_updated:'属性更新'}
const detailFields={subject_name:'关于',subject_type:'对象类型',subject_id:'对象标识',created_at:'形成时间',occurred_at:'发生时间',valid_from:'有效开始',valid_to:'有效结束（不含）',expires_at:'策略过期时间'}
const stats=ref({}),items=ref([]),issues=ref([]),tab=ref('issues'),busy=ref(false),loading=ref(false),error=ref(''),notice=ref('')
const filters=reactive({q:'',type:'',status:'',kind:'',subject:'',confidence_min:''})
const nextCursor=ref(null),issueCursor=ref(null),detail=ref(null),evidence=ref([]),history=ref([]),evidenceCursor=ref(null),historyCursor=ref(null)
const form=ref(null),resolution=ref(null),showConfig=ref(false),config=ref(null),configDraft=ref(null),consolidationCursor=ref(null),purgeConfirm=ref(false)
const resolutionOptions=computed(()=>[
  ...(resolution.value?.issue.issue_type==='conflict'?[{value:'confirm_a',label:'确认 A，撤回 B'},{value:'confirm_b',label:'确认 B，撤回 A'},{value:'temporal',label:'两者有效但时间不同'}]:[{value:'confirm',label:'人工确认记忆及依据'},...(resolution.value?.issue.issue_type==='governance_failure'?[{value:'retry',label:'重试自动治理'}]:[])]),
  {value:'neither',label:'撤回相关错误记忆'},{value:'defer',label:'暂不处理'}
])
const date=v=>v?new Date(v).toLocaleString('zh-CN'):'未知'
const confidence=v=>v>=.75?'高':v>=.5?'中':'低'
const iso=v=>v?new Date(v).toISOString():null
function fail(e){error.value=typeof e.response?.data?.detail==='string'?e.response.data.detail:'操作失败，请检查输入后重试';if([401,403].includes(e.response?.status)){form.value=null;showConfig.value=false;detail.value=null;items.value=[];issues.value=[]}}
async function action(fn){if(busy.value)return;busy.value=true;error.value='';notice.value='';try{await fn()}catch(e){fail(e)}finally{busy.value=false}}
async function loadList(append=false){loading.value=true;try{const {data}=await memoryApi.list({agent_id:props.agentId,...Object.fromEntries(Object.entries(filters).filter(([,v])=>v!=='')),cursor:append?nextCursor.value:undefined});items.value=append?[...items.value,...data.items]:data.items;nextCursor.value=data.next_cursor}catch(e){fail(e)}finally{loading.value=false}}
async function loadIssues(append=false){const {data}=await memoryApi.issues(props.agentId,{cursor:append?issueCursor.value:undefined});issues.value=append?[...issues.value,...data.items]:data.items;issueCursor.value=data.next_cursor}
async function refresh(){const results=await Promise.allSettled([loadList(),loadIssues(),memoryApi.summary(props.agentId).then(r=>stats.value=r.data)]);results.filter(r=>r.status==='rejected').forEach(r=>fail(r.reason))}
async function loadEvidence(append=false){const {data}=await memoryApi.evidences(detail.value.id,{cursor:append?evidenceCursor.value:undefined});evidence.value=append?[...evidence.value,...data.items]:data.items;evidenceCursor.value=data.next_cursor}
async function loadHistory(append=false){const {data}=await memoryApi.history(detail.value.id,{cursor:append?historyCursor.value:undefined});history.value=append?[...history.value,...data.items]:data.items;historyCursor.value=data.next_cursor}
async function openDetail(id){await action(async()=>{detail.value=(await memoryApi.get(id)).data;purgeConfirm.value=false;evidence.value=[];history.value=[];await Promise.all([loadEvidence(),loadHistory()])})}
function openCreate(){error.value='';form.value={mode:'create',content:'',type:'semantic',memory_kind:'',subject_name:'',importance:.7,idempotency_key:globalThis.crypto?.randomUUID?.() || 'memory-'+Date.now()+'-'+Math.random().toString(36).slice(2)}}
function openCorrection(mode){error.value='';form.value={mode,id:detail.value.id,content:'',type:detail.value.type,reason:'',expected_revision:detail.value.revision,idempotency_key:globalThis.crypto?.randomUUID?.() || 'memory-'+Date.now()+'-'+Math.random().toString(36).slice(2)}}
async function submitForm(){await action(async()=>{const f=form.value;let result;if(f.mode==='create'){result=await memoryApi.create({agent_id:props.agentId,content:f.content,type:f.type,memory_kind:f.memory_kind||null,subject_name:f.subject_name||null,importance:f.importance,idempotency_key:f.idempotency_key,occurred_at:iso(f.occurred_at),valid_from:iso(f.valid_from),valid_to:iso(f.valid_to),expires_at:iso(f.expires_at)})}else{result=await memoryApi.correct(f.id,{new_content:f.content||null,reason:f.reason,expected_revision:f.expected_revision,idempotency_key:f.idempotency_key,valid_from:iso(f.valid_from),valid_to:iso(f.valid_to)},f.mode==='supersede')}notice.value='处理结果：'+(statuses[result.data.status]||result.data.status)+(result.data.outcome==='merged'?'（已合并依据）':'');form.value=null;detail.value=null;await refresh()})}
async function stateAction(mode){await action(async()=>{const id=detail.value.id;await (mode==='archive'?memoryApi.delete(id):mode==='restore'?memoryApi.restore(id):memoryApi.purge(id));detail.value=null;purgeConfirm.value=false;await refresh()})}
function beginResolve(issue){resolution.value={issue,action:issue.issue_type==='conflict'?'confirm_a':issue.issue_type==='governance_failure'?'retry':'confirm',reason:'',periods:Object.fromEntries(issue.memories.map(m=>[m.id,{valid_from:'',valid_to:''}]))}}
async function resolve(){await action(async()=>{const r=resolution.value;const result=await memoryApi.resolve(props.agentId,r.issue.id,{action:r.action,reason:r.reason,revisions:Object.fromEntries(r.issue.memories.map(m=>[m.id,m.revision])),periods:r.action==='temporal'?Object.fromEntries(Object.entries(r.periods).map(([id,p])=>[id,{valid_from:iso(p.valid_from),valid_to:iso(p.valid_to)}])):{}});notice.value=result.data.status==='resolved'?'事项已处理':'仍需关注，未强制确认记忆';resolution.value=null;detail.value=null;await refresh()})}
async function consolidate(){await action(async()=>{const {data}=await memoryApi.consolidate(props.agentId,consolidationCursor.value);consolidationCursor.value=data.next_cursor;notice.value='已整理 '+data.processed+' 条记忆'+(data.next_cursor?'，可继续下一批':'');await refresh()})}
function openConfig(){error.value='';configDraft.value={...config.value};showConfig.value=true}
async function saveConfig(){await action(async()=>{config.value=(await memoryApi.setConfig(props.agentId,configDraft.value)).data;notice.value='召回规则已保存';showConfig.value=false})}
function sourceLink(e){if(e.source_type==='conversation')return {path:'/chat',query:{conversation:e.source_id,message:e.source_sub_id||undefined}};if(e.source_type==='work')return '/works/'+e.source_id;return null}
onMounted(()=>action(async()=>{await refresh();config.value=(await memoryApi.config(props.agentId)).data}))
</script>
<style scoped>
.agent-memory{min-width:0}.memory-stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}.memory-stats>div{display:grid;gap:5px;padding:12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--surface2)}.memory-stats strong{font-size:22px}.memory-stats span,.hint,small,.tags{font-size:12px;color:var(--text3)}.hint{line-height:1.8}.toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:14px 0}.active{color:var(--primary);background:var(--primary-light)}.panel{border:1px solid var(--border);border-radius:var(--radius-sm);padding:16px;margin-top:16px;background:var(--surface)}h4{margin:0 0 12px}.toolbar h4{margin:0;flex:1}.fields,.conflict-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:12px 0}label{display:grid;gap:6px;font-size:13px;margin-bottom:10px}input,textarea{min-width:0;max-width:100%;padding:8px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--surface);color:var(--text)}textarea{width:100%;resize:vertical}summary{cursor:pointer;font-size:13px;padding:10px 0}.check{display:flex;align-items:center}.memory-row{border-bottom:1px solid var(--border)}.memory-open{display:block;text-align:left;width:100%;padding:16px 0;background:none;border:0;color:var(--text);cursor:pointer}.memory-open p,.cognition,.conflict-grid p{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.8;margin:8px 0}.memory-open:hover p{color:var(--primary)}.conflict-grid>div{padding:12px;background:var(--surface2);border-radius:var(--radius-sm)}.evidence,.history-row{padding:10px 0;border-top:1px solid var(--border);font-size:13px}.evidence small,.history-row small{display:block;margin-top:6px}dl{display:grid;grid-template-columns:auto 1fr;gap:8px 20px;font-size:13px}dt{color:var(--text3)}dd{margin:0;overflow-wrap:anywhere}.error{color:var(--danger)}fieldset{min-width:0;border:1px solid var(--border);border-radius:var(--radius-sm)}@media(max-width:700px){.memory-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.fields,.conflict-grid{grid-template-columns:1fr}.panel{padding:12px}.filters input{flex:1;min-width:140px}}

.filters > .search-select { flex: 0 1 170px; min-width: 145px; }
.filters > input { flex: 1 1 200px; }
.field-help-row { display: flex; align-items: center; gap: 6px; min-width: 0; }
.field-help-row > input { flex: 1; width: 100%; min-width: 0; }
.field-help-row .check { margin: 0; }
.rule-field label { margin-bottom: 6px; }
@media(max-width:640px) { .filters > .search-select { flex: 1 1 140px; } }
</style>

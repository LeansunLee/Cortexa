<template>
  <section class="work-panel memory-panel">
    <div class="section-heading"><h3>沉淀 Agent 记忆 <span class="count">{{ saved.length }}</span></h3><button :disabled="busy" @click="add">＋ 添加一条</button></div>
    <p class="hint">验收通过不会自动生成记忆。请人工选择目标 Agent 和最小必要记忆；该 Agent 的所有使用者均可使用。</p>
    <p v-if="error" class="work-error" role="alert">{{ error }}</p><p v-if="notice" class="hint" role="status">{{ notice }}</p>
    <form @submit.prevent="save">
      <fieldset v-for="(entry,index) in entries" :key="entry.key" class="memory-entry" :disabled="busy || entry.saved">
        <legend>记忆 {{ index + 1 }}<span v-if="entry.saved"> · 已保存</span></legend>
        <div class="memory-fields"><label>目标 Agent<SearchSelect v-model="entry.agent_id" :options="agentOptions" placeholder="选择 Agent" aria-label="目标 Agent" /></label><label>记忆类型<SearchSelect v-model="entry.type" :options="typeOptions" placeholder="选择记忆类型" aria-label="记忆类型" /></label><button type="button" class="remove-entry" :aria-label="'移除记忆 ' + (index + 1)" @click="entries.splice(index,1)">移除</button></div>
        <button v-if="workTitle" type="button" class="btn btn-ghost btn-sm" @click="entry.type='episodic';entry.content='工作「'+workTitle+'」已验收通过。'">填写验收结果</button>
        <label class="memory-content">记忆内容<textarea v-model="entry.content" required maxlength="2000" rows="2" placeholder="每条记录一个明确的事实、事件或关注事项" /></label>
      </fieldset>
      <div class="memory-actions"><button class="primary" :disabled="busy || !pending.length">{{ busy ? '保存中…' : `保存 ${pending.length} 条记忆` }}</button></div>
    </form>
    <div v-if="saved.length" class="saved-memories"><h4>已沉淀</h4><article v-for="m in saved" :key="m.id"><div><span class="type-label">{{ types[m.data_json.type] || m.data_json.type }}</span><strong>{{ agentName(m.data_json.agent_id) }}</strong><time>{{ format(m.created_at) }}</time></div><p>{{ m.data_json.source_deleted ? '来源已删除' : (outcomes[m.data_json.outcome] || '已提交治理') }} · 记忆 {{ m.data_json.memory_id }}</p></article></div>
  </section>
</template>
<script setup>
import { computed, ref } from 'vue'
import { workApi } from '../api'
const props = defineProps({workId:String, workTitle:String, agents:Array, events:Array})
const emit = defineEmits(['changed'])
const outcomes={created:'已形成记忆',merged:'已合并依据',existing:'已处理，无需重复',candidate:'待核验',conflict:'存在冲突，请在 Agent 运维中处理',rejected:'未通过长期记忆校验',superseded:'已更新记忆'}
const types = {semantic:'事实',episodic:'事件',focus:'关注'}
let key = 0
const entries = ref([]), busy = ref(false), error = ref(''), notice = ref('')
function add() { entries.value.push({key:++key,agent_id:entries.value.at(-1)?.agent_id || '',type:'semantic',content:'',saved:false}) }
add()
const pending = computed(() => entries.value.filter(e => !e.saved))
const saved = computed(() => props.events.filter(e => e.action === 'memory').slice().reverse())
const agentOptions = computed(() => [
  { value: '', label: '选择 Agent' },
  ...(props.agents || []).map(a => ({ value: a.id, label: a.name })),
])
const typeOptions = computed(() => Object.entries(types).map(([value, label]) => ({ value, label })))
const agentName = id => props.agents.find(a=>a.id===id)?.name || 'Agent（当前不可用）'
const format = v => new Date(v).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})
async function save() {
  if(busy.value || !pending.value.length) return
  if(pending.value.some(e=>!e.agent_id || !e.content.trim())) {error.value='请为每条记忆选择 Agent 并填写内容';return}
  busy.value=true;error.value='';notice.value='';let count=0;const results=[]
  try {
    for(const e of pending.value) {
      const {data}=await workApi.memory(props.workId,{agent_id:e.agent_id,type:e.type,content:e.content.trim()})
      e.saved=true;count++;results.push(outcomes[data.outcome] || '已提交治理')
    }
    notice.value=results.join('；');entries.value=[];add()
  } catch(e) {
    error.value=`已保存 ${count} 条，其余内容已保留，可继续保存。` + (typeof e.response?.data?.detail === 'string' ? e.response.data.detail : '请重试。')
  } finally {busy.value=false;if(count)emit('changed')}
}
</script>
<style scoped>
.section-heading{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:8px}.section-heading h3{margin:0}.count{color:var(--text3);font-size:12px;margin-left:6px}.memory-entry{min-width:0;margin:14px 0 0;padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface2)}.memory-entry legend{padding:0 6px;font-size:12px;color:var(--text2)}.memory-fields{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) auto;gap:10px;align-items:end}.memory-entry label{display:grid;gap:6px;font-size:12px;min-width:0}.memory-entry textarea{width:100%;min-width:0;padding:8px;border:1px solid var(--border);border-radius:7px}.memory-entry :deep(.search-select-trigger){min-height:36px;padding:8px;border-radius:7px}.memory-content{margin-top:10px}.memory-entry textarea{resize:vertical}.memory-actions{display:flex;justify-content:flex-end;margin-top:12px}.saved-memories{border-top:1px solid var(--border);margin-top:18px;padding-top:14px}.saved-memories h4{font-size:13px;margin:0 0 10px}.saved-memories article{padding:10px 0}.saved-memories article+article{border-top:1px solid var(--border)}.saved-memories article>div{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:12px}.saved-memories time{margin-left:auto;color:var(--text3)}.saved-memories p{font-size:13px;white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0 0;line-height:22px}.type-label{background:var(--surface2);border:1px solid var(--border);border-radius:5px;padding:0 6px;color:var(--text2)}@media(max-width:640px){.memory-fields{grid-template-columns:minmax(0,1fr) auto}.memory-fields label:first-child{grid-column:1/-1}}
</style>

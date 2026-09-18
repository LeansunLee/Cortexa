<template>
  <section class="work-panel log-panel">
    <div class="section-heading"><h3>工作日志 <span class="count">{{ logs.length }}</span></h3><button v-if="canWrite && !editor" @click="editor = {content:''}">＋ 写日志</button></div>
    <p v-if="error" class="work-error" role="alert">{{ error }}</p>
    <form v-if="editor" @submit.prevent="save" class="log-editor">
      <label>{{ editor.id ? '编辑日志' : '记录工作进展' }}<textarea v-model="editor.content" required maxlength="2000" rows="4" placeholder="记录进展、遇到的问题或下一步安排" :disabled="busy" /></label>
      <div class="log-actions"><span class="hint">{{ editor.content.length }} / 2000</span><button type="button" :disabled="busy" @click="editor = null">取消</button><button class="primary" :disabled="busy || !editor.content.trim()">{{ busy ? '保存中…' : '保存日志' }}</button></div>
    </form>
    <p v-if="!logs.length && !editor" class="hint">暂无日志，记录每一步进展。</p>
    <article v-for="log in logs" :key="log.id" class="log-entry">
      <header><strong>{{ log.actor_name }}</strong><time>{{ format(log.created_at) }}<span v-if="log.data_json.edited_at"> · 已编辑</span></time><button v-if="log.can_edit" :disabled="busy || !!editor" @click="editor = {id:log.id, content:log.data_json.content, version:log.data_json.version || 1}">编辑</button></header>
      <p class="preserve">{{ log.data_json.content }}</p>
    </article>
  </section>
</template>
<script setup>
import { computed, ref } from 'vue'
import { workApi } from '../api'
const props = defineProps({workId:String, events:Array, canWrite:Boolean})
const emit = defineEmits(['changed'])
const logs = computed(() => props.events.filter(e => e.action === 'log').slice().reverse())
const editor = ref(null), busy = ref(false), error = ref('')
const format = v => new Date(v).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})
async function save() {
  if(busy.value) return
  busy.value = true; error.value = ''
  try {
    const e = editor.value
    if(e.id) await workApi.updateLog(props.workId,e.id,{content:e.content,version:e.version})
    else await workApi.createLog(props.workId,{content:e.content})
    editor.value = null; emit('changed')
  } catch(e) { error.value = typeof e.response?.data?.detail === 'string' ? e.response.data.detail : '日志保存失败，请重试' }
  finally { busy.value = false }
}
</script>
<style scoped>
.section-heading,.log-entry header,.log-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.section-heading{justify-content:space-between;margin-bottom:14px}.section-heading h3{margin:0}.count{font-size:12px;color:var(--text3);margin-left:6px}.log-entry{border-top:1px solid var(--border);padding-top:12px;margin-top:12px}.log-entry header{font-size:12px}.log-entry time{color:var(--text3);font-size:12px}.log-entry header button{margin-left:auto}.log-entry p{margin:8px 0 0;font-size:13px;line-height:22px}.log-editor{padding:12px;background:var(--surface2);border:1px solid var(--border);border-radius:10px}.log-editor label{display:grid;gap:8px;font-size:13px}.log-editor textarea{width:100%;padding:10px;resize:vertical;border:1px solid var(--border);border-radius:8px}.log-actions{justify-content:flex-end;margin-top:10px}.log-actions .hint{margin-right:auto}.preserve{white-space:pre-wrap;overflow-wrap:anywhere}
</style>

<template>
  <Teleport v-if="pageTabActive" to="body">
    <div class="work-overlay" @click.self="$emit('close')">
      <form class="work-editor" @submit.prevent="save" role="dialog" aria-modal="true" aria-labelledby="work-editor-title">
        <header><h2 id="work-editor-title">{{ work ? '编辑工作' : '确认并创建工作' }}</h2><button type="button" @click="$emit('close')" aria-label="关闭">×</button></header>
        <p class="hint">明确目标、负责人和交付结果，确认后派发。</p>
        <label>标题<input v-model="form.title" required maxlength="200" autofocus /></label>
        <label>执行目标<textarea v-model="form.goal" required maxlength="2000" rows="3" /></label>
        <section v-if="form.goal.trim() || form.title.trim()" class="assignee-recommendations" aria-label="推荐负责人" aria-live="polite">
          <strong>推荐负责人</strong>
          <p v-if="recommending" class="hint">正在匹配职责…</p>
          <p v-else-if="recommendationError" class="hint">{{ recommendationError }} <button type="button" @click="loadRecommendations">重试</button></p>
          <template v-else><button v-for="r in recommendations" :key="r.user_id" type="button" :aria-pressed="form.assignee_id===r.user_id" @click="form.assignee_id=r.user_id"><strong>{{ r.display_name }} · {{ r.score }} 分</strong><span>{{ [r.org_unit_name,r.position_title].filter(Boolean).join(' · ') }}</span><small>{{ r.reason }}</small></button><p v-if="!recommendations.length" class="hint">暂无职责匹配，请手动选择负责人。</p></template>
        </section>
        <div class="form-grid">
          <label>负责人<SearchSelect v-model="form.assignee_id" :options="assigneeOptions" placeholder="选择空间成员" aria-label="负责人" /></label>
          <label>验收人<SearchSelect v-model="form.reviewer_id" :options="reviewerOptions" placeholder="选择验收人" aria-label="验收人" /></label>
          <label>截止时间<input type="datetime-local" v-model="due" /></label>
          <label>优先级<SearchSelect v-model="form.priority" :options="priorityOptions" placeholder="选择优先级" aria-label="优先级" /></label>
        </div>
        <label>交付要求<textarea v-model="form.deliverable_requirement" maxlength="2000" rows="3" placeholder="需要提交什么结果，如何判断完成？" /></label>
        <label>补充说明<textarea v-model="form.description" maxlength="4000" rows="2" /></label>
        <p v-if="error" role="alert" class="work-error">{{ error }}</p>
        <footer><button type="button" @click="$emit('close')">取消</button><button class="primary btn btn-primary" :disabled="busy || !members.length">{{ busy ? '保存中…' : work ? '保存修改' : '创建并派发' }}</button></footer>
      </form>
    </div>
  </Teleport>
</template>
<script setup>
import { computed, inject as injectPageTab } from 'vue'
const pageTabActive = injectPageTab('pageTabActive', true)

import { ref, onMounted, watch, onBeforeUnmount } from 'vue'
import { workApi } from '../api'
import { auth } from '../auth'
const props = defineProps({ work: Object, candidate: Object })
const emit = defineEmits(['close', 'saved'])
const base = props.work || props.candidate || {}
const form = ref({ title: base.title || '', goal: base.goal || '', description: base.description || '',
  assignee_type: 'human', assignee_id: base.assignee_type === 'agent' ? '' : base.assignee_id || '',
  reviewer_id: base.reviewer_id || auth.user?.id || '', priority: base.priority || 'P2',
  deliverable_requirement: base.deliverable_requirement || '' })
const initialDue = base.due_at || base.suggested_due_at
const date = initialDue ? new Date(initialDue) : null
const due = ref(date ? new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0,16) : '')
const members = ref([]), error = ref(''), busy = ref(false)
const priorityOptions = [
  { value: 'P0', label: 'P0 · 紧急' },
  { value: 'P1', label: 'P1 · 高' },
  { value: 'P2', label: 'P2 · 普通' },
  { value: 'P3', label: 'P3 · 低' },
]
const assigneeOptions = computed(() => [
  { value: '', label: '选择空间成员', disabled: true },
  ...members.value.map(u => ({ value: u.id, label: u.name })),
])
const reviewerOptions = computed(() => [
  { value: '', label: '选择验收人', disabled: true },
  ...members.value.map(u => ({ value: u.id, label: u.name, disabled: u.id === form.value.assignee_id })),
])
onMounted(async () => { try { members.value = (await workApi.members()).data } catch { error.value = '无法加载空间成员，请关闭后重试' } })
const recommendations=ref([]), recommending=ref(false), recommendationError=ref('')
let recommendationTimer, recommendationVersion=0
async function loadRecommendations(){
 const version=++recommendationVersion
 clearTimeout(recommendationTimer)
 recommending.value=true;recommendationError.value=''
 try {const {data}=await workApi.recommendations(Object.fromEntries(['title','goal','description','deliverable_requirement','priority'].map(k=>[k,form.value[k]])));if(version===recommendationVersion)recommendations.value=data}
 catch {if(version===recommendationVersion){recommendations.value=[];recommendationError.value='推荐暂不可用，可继续手动选择负责人。'}}
 finally {if(version===recommendationVersion)recommending.value=false}
}
watch(()=>[form.value.title,form.value.goal,form.value.description,form.value.deliverable_requirement,form.value.priority],()=>{
 ++recommendationVersion;clearTimeout(recommendationTimer);recommendations.value=[];recommendationError.value=''
 if(!form.value.title.trim()&&!form.value.goal.trim()){recommending.value=false;return}
 recommending.value=true;recommendationTimer=setTimeout(loadRecommendations,500)
},{immediate:true})
onBeforeUnmount(()=>{++recommendationVersion;clearTimeout(recommendationTimer)})
async function save() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    const payload = {...form.value, due_at: due.value ? new Date(due.value).toISOString() : null}
    const { data } = props.work ? await workApi.update(props.work.id, payload) : props.candidate
      ? await workApi.accept(props.candidate.id, payload) : await workApi.create(payload)
    emit('saved', data)
  } catch (e) { error.value = typeof e.response?.data?.detail === 'string' ? e.response.data.detail : '保存失败，请检查必填项和负责人、验收人' }
  finally { busy.value = false }
}
</script>
<style>
.assignee-recommendations{display:grid;gap:8px;padding:12px;border:1px solid var(--border);border-radius:8px}.assignee-recommendations>strong{font-size:13px}.assignee-recommendations>button{display:grid;text-align:left;gap:5px}.assignee-recommendations>button[aria-pressed="true"]{border-color:var(--primary);background:var(--primary-light)}.assignee-recommendations span,.assignee-recommendations small{color:var(--text2);line-height:1.5}

.work-overlay{position:fixed;inset:0;background:#10182866;z-index:1000;display:flex;align-items:center;justify-content:center;padding:20px;backdrop-filter:blur(3px)}
.work-editor{background:var(--surface,#fff);color:var(--text);border:1px solid var(--border);border-radius:18px;padding:26px;width:min(620px,100%);max-height:90dvh;overflow:auto;box-shadow:0 24px 80px #0002;display:grid;gap:14px}
.work-editor header,.work-editor footer{display:flex;justify-content:space-between;align-items:center;gap:12px}.work-editor h2{font-size:20px;margin:0}.work-editor footer{justify-content:flex-end;margin-top:8px}.work-editor label{display:grid;gap:7px;font-size:13px;font-weight:500}.work-editor input,.work-editor textarea{width:100%;box-sizing:border-box}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.work-editor input,.work-editor textarea,.work-page input,.work-page textarea{border:1px solid var(--border,#e5e7eb);border-radius:8px;padding:10px 12px;background:var(--surface,#fff);color:var(--text);font:inherit}.work-editor .search-select-trigger{border-radius:8px;padding:10px 12px}.work-editor button,.work-page button,.work-candidates button{border:1px solid var(--border,#e5e7eb);border-radius:8px;padding:9px 14px;background:var(--surface,#fff);color:var(--text);cursor:pointer;font:inherit}.work-editor button:disabled,.work-page button:disabled,.work-candidates button:disabled{opacity:.5;cursor:wait}.work-editor .primary,.work-page .primary{background:var(--accent,#6366f1);color:white;border-color:transparent}.work-error{color:#b42318;font-size:13px}.hint{color:var(--text3,#777);font-size:13px;margin:0;line-height:1.6}@media(max-width:640px){.form-grid{grid-template-columns:1fr}.work-editor{padding:18px}}
</style>

<template>
  <section class="work-candidates" aria-label="可执行工作" :aria-busy="busy || undefined">
    <p v-if="error" class="hint">{{ error }} <button @click="load">重试</button></p>
    <h4 v-if="busy">
      <span class="heading-mark" aria-hidden="true"></span>正在梳理对话中的可执行工作
      <span class="loading-dots" aria-hidden="true"><i></i><i></i><i></i></span>
    </h4>
    <h4 v-else><span class="heading-mark" aria-hidden="true"></span>{{ items.length ? `发现 ${items.length} 项可执行工作` : '创建可执行工作' }}</h4>
    <div v-if="busy" class="candidate-grid" aria-hidden="true">
      <article v-for="n in 2" :key="n" class="skeleton-card">
        <div class="sk sk-badges"></div>
        <div class="sk-body">
          <div class="sk sk-title"></div>
          <div class="sk sk-line"></div>
          <div class="sk sk-line short"></div>
        </div>
        <div class="sk-actions">
          <div class="sk sk-btn"></div>
          <div class="sk sk-btn primary"></div>
        </div>
      </article>
    </div>
    <div v-else class="candidate-grid">
      <article v-for="c in items" :key="c.id">
        <WorkCard :item="c.work || c">
          <template #actions>
            <template v-if="c.status === 'candidate'">
              <button type="button" class="action-secondary" @click="ignore(c)" :disabled="acting">忽略</button>
              <button type="button" class="action-primary btn btn-primary" @click="editing = c">编辑并创建</button>
            </template>
            <router-link v-else-if="c.status === 'accepted'" :to="`/works/${c.work_id}`">查看工作 →</router-link>
          </template>
        </WorkCard>
      </article>
      <article class="manual-card">
        <span class="manual-icon" aria-hidden="true"><Plus :size="22" :stroke-width="1.8" /></span>
        <div class="manual-copy">
          <h5>自建任务</h5>
          <p>有其他需要执行的工作？自行填写并创建。</p>
        </div>
        <button type="button" class="manual-create btn btn-primary" @click="creatingManual = true">新建工作</button>
      </article>
    </div>
    <p v-if="items.length" class="hint">建议由你确认后才会派发。</p>
    <WorkEditor v-if="editing || creatingManual" :candidate="editing || undefined" :conversation-id="conversationId" :project-id="message.metadata_json?.project_ids?.length === 1 ? message.metadata_json.project_ids[0] : undefined" @close="closeEditor" @saved="saved" />
  </section>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { Plus } from 'lucide-vue-next'
import { workApi } from '../api'
import WorkCard from './WorkCard.vue'
import WorkEditor from './WorkEditor.vue'
const props = defineProps({ conversationId: String, message: Object, autoExtract: Boolean })
const items = ref([]), busy = ref(false), error = ref(''), editing = ref(null), creatingManual = ref(false), acting = ref(false)
async function load() {
  if (!props.message.id) return
  busy.value = true; error.value = ''
  try {
    let { data } = await workApi.candidates(props.conversationId)
    if (props.autoExtract && !props.message.metadata_json?.work_extracted && !data.some(c => c.message_id === props.message.id))
      data = (await workApi.extract(props.conversationId, props.message.id)).data
    items.value = data.filter(c => c.message_id === props.message.id && c.status !== 'rejected')
    await Promise.all(items.value.filter(c => c.status === 'accepted' && c.work_id).map(async c => {
      try { c.work = (await workApi.get(c.work_id)).data } catch { /* Keep the saved suggestion visible if the work is unavailable. */ }
    }))
  } catch { error.value = '工作建议暂不可用' } finally { busy.value = false }
}
async function ignore(c) { acting.value = true; try { await workApi.ignore(c.id); items.value = items.value.filter(x => x.id !== c.id) } catch { error.value = '忽略失败，请重试' } finally { acting.value = false } }
function closeEditor() { editing.value = null; creatingManual.value = false }
function saved(w) {
  if (editing.value) {
    const c = items.value.find(x => x.id === editing.value.id)
    if (c) { c.status = 'accepted'; c.work_id = w.id; c.work = w }
  }
  closeEditor()
}
onMounted(load)
</script>
<style scoped>
.work-candidates { margin-top:16px; padding:0; border-radius:12px; }
h4 {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 0 0 10px;
  font-size: 13px;
  line-height: 20px;
  font-weight: 600;
}
.heading-mark {
  width: 4px;
  height: 14px;
  border-radius: 999px;
  background: var(--primary);
}
.loading-dots { display: inline-flex; align-items: center; gap: 3px; margin-left: 2px; }
.loading-dots i {
  width: 5px; height: 5px; border-radius: 50%; background: var(--primary);
  animation: dots-bounce 1.4s infinite ease-in-out;
}
.loading-dots i:nth-child(1) { animation-delay: -0.32s; }
.loading-dots i:nth-child(2) { animation-delay: -0.16s; }
@keyframes dots-bounce { 0%, 80%, 100% { transform: scale(0.6); opacity: 0.35; } 40% { transform: scale(1); opacity: 1; } }
.skeleton-card {
  box-sizing: border-box; min-height: 240px; padding: 18px;
  display: flex; flex-direction: column; gap: 12px;
  border: 1px solid var(--border); border-radius: 14px; background: var(--surface);
}
.sk {
  border-radius: 6px;
  background: linear-gradient(90deg, var(--surface2) 25%, var(--border) 45%, var(--surface2) 65%);
  background-size: 200% 100%;
  animation: sk-shimmer 1.4s linear infinite;
}
.sk-badges { width: 104px; height: 22px; }
.sk-body { display: flex; flex-direction: column; gap: 8px; min-height: 96px; }
.sk-title { width: 68%; height: 15px; }
.sk-line { width: 94%; height: 12px; }
.sk-line.short { width: 56%; }
.sk-actions { margin-top: auto; display: flex; justify-content: flex-end; gap: 8px; }
.sk-btn { width: 64px; height: 28px; }
.sk-btn.primary { width: 96px; }
@keyframes sk-shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .loading-dots i, .sk { animation: none; } }
.candidate-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(min(100%,280px),1fr)); gap:16px; }
article { min-width:0; }
.manual-card { box-sizing:border-box; min-height:240px; padding:18px; display:flex; flex-direction:column; align-items:flex-start; gap:12px; border:1px dashed var(--border); border-radius:14px; background:var(--surface); color:var(--text); }
.manual-icon { width:34px; height:34px; display:grid; place-items:center; border-radius:10px; background:var(--primary-light); color:var(--primary); }
.manual-copy h5 { margin:0 0 6px; font-size:15px; line-height:22px; font-weight:600; }
.manual-copy p { margin:0; font-size:13px; line-height:21px; color:var(--text2); }
.manual-card .manual-create { align-self:flex-end; margin-top:auto; min-height:28px; padding:3px 10px; }
.manual-card:hover { border-color:var(--primary); }
button { height:28px; padding:3px 10px; border-radius:6px; font-family:inherit; font-size:12px; line-height:20px; font-weight:500; cursor:pointer; }
button:disabled { opacity:.5; cursor:not-allowed; }
.action-secondary { color:var(--text2); background:transparent; border:1px solid var(--border); }
.action-secondary:hover:not(:disabled) { background:var(--surface2); }
.action-primary { min-width:82px; }
a { font-size:12px; line-height:20px; font-weight:500; color:var(--primary); text-decoration:none; }
a:hover { text-decoration:underline; }
.hint { margin:10px 0 0; font-size:11px; line-height:17px; color:var(--text3); }
</style>

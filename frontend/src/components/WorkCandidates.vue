<template>
  <section class="work-candidates" aria-label="可执行工作">
    <p v-if="busy" class="hint">正在识别可执行工作…</p>
    <p v-else-if="error" class="hint">{{ error }} <button @click="load">重试</button></p>
    <h4><span class="heading-mark" aria-hidden="true"></span>{{ items.length ? `发现 ${items.length} 项可执行工作` : '创建可执行工作' }}</h4>
    <div class="candidate-grid">
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
    <WorkEditor v-if="editing || creatingManual" :candidate="editing || undefined" @close="closeEditor" @saved="saved" />
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

<template>
  <section class="work-candidates" v-if="items.length || busy || error">
    <p v-if="busy" class="hint">正在识别可执行工作…</p>
    <p v-else-if="error" class="hint">{{ error }} <button @click="load">重试</button></p>
    <template v-if="items.length">
      <h4><span class="heading-mark" aria-hidden="true"></span>发现 {{ items.length }} 项可执行工作</h4>
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
      </div>
      <p class="hint">建议由你确认后才会派发。</p>
    </template>
    <WorkEditor v-if="editing" :candidate="editing" @close="editing = null" @saved="saved" />
  </section>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { workApi } from '../api'
import WorkCard from './WorkCard.vue'
import WorkEditor from './WorkEditor.vue'
const props = defineProps({ conversationId: String, message: Object, autoExtract: Boolean })
const items = ref([]), busy = ref(false), error = ref(''), editing = ref(null), acting = ref(false)
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
function saved(w) { const c = items.value.find(x => x.id === editing.value.id); if(c) {c.status = 'accepted'; c.work_id = w.id; c.work = w} editing.value = null }
onMounted(load)
</script>
<style scoped>
.work-candidates {
  margin-top: 16px;
  padding: 0;

  border-radius: 12px;

}
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
button { height:28px; padding:3px 10px; border-radius:6px; font-family:inherit; font-size:12px; line-height:20px; font-weight:500; cursor:pointer; }
button:disabled { opacity:.5; cursor:not-allowed; }
.action-secondary { color:var(--text2); background:transparent; border:1px solid var(--border); }
.action-secondary:hover:not(:disabled) { background:var(--surface2); }
.action-primary { min-width:82px; }
a { font-size:12px; line-height:20px; font-weight:500; color:var(--primary); text-decoration:none; }
a:hover { text-decoration:underline; }
.hint { margin:10px 0 0; font-size:11px; line-height:17px; color:var(--text3); }
</style>

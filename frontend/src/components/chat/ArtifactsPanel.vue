<template>
  <aside class="artifacts-panel" aria-label="工作区">
    <header class="artifacts-head">
      <h3><PanelRightOpen :size="16" /> 工作区</h3>
      <button type="button" class="artifacts-close" aria-label="收起工作区面板" @click="$emit('close')"><PanelRightClose :size="16" /></button>
    </header>
    <p v-if="error" class="artifacts-error">{{ error }} <button type="button" @click="refresh">重试</button></p>
    <div class="artifacts-list">
      <div class="panel-section">
        <h4 class="panel-section-title"><FileText :size="13" /> 产出物 <span v-if="items.length" class="panel-count">{{ items.length }}</span></h4>
        <p v-if="!items.length && !error" class="panel-empty">本对话还没有产出物。要求 Agent 生成文档（方案、报告、清单等）时会出现在这里。</p>
        <article v-for="a in items" :key="a.id" class="panel-card" tabindex="0" role="button"
          :title="`查看 ${a.title}`" @click="$emit('open', a)" @keydown.enter.prevent="$emit('open', a)">
          <span class="panel-card-icon"><FileText :size="15" /></span>
          <span class="panel-card-body">
            <span class="panel-card-title">{{ a.title }}</span>
            <span class="panel-card-meta">{{ a.filename }} · {{ formatSize(a.size) }}</span>
          </span>
          <a class="panel-card-action" :href="artifactApi.downloadUrl(conversationId, a.id)" download
            :aria-label="`下载 ${a.title}`" @click.stop><Download :size="14" /></a>
        </article>
      </div>
      <div class="panel-section">
        <h4 class="panel-section-title"><ClipboardList :size="13" /> 已创建工作 <span v-if="works.length" class="panel-count">{{ works.length }}</span></h4>
        <p v-if="!works.length && !error" class="panel-empty">本对话还没有创建工作。确认「可执行工作」建议后会显示在这里。</p>
        <article v-for="w in works" :key="w.id" class="panel-card work-card" tabindex="0" role="button"
          :title="`打开工作 ${w.title}`" @click="openWork(w)" @keydown.enter.prevent="openWork(w)">
          <span class="panel-card-icon work-icon"><ClipboardList :size="15" /></span>
          <span class="panel-card-body">
            <span class="panel-card-badges">
              <span class="work-priority" :class="w.priority || 'P2'">{{ w.priority || 'P2' }}</span>
              <span class="work-status" :class="w.status"><i aria-hidden="true"></i>{{ states[w.status] || w.status }}</span>
            </span>
            <span class="panel-card-title">{{ w.title }}</span>
          </span>
          <a class="panel-card-action" :href="`/works/${w.id}`" :aria-label="`打开工作 ${w.title}`" @click.prevent.stop="openWork(w)"><ArrowUpRight :size="14" /></a>
        </article>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowUpRight, ClipboardList, Download, FileText, PanelRightClose, PanelRightOpen } from 'lucide-vue-next'
import { artifactApi, workApi } from '../../api'

const props = defineProps({ conversationId: String })
const emit = defineEmits(['close', 'open'])
const router = useRouter()
const items = ref([])
const works = ref([])
const error = ref('')
const states = { draft: '草稿', pending: '待处理', todo: '待开始', in_progress: '进行中', review: '待验收', completed: '已完成', rejected: '退回修改', cancelled: '已取消' }

async function refresh() {
  if (!props.conversationId) return
  error.value = ''
  try { items.value = (await artifactApi.list(props.conversationId)).data } catch { error.value = '工作区列表加载失败' }
  try { works.value = (await workApi.list({ view: 'all', source_id: props.conversationId, limit: 50 })).data } catch { /* keep previous */ }
}
function openWork(w) {
  router.push(`/works/${w.id}`)
}
function formatSize(n) {
  if (n == null) return ''
  return n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KB`
}
watch(() => props.conversationId, refresh)
onMounted(refresh)
defineExpose({ load: refresh })
</script>

<style scoped>
.artifacts-panel { display: flex; flex-direction: column; width: 300px; flex-shrink: 0; min-height: 0; border-left: 1px solid var(--border); background: var(--surface); }
.artifacts-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
.artifacts-head h3 { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 13px; line-height: 20px; font-weight: 600; }
.artifacts-close { display: grid; place-items: center; width: 28px; height: 28px; border: 0; border-radius: var(--radius-xs); background: transparent; color: var(--text3); cursor: pointer; }
.artifacts-close:hover { background: var(--surface2); color: var(--text); }
.artifacts-error, .panel-empty { margin: 0; padding: 6px 4px 10px; font-size: 12px; line-height: 1.6; color: var(--text3); }
.artifacts-error { color: var(--danger); }
.artifacts-list { flex: 1; min-height: 0; overflow-y: auto; padding: 10px 8px; display: flex; flex-direction: column; gap: 14px; }
.panel-section { display: flex; flex-direction: column; }
.panel-section-title { display: flex; align-items: center; gap: 5px; margin: 0 0 8px; font-size: 12px; line-height: 18px; font-weight: 600; color: var(--text2); }
.panel-count { min-width: 18px; height: 18px; display: grid; place-items: center; padding: 0 5px; border-radius: 999px; background: var(--primary-light); color: var(--primary); font-size: 11px; font-weight: 600; }
.panel-card { display: flex; align-items: center; gap: 9px; padding: 9px 10px; margin-bottom: 6px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface); cursor: pointer; }
.panel-card:hover, .panel-card:focus-visible { border-color: var(--primary); outline: none; }
.panel-card-icon { width: 28px; height: 28px; display: grid; place-items: center; border-radius: 8px; background: var(--primary-light); color: var(--primary); flex-shrink: 0; }
.panel-card-icon.work-icon { background: var(--surface2); color: var(--text2); }
.panel-card-body { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 3px; }
.panel-card-title { font-size: 13px; line-height: 18px; font-weight: 500; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.panel-card-meta { font-size: 11px; line-height: 16px; color: var(--text3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.panel-card-action { display: grid; place-items: center; width: 26px; height: 26px; border-radius: var(--radius-xs); color: var(--text3); flex-shrink: 0; }
.panel-card-action:hover { background: var(--surface2); color: var(--text); }
.panel-card-badges { display: flex; align-items: center; gap: 5px; }
.work-priority, .work-status { display: inline-flex; align-items: center; gap: 4px; padding: 0 6px; border-radius: 5px; font-size: 10px; line-height: 17px; font-weight: 500; background: var(--surface2); color: var(--text2); }
.work-priority.P0 { color: var(--danger); background: var(--danger-bg); font-weight: 700; }
.work-priority.P1 { color: var(--text); background: var(--surface2); font-weight: 600; }
.work-status i { width: 4px; height: 4px; border-radius: 50%; background: currentColor; }
.work-status.completed, .work-status.accepted { color: var(--success); background: var(--success-bg); }
.work-status.in_progress, .work-status.review, .work-status.rejected { color: var(--primary); background: var(--primary-light); }
@media (max-width: 900px) { .artifacts-panel { position: absolute; right: 0; top: 0; bottom: 0; z-index: 30; box-shadow: var(--shadow-md); } }
</style>

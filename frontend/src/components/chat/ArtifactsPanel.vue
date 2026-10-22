<template>
  <aside class="artifacts-panel" aria-label="对话产出物">
    <header class="artifacts-head">
      <h3><FileText :size="16" /> 产出物 <span v-if="items.length" class="artifacts-count">{{ items.length }}</span></h3>
      <button type="button" class="artifacts-close" aria-label="收起产出物面板" @click="$emit('close')"><PanelRightClose :size="16" /></button>
    </header>
    <p v-if="error" class="artifacts-error">{{ error }} <button type="button" @click="load">重试</button></p>
    <div class="artifacts-list">
      <p v-if="!items.length && !error" class="artifacts-empty">对话中还没有产出物。要求 Agent 生成文档（方案、报告、清单等）时会自动附在回复后。</p>
      <article v-for="a in items" :key="a.id" class="artifact-item" tabindex="0" role="button"
        :title="a.title" @click="$emit('open', a)" @keydown.enter.prevent="$emit('open', a)">
        <span class="artifact-item-icon"><FileText :size="15" /></span>
        <span class="artifact-item-body">
          <span class="artifact-item-title">{{ a.title }}</span>
          <span class="artifact-item-meta">{{ a.filename }} · {{ formatSize(a.size) }}</span>
        </span>
        <a class="artifact-item-download" :href="artifactApi.downloadUrl(conversationId, a.id)" download
          :aria-label="`下载 ${a.title}`" @click.stop><Download :size="14" /></a>
      </article>
    </div>
  </aside>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { Download, FileText, PanelRightClose } from 'lucide-vue-next'
import { artifactApi } from '../../api'

const props = defineProps({ conversationId: String })
defineEmits(['close', 'open'])
const items = ref([])
const error = ref('')

async function load() {
  if (!props.conversationId) return
  error.value = ''
  try { items.value = (await artifactApi.list(props.conversationId)).data } catch { error.value = '产出物列表加载失败' }
}
function formatSize(n) {
  if (n == null) return ''
  return n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KB`
}
watch(() => props.conversationId, load)
onMounted(load)
defineExpose({ load })
</script>

<style scoped>
.artifacts-panel { display: flex; flex-direction: column; width: 300px; flex-shrink: 0; min-height: 0; border-left: 1px solid var(--border); background: var(--surface); }
.artifacts-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
.artifacts-head h3 { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 13px; line-height: 20px; font-weight: 600; }
.artifacts-count { min-width: 18px; height: 18px; display: grid; place-items: center; padding: 0 5px; border-radius: 999px; background: var(--primary-light); color: var(--primary); font-size: 11px; font-weight: 600; }
.artifacts-close { display: grid; place-items: center; width: 28px; height: 28px; border: 0; border-radius: var(--radius-xs); background: transparent; color: var(--text3); cursor: pointer; }
.artifacts-close:hover { background: var(--surface2); color: var(--text); }
.artifacts-error, .artifacts-empty { margin: 0; padding: 14px; font-size: 12px; line-height: 1.6; color: var(--text3); }
.artifacts-error { color: var(--danger); }
.artifacts-list { flex: 1; min-height: 0; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 6px; }
.artifact-item { display: flex; align-items: center; gap: 9px; padding: 9px 10px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface); cursor: pointer; }
.artifact-item:hover, .artifact-item:focus-visible { border-color: var(--primary); outline: none; }
.artifact-item-icon { width: 28px; height: 28px; display: grid; place-items: center; border-radius: 8px; background: var(--primary-light); color: var(--primary); flex-shrink: 0; }
.artifact-item-body { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 1px; }
.artifact-item-title { font-size: 13px; line-height: 18px; font-weight: 500; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.artifact-item-meta { font-size: 11px; line-height: 16px; color: var(--text3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.artifact-item-download { display: grid; place-items: center; width: 26px; height: 26px; border-radius: var(--radius-xs); color: var(--text3); flex-shrink: 0; }
.artifact-item-download:hover { background: var(--surface2); color: var(--text); }
@media (max-width: 900px) { .artifacts-panel { position: absolute; right: 0; top: 0; bottom: 0; z-index: 30; box-shadow: var(--shadow-md); } }
</style>

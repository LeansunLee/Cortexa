<template>
  <Teleport to="body">
    <div v-if="visible" class="artifact-overlay" @click.self="close" @keydown.esc="close">
      <section class="artifact-dialog" role="dialog" aria-modal="true" aria-labelledby="artifact-dialog-title">
        <header class="artifact-header">
          <div class="artifact-icon"><FileText :size="20" /></div>
          <div class="artifact-heading">
            <h3 id="artifact-dialog-title">{{ artifact?.title || '产出物' }}</h3>
            <p class="artifact-meta">{{ detail?.filename || artifact?.filename }} · {{ formatSize(detail?.size ?? artifact?.size) }}<span v-if="dirty" class="artifact-dirty"> · 未保存修改</span></p>
          </div>
          <div class="artifact-header-actions">
            <a v-if="conversationId && artifact?.id" class="artifact-link" :href="artifactApi.downloadUrl(conversationId, artifact.id)" download>
              <Download :size="15" /> 下载
            </a>
            <button type="button" class="artifact-close" aria-label="关闭" @click="close"><X :size="18" /></button>
          </div>
        </header>
        <div class="artifact-body" :aria-busy="loading">
          <p v-if="error" class="artifact-error" role="alert">{{ error }} <button type="button" @click="load">重试</button></p>
          <label class="artifact-title-field">标题 <input v-model="title" :disabled="loading || saving" maxlength="200" /></label>
          <label v-if="!loading && detail" class="artifact-content-field">内容
            <textarea v-if="!isMarkdown" v-model="content" class="artifact-plain" spellcheck="false"></textarea>
            <MarkdownEditor v-else v-model="content" aria-label="产出物内容" />
          </label>
          <p v-else class="artifact-loading">加载中…</p>
        </div>
        <footer class="artifact-footer">
          <div class="artifact-import">
            <select v-model="targetWork" :disabled="saving || !works.length" aria-label="选择工作">
              <option value="">存为工作交付物…</option>
              <option v-for="w in works" :key="w.id" :value="w.id">{{ w.title }}（{{ w.status }}）</option>
            </select>
            <button type="button" class="btn btn-ghost" :disabled="!targetWork || saving" @click="importDeliverable">存为交付物</button>
            <select v-model="targetKb" :disabled="saving || !kbs.length" aria-label="选择知识库">
              <option value="">存入知识库…</option>
              <option v-for="kb in kbs" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
            </select>
            <button type="button" class="btn btn-ghost" :disabled="!targetKb || saving" @click="importKnowledge">存入知识库</button>
          </div>
          <div class="artifact-actions">
            <span v-if="notice" class="artifact-notice">{{ notice }}</span>
            <button type="button" class="btn btn-ghost" @click="close">关闭</button>
            <button type="button" class="btn btn-primary" :disabled="!dirty || saving" @click="save">{{ saving ? '保存中…' : '保存修改' }}</button>
          </div>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Download, FileText, X } from 'lucide-vue-next'
import { artifactApi, knowledgeApi, workApi } from '../../api'
import MarkdownEditor from '../knowledge/MarkdownEditor.vue'

const props = defineProps({ conversationId: String, artifact: Object })
const emit = defineEmits(['close', 'saved'])
const visible = computed(() => !!props.artifact)
const detail = ref(null)
const title = ref('')
const content = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const dirty = computed(() => detail.value && (title.value !== detail.value.title || content.value !== detail.value.content))
const isMarkdown = computed(() => (detail.value?.format || props.artifact?.format || 'markdown') === 'markdown')
const works = ref([])
const kbs = ref([])
const targetWork = ref('')
const targetKb = ref('')

watch(() => props.artifact, a => { if (a) { detail.value = null; error.value = ''; notice.value = ''; targetWork.value = ''; targetKb.value = ''; load(); loadTargets() } })
watch([title, content], () => { if (detail.value) notice.value = '' })

async function load() {
  if (!props.conversationId || !props.artifact?.id) return
  loading.value = true
  try {
    const { data } = await artifactApi.get(props.conversationId, props.artifact.id)
    detail.value = data
    title.value = data.title
    content.value = data.content || ''
  } catch { error.value = '产出物加载失败' } finally { loading.value = false }
}
async function loadTargets() {
  try { const { data } = await workApi.list(); works.value = (data || []).filter(w => !['completed', 'cancelled'].includes(w.status)) } catch { works.value = [] }
  try { const { data } = await knowledgeApi.list({ scope: 'workspace' }); kbs.value = data || [] } catch { kbs.value = [] }
}
function formatSize(n) {
  if (n == null) return ''
  return n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KB`
}
async function save() {
  if (!dirty.value || saving.value) return
  saving.value = true; error.value = ''
  try {
    const { data } = await artifactApi.update(props.conversationId, props.artifact.id, { title: title.value.trim(), content: content.value })
    detail.value = { ...detail.value, ...data, content: content.value }
    notice.value = '已保存'
    emit('saved', data)
  } catch (e) { error.value = e.response?.data?.detail || '保存失败，请重试' } finally { saving.value = false }
}
async function importDeliverable() {
  if (!targetWork.value) return
  saving.value = true; notice.value = ''
  try {
    await artifactApi.toDeliverable(props.conversationId, props.artifact.id, targetWork.value)
    notice.value = '已复制为工作交付物（独立副本）'
    targetWork.value = ''
  } catch (e) { error.value = e.response?.data?.detail || '转存失败，请重试' } finally { saving.value = false }
}
async function importKnowledge() {
  if (!targetKb.value) return
  saving.value = true; notice.value = ''
  try {
    await artifactApi.toKnowledge(props.conversationId, props.artifact.id, targetKb.value)
    notice.value = '已存入知识库'
    targetKb.value = ''
  } catch (e) { error.value = e.response?.data?.detail || '存入知识库失败，请重试' } finally { saving.value = false }
}
function close() { emit('close') }
</script>

<style scoped>
.artifact-overlay { position: fixed; inset: 0; z-index: 2000; background: var(--overlay); display: flex; align-items: center; justify-content: center; padding: 24px; }
.artifact-dialog { display: flex; flex-direction: column; width: min(880px, 96vw); max-height: 88vh; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-dialog); overflow: hidden; }
.artifact-header { display: flex; align-items: center; gap: 10px; padding: 14px 16px; border-bottom: 1px solid var(--border); }
.artifact-icon { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 10px; background: var(--primary-light); color: var(--primary); flex-shrink: 0; }
.artifact-heading { min-width: 0; flex: 1; }
.artifact-heading h3 { margin: 0; font-size: 15px; line-height: 22px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.artifact-meta { margin: 2px 0 0; font-size: 12px; color: var(--text3); }
.artifact-dirty { color: var(--accent); }
.artifact-header-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.artifact-link { display: inline-flex; align-items: center; gap: 5px; height: 30px; padding: 0 10px; border: 1px solid var(--border); border-radius: var(--radius-xs); font-size: 12px; color: var(--text2); }
.artifact-link:hover { background: var(--surface2); color: var(--text); }
.artifact-close { display: grid; place-items: center; width: 30px; height: 30px; border: 0; border-radius: var(--radius-xs); background: transparent; color: var(--text3); cursor: pointer; }
.artifact-close:hover { background: var(--surface2); color: var(--text); }
.artifact-body { flex: 1; min-height: 0; overflow-y: auto; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.artifact-title-field, .artifact-content-field { display: flex; flex-direction: column; gap: 6px; font-size: 13px; font-weight: 500; color: var(--text2); }
.artifact-title-field input { height: 34px; padding: 0 10px; border: 1px solid var(--border); border-radius: var(--radius-xs); }
.artifact-plain { min-height: 320px; padding: 10px; border: 1px solid var(--border); border-radius: var(--radius-xs); font-family: ui-monospace, monospace; font-size: 12px; line-height: 1.6; resize: vertical; }
.artifact-loading, .artifact-error { font-size: 13px; color: var(--text3); }
.artifact-error { color: var(--danger); }
.artifact-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding: 12px 16px; border-top: 1px solid var(--border); }
.artifact-import { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.artifact-import select { max-width: 210px; height: 30px; font-size: 12px; border: 1px solid var(--border); border-radius: var(--radius-xs); padding: 0 6px; }
.artifact-actions { display: flex; align-items: center; gap: 8px; }
.artifact-notice { font-size: 12px; color: var(--success); }
</style>

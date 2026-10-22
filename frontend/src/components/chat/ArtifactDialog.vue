<template>
  <Teleport to="body">
    <div v-if="visible" class="artifact-overlay" :class="{ fullscreen }" @click.self="close" @keydown.esc="fullscreen ? (fullscreen = false) : close()">
      <section class="artifact-dialog" :class="{ fullscreen }" role="dialog" aria-modal="true" aria-labelledby="artifact-dialog-title">
        <header class="artifact-header">
          <div class="artifact-icon"><FileText :size="20" /></div>
          <div class="artifact-heading">
            <h3 id="artifact-dialog-title">{{ artifact?.title || '产出物' }}</h3>
            <p class="artifact-meta">{{ detail?.filename || artifact?.filename }} · {{ formatSize(detail?.size ?? artifact?.size) }}<span v-if="dirty" class="artifact-dirty"> · 未保存修改</span></p>
          </div>
          <div class="artifact-header-actions">
            <button v-if="!editing" type="button" class="artifact-tool" @click="startEdit"><Pencil :size="14" /> 编辑</button>
            <button type="button" class="artifact-tool" :title="fullscreen ? '退出全屏' : '全屏'" @click="fullscreen = !fullscreen">
              <Minimize2 v-if="fullscreen" :size="14" />
              <Maximize2 v-else :size="14" />
            </button>
            <a v-if="conversationId && artifact?.id" class="artifact-tool" :href="artifactApi.downloadUrl(conversationId, artifact.id)" download>
              <Download :size="14" /> 下载
            </a>
            <button type="button" class="artifact-close" aria-label="关闭" @click="close"><X :size="18" /></button>
          </div>
        </header>
        <div class="artifact-body" :class="{ fullscreen, editing }" :aria-busy="loading">
          <p v-if="error" class="artifact-error" role="alert">{{ error }} <button type="button" @click="load">重试</button></p>
          <template v-else-if="loading">
            <p class="artifact-loading">加载中…</p>
          </template>
          <template v-else-if="detail">
            <article v-if="!editing && isMarkdown" class="markdown-page" v-html="renderedMarkdown"></article>
            <pre v-else-if="!editing" class="artifact-readonly">{{ detail.content }}</pre>
            <template v-else>
              <label class="artifact-title-field">标题 <input ref="titleInput" v-model="title" maxlength="200" /></label>
              <label class="artifact-content-field">内容
                <textarea v-if="!isMarkdown" v-model="content" class="artifact-plain" spellcheck="false"></textarea>
                <MarkdownEditor v-else v-model="content" aria-label="产出物内容" />
              </label>
            </template>
          </template>
        </div>
        <footer class="artifact-footer">
          <div v-if="!editing" class="artifact-import">
            <select v-model="targetWork" :disabled="busy || !works.length" aria-label="选择工作">
              <option value="">存为工作交付物…</option>
              <option v-for="w in works" :key="w.id" :value="w.id">{{ w.title }}（{{ w.status }}）</option>
            </select>
            <button type="button" class="btn btn-ghost" :disabled="!targetWork || busy" @click="importDeliverable">存为交付物</button>
            <select v-model="targetKb" :disabled="busy || !kbs.length" aria-label="选择知识库">
              <option value="">存入知识库…</option>
              <option v-for="kb in kbs" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
            </select>
            <button type="button" class="btn btn-ghost" :disabled="!targetKb || busy" @click="importKnowledge">存入知识库</button>
          </div>
          <div v-else class="artifact-import"><span class="artifact-notice artifact-notice-edit">编辑中：修改需保存后生效</span></div>
          <div class="artifact-actions">
            <span v-if="notice" class="artifact-notice">{{ notice }}</span>
            <button v-if="editing" type="button" class="btn btn-ghost" :disabled="busy" @click="cancelEdit">取消</button>
            <button v-if="editing" type="button" class="btn btn-primary" :disabled="!dirty || busy" @click="save">{{ saving ? '保存中…' : '保存修改' }}</button>
            <button v-if="!editing" type="button" class="btn btn-ghost" @click="close">关闭</button>
          </div>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { marked } from 'marked'
import { Download, FileText, Maximize2, Minimize2, Pencil, X } from 'lucide-vue-next'
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
const editing = ref(false)
const fullscreen = ref(false)
const titleInput = ref(null)
const works = ref([])
const kbs = ref([])
const targetWork = ref('')
const targetKb = ref('')

const dirty = computed(() => detail.value && (title.value !== detail.value.title || content.value !== detail.value.content))
const isMarkdown = computed(() => (detail.value?.format || props.artifact?.format || 'markdown') === 'markdown')
const busy = computed(() => loading.value || saving.value)
const cleanMarkdownHtml = html => html
  .replace(/<(script|style|iframe|object|embed)[^>]*>[\s\S]*?<\/\1>/gi, '')
  .replace(/\s+on[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '')
  .replace(/(href|src)\s*=\s*(?:"|')?javascript:[^"'\s>]*/gi, '$1="#"')
const renderedMarkdown = computed(() => cleanMarkdownHtml(marked.parse(content.value || '', { gfm: true, breaks: true })))

watch(() => props.artifact, a => {
  if (!a) return
  detail.value = null
  error.value = ''; notice.value = ''
  editing.value = false; fullscreen.value = false
  targetWork.value = ''; targetKb.value = ''
  load(); loadTargets()
})

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
function startEdit() {
  editing.value = true
  nextTick(() => titleInput.value?.focus())
}
function cancelEdit() {
  editing.value = false
  title.value = detail.value?.title || ''
  content.value = detail.value?.content || ''
}
async function save() {
  if (!dirty.value || saving.value) return
  saving.value = true; error.value = ''
  try {
    const { data } = await artifactApi.update(props.conversationId, props.artifact.id, { title: title.value.trim(), content: content.value })
    detail.value = { ...detail.value, ...data, content: content.value }
    notice.value = '已保存'
    editing.value = false
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
.artifact-overlay.fullscreen { padding: 0; }
.artifact-dialog { display: flex; flex-direction: column; width: min(1180px, 96vw); height: min(88vh, 1000px); background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-dialog); overflow: hidden; }
.artifact-dialog.fullscreen { width: 100vw; height: 100dvh; max-width: none; border: 0; border-radius: 0; }
.artifact-header { display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
.artifact-icon { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 10px; background: var(--primary-light); color: var(--primary); flex-shrink: 0; }
.artifact-heading { min-width: 0; flex: 1; }
.artifact-heading h3 { margin: 0; font-size: 15px; line-height: 22px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.artifact-meta { margin: 2px 0 0; font-size: 12px; color: var(--text3); }
.artifact-dirty { color: var(--accent); }
.artifact-header-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.artifact-tool { display: inline-flex; align-items: center; gap: 5px; height: 30px; padding: 0 10px; border: 1px solid var(--border); border-radius: var(--radius-xs); background: transparent; font-size: 12px; color: var(--text2); cursor: pointer; text-decoration: none; }
.artifact-tool:hover { background: var(--surface2); color: var(--text); }
.artifact-close { display: grid; place-items: center; width: 30px; height: 30px; border: 0; border-radius: var(--radius-xs); background: transparent; color: var(--text3); cursor: pointer; }
.artifact-close:hover { background: var(--surface2); color: var(--text); }
.artifact-body { flex: 1; min-height: 0; overflow-y: auto; padding: 0; display: flex; flex-direction: column; }
.artifact-body > * { flex-shrink: 0; }
.markdown-page { margin: 0 auto; width: 100%; max-width: 980px; padding: 28px 36px; background: var(--surface); color: var(--text); overflow-wrap: anywhere; line-height: 1.85; }
.markdown-page :deep(h1), .markdown-page :deep(h2), .markdown-page :deep(h3) { line-height: 1.3; margin: 0 0 16px; }
.markdown-page :deep(p), .markdown-page :deep(ul), .markdown-page :deep(ol), .markdown-page :deep(blockquote), .markdown-page :deep(pre) { margin: 0 0 14px; }
.markdown-page :deep(ul), .markdown-page :deep(ol) { padding-left: 24px; }
.markdown-page :deep(blockquote) { border-left: 3px solid var(--primary); padding-left: 14px; color: var(--text3); }
.markdown-page :deep(code) { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; background: var(--surface2); padding: 2px 4px; border-radius: 4px; }
.markdown-page :deep(pre) { padding: 14px; overflow: auto; background: var(--surface2); border-radius: 6px; }
.markdown-page :deep(pre code) { padding: 0; background: none; }
.markdown-page :deep(a) { color: var(--primary); }
.markdown-page :deep(table) { border-collapse: collapse; margin: 0 0 14px; }
.markdown-page :deep(th), .markdown-page :deep(td) { border: 1px solid var(--border); padding: 6px 10px; }
.artifact-readonly { flex: 1; margin: 0; padding: 24px 32px; white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; font-size: 14px; line-height: 1.8; color: var(--text); }
.artifact-loading, .artifact-error { margin: 0; padding: 24px 32px; font-size: 13px; color: var(--text3); }
.artifact-error { color: var(--danger); }
.artifact-title-field, .artifact-content-field { display: flex; flex-direction: column; gap: 6px; margin: 16px auto 0; width: 100%; max-width: 980px; padding: 0 36px; font-size: 13px; font-weight: 500; color: var(--text2); }
.artifact-title-field input { height: 34px; padding: 0 10px; border: 1px solid var(--border); border-radius: var(--radius-xs); }
.artifact-content-field { margin-bottom: 16px; }
.artifact-plain { min-height: 380px; padding: 10px; border: 1px solid var(--border); border-radius: var(--radius-xs); font-family: ui-monospace, monospace; font-size: 12px; line-height: 1.6; resize: vertical; }
/* Edit mode: editor fills the whole dialog body. */
.artifact-body.editing { overflow: hidden; }
.artifact-body.editing .artifact-content-field { flex: 1; min-height: 0; margin-bottom: 16px; }
.artifact-body.editing .artifact-content-field :deep(.markdown-editor) { flex: 1; min-height: 0; }
.artifact-body.editing .artifact-plain { flex: 1; min-height: 0; height: 100%; resize: none; }
.artifact-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding: 12px 16px; border-top: 1px solid var(--border); flex-shrink: 0; }
.artifact-import { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.artifact-import select { max-width: 210px; height: 30px; font-size: 12px; border: 1px solid var(--border); border-radius: var(--radius-xs); padding: 0 6px; }
.artifact-notice-edit { color: var(--text3); }
.artifact-actions { display: flex; align-items: center; gap: 8px; }
.artifact-notice { font-size: 12px; color: var(--success); }
</style>

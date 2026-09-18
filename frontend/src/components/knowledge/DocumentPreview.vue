<template>
  <TextDocumentEditorDialog v-if="editMode" v-model="draft" :name="info?.name || name" :markdown="isMarkdown" :saving="saving" :error="editError" @close="cancelEdit" @save="saveEdit" />
  <Teleport v-if="pageTabActive && !editMode" to="body">
    <div class="preview-overlay" @click.self="$emit('close')" @keydown="handleKey">
      <section ref="dialog" class="document-preview" role="dialog" aria-modal="true" aria-labelledby="document-preview-title" tabindex="-1">
        <header>
          <div class="preview-file-icon"><FileText :size="23" /></div>
          <div class="heading"><h3 id="document-preview-title">{{ info?.name || name || '文档预览' }}</h3><span>{{ info ? `${kindLabel} · ${formatSize(info.size)}` : '正在读取文档信息…' }}</span></div>
          <button v-if="info?.download_available" class="download" :disabled="downloading" @click="download"><Download :size="16" />{{ downloading ? '下载中…' : '下载原文件' }}</button>
          <button v-if="info?.kind === 'text' && !readonly && !editMode" class="edit-button" aria-label="编辑" @click="startEdit"><Pencil :size="16" />编辑</button>
          <button class="icon-button" aria-label="关闭预览" @click="$emit('close')"><X :size="20" /></button>
        </header>
        <div v-if="info?.status === 'ready' && !editMode" class="preview-toolbar">
          <div class="page-controls"><button aria-label="上一页" :disabled="page <= 1" @click="go(page - 1)"><ChevronLeft :size="17" /></button><span>第 <input v-model="pageInput" type="number" min="1" :max="info.page_count" aria-label="跳转页码" @change="go(Number(pageInput))" @keydown.enter="go(Number(pageInput))" /> / {{ info.page_count }} {{ info.kind === 'text' ? '段' : '页' }}</span><button aria-label="下一页" :disabled="page >= info.page_count" @click="go(page + 1)"><ChevronRight :size="17" /></button></div>
          <span class="lazy-hint">{{ info.kind === 'text' ? '长文本分段加载' : '仅加载当前页' }}</span>
          <div v-if="info.kind !== 'text'" class="zoom-controls"><button aria-label="缩小" :disabled="zoom <= 50" @click="zoom -= 25"><Minus :size="16" /></button><button @click="zoom = 100">{{ zoom }}%</button><button aria-label="放大" :disabled="zoom >= 200" @click="zoom += 25"><Plus :size="16" /></button></div>
        </div>
        <div v-if="info?.message && info.status === 'ready'" class="preview-notice">{{ info.message }}</div>
        <div v-if="editError" class="preview-notice" role="alert">{{ editError }}</div>
        <div v-if="downloadError" class="preview-notice">{{ downloadError }}</div>
        <main ref="viewport" :aria-busy="loading || pageLoading">
          <div v-if="loading || info?.status === 'processing'" class="preview-state"><LoaderCircle :size="32" class="spin" /><strong>{{ info?.status === 'processing' ? '正在准备文档预览' : '正在加载…' }}</strong><p>{{ info?.message || '正在读取文件信息' }}</p><small v-if="info?.status === 'processing'">完成后自动显示，无需重新打开</small></div>
          <div v-else-if="error || info?.status !== 'ready'" class="preview-state"><FileWarning :size="36" /><strong>{{ error || info?.message || '暂时无法预览' }}</strong><button v-if="error || info?.status === 'error'" @click="loadInfo(true)">重新加载</button></div>
          <div v-else-if="pageLoading" class="preview-state"><LoaderCircle :size="30" class="spin" /><p>正在加载第 {{ page }} {{ info.kind === 'text' ? '段' : '页' }}…</p></div>
          <div v-else-if="pageError" class="preview-state"><FileWarning :size="32" /><p>{{ pageError }}</p><button @click="loadPage">重试当前页</button></div>
          <template v-else-if="info.kind === 'text'">
            <article v-if="isMarkdown" class="markdown-page" v-html="renderedPage" />
            <pre v-else class="text-page">{{ pageText || '（空白内容）' }}</pre>
          </template>
          <div v-else class="page-canvas" :style="{ width: zoom + '%' }"><img v-if="pageUrl" :src="pageUrl" :alt="`${info.name}，第 ${page} 页`" @error="pageError = '页面图片加载失败，请重试'" /></div>
        </main>
        <footer><span>支持 PDF · Word / Excel / PowerPoint · 图片 · 文本</span><span>← → 翻页 · Esc 关闭</span></footer>
      </section>
    </div>
  </Teleport>
</template>
<script setup>
import { inject as injectPageTab } from 'vue'
const pageTabActive = injectPageTab('pageTabActive', true)

import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { FileText, Download, X, ChevronLeft, ChevronRight, Minus, Plus, LoaderCircle, FileWarning, Pencil } from 'lucide-vue-next'
import { marked } from 'marked'
import TextDocumentEditorDialog from './TextDocumentEditorDialog.vue'
import { knowledgeApi } from '../../api'
const props = defineProps({ kbId: String, docId: String, name: String, readonly: Boolean })
const emit = defineEmits(['close'])
const info = ref(null), loading = ref(true), error = ref(''), page = ref(1), pageInput = ref(1), zoom = ref(100)
const pageLoading = ref(false), pageError = ref(''), pageUrl = ref(''), pageText = ref(''), downloading = ref(false), downloadError = ref('')
const editMode = ref(false), draft = ref(''), saving = ref(false), editError = ref('')
const dialog = ref(null), viewport = ref(null)
const kindLabel = computed(() => ({ pdf: 'PDF 文档', office: 'Office 文档', image: '图片', text: '文本', unsupported: '文件' }[info.value?.kind] || '文件'))
// TXT and MD documents both use Markdown syntax in the knowledge base.
const isMarkdown = computed(() => /\.(?:txt|md)$/i.test(info.value?.name || props.name || ''))
const cleanMarkdownHtml = html => html.replace(/<(script|style|iframe|object|embed)[^>]*>[\s\S]*?<\/\1>/gi, '').replace(/\s+on[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '').replace(/(href|src)\s*=\s*(?:"|')?javascript:[^"'\s>]*/gi, '$1="#"')
const markdownHtml = text => cleanMarkdownHtml(marked.parse(text || '', { gfm: true, breaks: true }))
const renderedPage = computed(() => markdownHtml(pageText.value))
const formatSize = size => !size ? '' : size < 1048576 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1048576).toFixed(1)} MB`
const TEXT_PAGE_SIZE = 12000
const utf8Size = value => new TextEncoder().encode(value || '').length
let metadataController, pageController, pollTimer, previousFocus, active = true
async function loadInfo(retry = false) {
  clearTimeout(pollTimer); metadataController?.abort(); metadataController = new AbortController()
  const signal = metadataController.signal
  error.value = ''; loading.value = true
  try {
    const { data } = await knowledgeApi.previewDoc(props.kbId, props.docId, { signal, params: retry ? { retry: true } : {} })
    if (signal.aborted || !active) return
    info.value = data
    if (data.status === 'processing') pollTimer = setTimeout(() => loadInfo(), 1500)
    else if (data.status === 'ready') await loadPage()
  } catch (e) { if (!signal.aborted) error.value = e.response?.data?.detail || '预览加载失败，请重试' }
  finally { if (!signal.aborted) loading.value = false }
}
async function loadPage() {
  pageController?.abort(); pageController = new AbortController()
  const signal = pageController.signal
  pageLoading.value = true; pageError.value = ''
  if (pageUrl.value) { URL.revokeObjectURL(pageUrl.value); pageUrl.value = '' }
  try {
    const { data } = await knowledgeApi.previewPage(props.kbId, props.docId, page.value, { signal, responseType: info.value.kind === 'text' ? 'json' : 'blob' })
    if (signal.aborted || !active) return
    if (info.value.kind === 'text') pageText.value = data.content
    else pageUrl.value = URL.createObjectURL(data)
    viewport.value?.scrollTo(0, 0)
  } catch (e) {
    if (!signal.aborted) pageError.value = '该页加载失败，请重试；也可下载原文件查看'
  } finally { if (!signal.aborted) pageLoading.value = false }
}
async function startEdit() {
  if (props.readonly || info.value?.kind !== 'text') return
  editError.value = ''
  try {
    const { data } = await knowledgeApi.getDocContent(props.kbId, props.docId)
    draft.value = data.content || ''; editMode.value = true
  } catch (e) { editError.value = e.response?.data?.detail || '正文加载失败，请重试' }
}
function cancelEdit() { editMode.value = false; editError.value = ''; nextTick(() => dialog.value?.querySelector('.edit-button')?.focus()) }
async function saveEdit() {
  if (saving.value || !draft.value.trim()) return
  saving.value = true; editError.value = ''
  try {
    const { data } = await knowledgeApi.updateDocContent(props.kbId, props.docId, draft.value)
    const previousInfo = info.value || {}
    const pageCount = Math.max(1, Math.ceil(draft.value.length / TEXT_PAGE_SIZE))
    const currentPage = Math.min(page.value, pageCount)
    page.value = currentPage; pageInput.value = currentPage
    info.value = {
      ...previousInfo,
      name: data?.name || previousInfo.name,
      size: data?.metadata_json?.size ?? data?.size ?? utf8Size(draft.value),
      kind: previousInfo.kind || 'text',
      status: previousInfo.status === 'ready' ? 'ready' : (previousInfo.status || 'ready'),
      page_count: pageCount,
      content_type: data?.metadata_json?.content_type || previousInfo.content_type || 'text/plain',
      download_available: previousInfo.download_available,
    }
    pageText.value = draft.value.slice((currentPage - 1) * TEXT_PAGE_SIZE, currentPage * TEXT_PAGE_SIZE)
    cancelEdit()
  } catch (e) { editError.value = e.response?.data?.detail || '保存失败，请重试' }
  finally { saving.value = false }
}
function go(value) {
  const target = Math.max(1, Math.min(info.value?.page_count || 1, Math.trunc(value) || 1))
  pageInput.value = target
  if (target === page.value) return
  page.value = target; loadPage()
}
async function download() {
  downloading.value = true; downloadError.value = ''
  try {
    const { data } = await knowledgeApi.downloadDoc(props.kbId, props.docId)
    if (!active) return
    const url = URL.createObjectURL(data), link = document.createElement('a')
    link.href = url; link.download = info.value.name; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch { downloadError.value = '下载失败，请重试' }
  finally { downloading.value = false }
}
function handleKey(event) {
  if (event.key === 'Escape') { event.stopPropagation(); emit('close') }
  if (event.key === 'Tab') {
    const focusable = [...dialog.value.querySelectorAll('button:not(:disabled), input')]
    const index = focusable.indexOf(document.activeElement)
    if (event.shiftKey && index <= 0) { event.preventDefault(); focusable.at(-1)?.focus() }
    else if (!event.shiftKey && (index === focusable.length - 1 || index < 0)) { event.preventDefault(); focusable[0]?.focus() }
  }
  if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA' || editMode.value || info.value?.status !== 'ready') return
  if (event.key === 'ArrowLeft') { event.preventDefault(); go(page.value - 1) }
  if (event.key === 'ArrowRight') { event.preventDefault(); go(page.value + 1) }
}
onMounted(() => { previousFocus = document.activeElement; dialog.value?.focus(); loadInfo() })
onBeforeUnmount(() => { active = false; clearTimeout(pollTimer); metadataController?.abort(); pageController?.abort(); if (pageUrl.value) URL.revokeObjectURL(pageUrl.value); previousFocus?.focus() })
</script>
<style scoped>
.preview-overlay{position:fixed;inset:0;z-index:3000;background:#101828a6;display:grid;place-items:center;padding:24px;backdrop-filter:blur(4px)}.document-preview{width:min(1200px,96vw);height:92vh;display:flex;flex-direction:column;background:var(--surface,#fff);color:var(--text,#334155);border:1px solid var(--border,#ddd);border-radius:16px;overflow:hidden;box-shadow:0 30px 100px #0005;outline:none}header{display:flex;gap:14px;align-items:center;padding:17px 22px;border-bottom:1px solid var(--border,#e2e8f0)}.preview-file-icon{width:42px;height:42px;border-radius:10px;background:#6366f112;color:var(--primary,#6366f1);display:grid;place-items:center;flex-shrink:0}.heading{min-width:0;flex:1}.heading h3{font-size:16px;margin:0 0 5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.heading span{font-size:12px;color:var(--text3,#64748b)}button{font:inherit;font-size:12px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:6px;border:1px solid var(--border,#ddd);background:var(--surface,#fff);color:inherit;border-radius:7px;padding:7px 10px}button:disabled{opacity:.4;cursor:default}.icon-button{border:0}.download{white-space:nowrap}.preview-toolbar{display:flex;align-items:center;gap:16px;padding:10px 22px;background:var(--surface2,#f8fafc);border-bottom:1px solid var(--border,#e2e8f0);font-size:12px}.page-controls,.zoom-controls{display:flex;align-items:center;gap:8px}.page-controls input{width:52px;padding:5px;border:1px solid var(--border,#ddd);border-radius:5px;background:var(--surface,#fff);color:inherit;text-align:center;font:inherit}.lazy-hint{color:var(--text3,#64748b)}.zoom-controls{margin-left:auto}.preview-notice{padding:9px 22px;background:#f59e0b15;color:var(--text,#92400e);font-size:12px}main{overflow:auto;flex:1;min-height:0;padding:24px;background:var(--surface2,#e9edf3)}.preview-state{display:flex;align-items:center;justify-content:center;flex-direction:column;gap:16px;text-align:center;min-height:100%;color:var(--text3,#64748b);font-size:14px}.preview-state p{margin:0;max-width:600px}.preview-state strong{max-width:600px;line-height:1.8}.page-canvas{margin:0 auto;min-width:200px}.page-canvas img{display:block;width:100%;height:auto;box-shadow:0 3px 20px #0002;background:white}.text-page{margin:0 auto;background:var(--surface,#fff);color:var(--text,#334155);max-width:1000px;padding:28px;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.85;font:13px/1.85 ui-monospace,SFMono-Regular,Consolas,monospace;box-shadow:0 3px 18px #0001;border-radius:6px}footer{display:flex;justify-content:space-between;gap:10px;padding:10px 22px;font-size:11px;color:var(--text3,#64748b);border-top:1px solid var(--border,#ddd)}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:640px){.preview-overlay{padding:0}.document-preview{width:100vw;height:100dvh;border-radius:0}header{padding:12px;gap:8px}.preview-file-icon,.download,.lazy-hint,footer span:last-child{display:none}.preview-toolbar{padding:8px;gap:6px}.zoom-controls{gap:3px}main{padding:12px}.text-page{padding:14px}}
.markdown-page{margin:0 auto;background:var(--surface,#fff);color:var(--text,#334155);max-width:1000px;padding:28px;overflow-wrap:anywhere;line-height:1.85;box-shadow:0 3px 18px #0001;border-radius:6px}.markdown-page h1,.markdown-page h2,.markdown-page h3{line-height:1.3;margin:0 0 16px}.markdown-page h1{font-size:28px}.markdown-page h2{font-size:22px}.markdown-page h3{font-size:18px}.markdown-page p,.markdown-page ul,.markdown-page ol,.markdown-page blockquote,.markdown-page pre{margin:0 0 14px}.markdown-page ul,.markdown-page ol{padding-left:24px}.markdown-page blockquote{border-left:3px solid var(--primary,#6366f1);padding-left:14px;color:var(--text3,#64748b)}.markdown-page code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;background:var(--surface2,#f1f5f9);padding:2px 4px;border-radius:4px}.markdown-page pre{padding:14px;overflow:auto;background:#111827;color:#e5e7eb;border-radius:6px}.markdown-page pre code{padding:0;background:none}.markdown-page a{color:var(--primary,#4f46e5)}.edit-button{white-space:nowrap}
</style>

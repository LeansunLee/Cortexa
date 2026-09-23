<template>
  <Teleport to="body">
    <div class="summary-overlay" @click.self="!saving && $emit('close')" @keydown.esc="!saving && $emit('close')">
      <div class="summary-dialog" role="dialog" aria-modal="true" aria-labelledby="summary-title" @click.stop>
        <h3 id="summary-title">文档摘要</h3>
        <p class="document-title" :title="doc.name">{{ doc.name }}</p>
        <p class="source-badge" :class="sourceKey"><span class="source-dot" />{{ sourceLabel }}</p>
        <p class="job-status" role="status">{{ documentStatus(doc) }}</p>
        <p v-if="extractionHint || documentErrors(doc)" class="job-error" role="alert">{{ extractionHint || documentErrors(doc) }}</p>
        <textarea
          v-if="editing"
          v-model="draft"
          class="summary-editor"
          rows="10"
          maxlength="8000"
          aria-label="编辑摘要"
          autofocus
        />
        <div v-else class="summary-text" :class="{ empty: !summaryText }">
          {{ summaryText || emptyHint }}
        </div>
        <div class="hint-row">
          <p class="hint">
            <template v-if="editing">{{ draft.length }} / 8000 字 · 摘要用于知识库检索定位，建议保留型号、参数等关键检索词。</template>
            <template v-else>摘要用于 Agent 检索知识库时的文档定位，修改后立即生效。</template>
          </p>
          <button v-if="!editing && !readonly && retryAvailable" type="button" class="regen-btn" :disabled="regenerating" @click="retryRecognition"><RefreshCw :size="13" />{{ regenerating ? '提交中…' : '自动生成摘要' }}</button>
          <button v-else-if="!editing && !readonly && doc.metadata_json?.encoding !== 'base64'" type="button" class="regen-btn" :disabled="regenerating || !!extractionHint || pending(doc.metadata_json?.summary_status)" @click="regenerateSummary">
            <RefreshCw :size="13" :class="{ spinning: regenerating }" />{{ regenerating ? '生成中…' : '重新生成' }}
          </button>
        </div>
        <div class="actions">
          <template v-if="editing">
            <button type="button" class="btn btn-ghost btn-sm" :disabled="saving" @click="cancelEdit">取消</button>
            <button type="button" class="btn btn-primary btn-sm save" :disabled="saving || !draft.trim() || draft.trim() === summaryText" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
          </template>
          <template v-else>
            <button type="button" class="btn btn-ghost btn-sm" @click="$emit('close')">关闭</button>
            <button v-if="!readonly" type="button" class="btn btn-primary btn-sm save" :disabled="regenerating" @click="startEdit">{{ summaryText ? '编辑' : '手动填写' }}</button>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>
<script setup>
import { RefreshCw } from 'lucide-vue-next'
import { ref, computed } from 'vue'
import { knowledgeApi } from '../../api'
import { documentStatus, documentErrors, pending } from './documentStatus.js'
const props = defineProps({ kbId: { type: String, required: true }, doc: { type: Object, required: true }, readonly: Boolean })
const emit = defineEmits(['close', 'saved', 'queued'])
const editing = ref(false)
const draft = ref('')
const saving = ref(false)
const regenerating = ref(false)
const summaryText = computed(() => props.doc.metadata_json?.encoding === 'base64' && !['manual', 'llm', 'full'].includes(props.doc.metadata_json?.summary_source) ? '' : props.doc.content || '')
const sourceKey = computed(() => summaryText.value ? props.doc.metadata_json?.summary_source || 'unknown' : 'none')
const retryAvailable = computed(() => !pending(props.doc.metadata_json?.extraction_status) && (props.doc.metadata_json?.extraction_status === 'error' || props.doc.metadata_json?.encoding === 'base64' || props.doc.metadata_json?.summary_status === 'unsupported'))
const emptyHint = computed(() => pending(props.doc.metadata_json?.extraction_status) ? '正在提取文件内容，完成后会自动生成摘要。' : '该文档还没有摘要，可以自动提取后生成，或点击下方手动填写。')
const sourceLabel = computed(() => ({ full: '全文摘要（不超过 1000 字）', llm: 'LLM 自动生成', file_info: '文件信息摘要（未提取正文）', manual: '手动编辑', truncated: '截断回退（未生成 LLM 摘要）', unknown: '正文摘录', none: '未生成' }[sourceKey.value]))
const extractionHint = computed(() => pending(props.doc.metadata_json?.extraction_status) ? '正在识别文件正文，完成后会自动生成摘要。' : props.doc.metadata_json?.extraction_status === 'error' ? '正文识别失败，可以重试识别或手动填写摘要。' : '')
const toast = (message, type = 'success') => window.dispatchEvent(new CustomEvent('toast', { detail: { message, type } }))
function startEdit() { draft.value = summaryText.value; editing.value = true }
function cancelEdit() { editing.value = false; draft.value = '' }
async function save() {
  if (saving.value || !draft.value.trim()) return
  saving.value = true
  try {
    const { data } = await knowledgeApi.updateDocSummary(props.kbId, props.doc.id, draft.value.trim())
    editing.value = false
    emit('saved', data)
  } catch (error) { toast('摘要保存失败：' + (error.response?.data?.detail || '请重试'), 'error') }
  finally { saving.value = false }
}
async function retryRecognition() {
  if (regenerating.value) return
  regenerating.value = true
  try {
    await knowledgeApi.extractDoc(props.kbId, props.doc.id)
    toast('已提交内容提取，完成后会自动生成摘要')
    emit('queued')
  } catch (error) { toast(error.response?.data?.detail || '无法启动识别，请重试', 'error') }
  finally { regenerating.value = false }
}
async function regenerateSummary() {
  if (regenerating.value) return
  regenerating.value = true
  try {
    const { data } = await knowledgeApi.regenDocSummary(props.kbId, props.doc.id)
    emit('saved', data)
    toast('摘要已重新生成')
  } catch (error) { toast('生成失败：' + (error.response?.data?.detail || '请重试'), 'error') }
  finally { regenerating.value = false }
}
</script>
<style scoped>
.job-status,.job-error{font-size:12px;line-height:1.6;margin:0 0 10px;overflow-wrap:anywhere}.job-error{color:#b45309}:root[data-theme="dark"] .job-error{color:#fbbf24}
.summary-overlay{position:fixed;inset:0;z-index:2600;background:var(--overlay);display:grid;place-items:center;padding:20px}
.summary-dialog{width:560px;max-width:100%;box-sizing:border-box;background:var(--surface,#fff);color:var(--text,#334155);padding:26px;border-radius:16px;box-shadow:0 20px 70px #0003;max-height:90vh;display:flex;flex-direction:column}
.summary-dialog h3{font-size:18px;margin:0 0 8px}
.document-title{font-size:13px;color:var(--text3,#64748b);margin:0 0 10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.source-badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;margin:0 0 14px;color:var(--text2,#475569)}
.source-dot{width:8px;height:8px;border-radius:50%;background:var(--primary,#6366f1)}
.source-badge.manual .source-dot{background:var(--success)}
.source-badge.truncated .source-dot,.source-badge.none .source-dot{background:#d97706}:root[data-theme="dark"] .source-badge.truncated .source-dot,:root[data-theme="dark"] .source-badge.none .source-dot{background:#fbbf24}
.summary-text{flex:1;min-height:120px;max-height:46vh;overflow-y:auto;overflow-wrap:anywhere;white-space:pre-wrap;font-size:13px;line-height:1.7;background:var(--surface2,#f8fafc);border:1px solid var(--border,#e2e8f0);border-radius:10px;padding:14px}
.summary-text.empty{color:var(--text3,#94a3b8)}
.summary-editor{flex:1;min-height:160px;font:inherit;font-size:13px;line-height:1.7;border:1px solid var(--border,#ddd);border-radius:10px;padding:14px;background:var(--surface2,#f8fafc);color:inherit;resize:vertical}
.summary-editor:focus-visible{outline:2px solid var(--primary,#6366f1);outline-offset:-2px}
.hint-row{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:12px 0 0}
.hint{font-size:12px;line-height:1.6;color:var(--text3,#64748b);margin:0;flex:1}
.regen-btn{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--border,#ddd);border-radius:6px;background:transparent;color:var(--text3,#64748b);padding:6px 10px;font-size:12px;cursor:pointer;white-space:nowrap;flex-shrink:0}
.regen-btn:hover{background:var(--surface2,#f1f5f9);color:var(--primary,#6366f1);border-color:var(--primary,#6366f1)}
.regen-btn:disabled{opacity:.5;cursor:default}
.regen-btn .spinning{animation:spin 1s linear infinite}
@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
.actions{display:flex;justify-content:flex-end;gap:10px;margin-top:20px}


.actions button:disabled{opacity:.5;cursor:default}
</style>

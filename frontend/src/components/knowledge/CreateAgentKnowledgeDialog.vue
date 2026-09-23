<template>
  <Teleport to="body">
    <dialog ref="dialog" class="agent-knowledge-dialog" aria-labelledby="agent-knowledge-title" @cancel.prevent="close" @click="onBackdrop" @keydown.tab="trapFocus">
      <form @submit.prevent="create">
        <header><h2 id="agent-knowledge-title">创建独立知识库</h2><button type="button" class="btn btn-ghost close-button" aria-label="关闭" :disabled="saving" @click="close"><X :size="18" /></button></header>
        <p class="dialog-description">{{ management ? '创建后可添加文件夹和文档，绑定需保存并发布后生效。' : '创建后自动供当前 Agent 使用，可继续添加文件夹和文档。' }}</p>
        <label for="agent-knowledge-name">知识库名称</label>
        <input id="agent-knowledge-name" v-model.trim="name" class="form-input" placeholder="例如：产品资料" maxlength="200" required autofocus :disabled="saving" :aria-invalid="!!error" :aria-describedby="error ? 'agent-knowledge-error' : undefined" />
        <label for="agent-knowledge-desc" class="desc-label">描述（选填）</label>
        <textarea id="agent-knowledge-desc" v-model.trim="description" class="form-textarea" rows="3" placeholder="描述资料范围，方便团队成员了解库内内容" maxlength="500" :disabled="saving" />
        <p v-if="error" id="agent-knowledge-error" class="dialog-error" role="alert">{{ error }}</p>
        <footer><button type="button" class="btn btn-ghost" :disabled="saving" @click="close">取消</button><button class="btn btn-primary" :disabled="saving || !name">{{ saving ? '创建中…' : '创建' }}</button></footer>
      </form>
    </dialog>
  </Teleport>
</template>
<script setup>
import { ref, inject, watch, nextTick, onBeforeUnmount } from 'vue'
import { X } from 'lucide-vue-next'
import { knowledgeApi, agentOpsApi } from '../../api'
const props = defineProps({ agentId: { type: String, required: true }, management: Boolean })
const emit = defineEmits(['close', 'created'])
const dialog = ref(null), name = ref(''), description = ref(''), saving = ref(false), error = ref('')
const pageTabActive = inject('pageTabActive', ref(true))
const previousFocus = document.activeElement
// Native modal dialogs provide focus trapping and keep the rest of the page inert.
watch([dialog, () => !!(pageTabActive?.value ?? pageTabActive)], ([element, active]) => {
  if (!element) return
  if (active && !element.open) element.showModal()
  if (!active && element.open) element.close()
}, { flush: 'post' })
function close() { if (!saving.value) emit('close') }
function trapFocus(event) {
  const controls = [...dialog.value.querySelectorAll('button:not(:disabled), input:not(:disabled)')]
  if (!controls.length) { event.preventDefault(); return }
  const first = controls[0], last = controls.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
function onBackdrop(event) {
  if (event.target !== dialog.value) return
  const r = dialog.value.getBoundingClientRect()
  if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) close()
}
async function create() {
  if (saving.value || !name.value) return
  saving.value = true; error.value = ''
  try {
    const payload = { name: name.value, description: description.value || null }
    const { data } = await (props.management
      ? knowledgeApi.create({ ...payload, type: 'documents', agent_id: props.agentId })
      : agentOpsApi.createKnowledge(props.agentId, payload))
    emit('created', data)
  } catch (e) {
    const detail = e.response?.data?.detail
    error.value = typeof detail === 'string' ? detail : '创建失败，请稍后重试'
  } finally { saving.value = false }
}
onBeforeUnmount(() => {
  dialog.value?.close()
  nextTick(() => { if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true }) })
})
</script>
<style scoped>
.agent-knowledge-dialog { position: fixed; inset: 0; margin: auto; width: min(460px, calc(100vw - 32px)); max-height: calc(100dvh - 32px); overflow-y: auto; padding: 24px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); color: var(--text); box-shadow: var(--shadow-md); }
.agent-knowledge-dialog::backdrop { background: var(--overlay); }
header, footer { display: flex; align-items: center; gap: 12px; }header { justify-content: space-between; }h2 { margin: 0; font-size: 18px; line-height: 26px; }
.close-button { padding: 6px; flex: 0 0 auto; }.dialog-description { margin: 12px 0 20px; font-size: 13px; line-height: 22px; color: var(--text2); }
label { display: block; margin-bottom: 8px; font-size: 13px; font-weight: 600; }.desc-label { margin-top: 16px; }input, textarea { line-height: 20px; }footer { justify-content: flex-end; margin-top: 24px; }.btn { white-space: nowrap; line-height: 20px; }
.dialog-error { margin: 12px 0 0; font-size: 13px; line-height: 20px; color: var(--danger); overflow-wrap: anywhere; }
@media(max-width: 480px) { .agent-knowledge-dialog { padding: 20px; } }
</style>

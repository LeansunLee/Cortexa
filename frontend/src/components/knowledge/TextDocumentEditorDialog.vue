<template>
  <Teleport v-if="pageTabActive" to="body">
    <div class="textdoc-overlay" @click.self="close" @keydown="handleKey">
      <section ref="dialog" class="textdoc-dialog" role="dialog" aria-modal="true" aria-labelledby="textdoc-title" tabindex="-1">
        <header class="textdoc-header">
          <div class="textdoc-icon"><FileText :size="23" /></div>
          <h3 id="textdoc-title">{{ creating ? '创建文本文档' : '编辑文本文档' }}</h3>
          <button class="btn btn-ghost close-button" type="button" aria-label="关闭编辑器" :disabled="saving" @click="close"><X :size="20" /></button>
        </header>
        <div class="textdoc-body" :aria-busy="saving">
          <label class="name-field">
            <span>文件名</span>
            <input ref="nameInput" :value="name" :readonly="!creating" :disabled="saving" placeholder="例如：笔记.txt 或 说明.md" maxlength="100" @input="$emit('update:name', $event.target.value)" />
          </label>
          <div class="content-field" :inert="saving">
            <label id="textdoc-content-label">正文</label>
            <MarkdownEditor v-if="markdown" :model-value="modelValue" aria-label="文本文档正文" aria-labelledby="textdoc-content-label" @update:model-value="$emit('update:modelValue', $event)" />
            <textarea v-else :value="modelValue" class="plain-editor" spellcheck="false" aria-labelledby="textdoc-content-label" @input="$emit('update:modelValue', $event.target.value)" />
          </div>
        </div>
        <footer class="textdoc-footer">
          <div class="editor-feedback">
            <p class="hint">{{ modelValue.length }} 字<span v-if="markdown"> · Markdown 原文会保存到知识库</span></p>
            <p v-if="error" class="edit-error" role="alert">{{ error }}</p>
          </div>
          <div class="actions">
            <button type="button" class="btn btn-ghost" :disabled="saving" @click="close">取消</button>
            <button type="button" class="btn btn-primary" :aria-label="creating ? '创建文档' : '保存'" :disabled="saving || !name.trim() || !modelValue.trim()" @click="$emit('save')">{{ saving ? (creating ? '创建中…' : '保存中…') : (creating ? '创建文档' : '保存') }}</button>
          </div>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { FileText, X } from 'lucide-vue-next'
import MarkdownEditor from './MarkdownEditor.vue'
const props = defineProps({
  creating: Boolean, name: { type: String, default: '' },
  modelValue: { type: String, default: '' }, markdown: { type: Boolean, default: true },
  saving: Boolean, error: { type: String, default: '' },
})
const emit = defineEmits(['close', 'save', 'update:name', 'update:modelValue'])
const pageTabActive = inject('pageTabActive', true)
const dialog = ref(null), nameInput = ref(null)
let previousFocus
const close = () => { if (!props.saving) emit('close') }
function handleKey(event) {
  if (event.key === 'Escape') { event.stopPropagation(); close(); return }
  if (event.key !== 'Tab') return
  const focusable = [...dialog.value.querySelectorAll('button:not(:disabled), input:not(:disabled), textarea, [contenteditable="true"], [tabindex="0"]')].filter(el => el.getClientRects().length && !el.closest('[inert]'))
  const first = focusable[0], last = focusable.at(-1)
  if (!first) { event.preventDefault(); dialog.value.focus(); return }
  if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.value)) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.value)) { event.preventDefault(); first.focus() }
}
function focusEditor() {
  if (props.creating) nameInput.value?.focus()
  else dialog.value?.focus()
}
watch(() => props.saving, async saving => { if (!saving) { await nextTick(); dialog.value?.focus() } })
onMounted(() => { previousFocus = document.activeElement; focusEditor() })
onBeforeUnmount(() => previousFocus?.focus())
</script>

<style scoped>
.textdoc-overlay{position:fixed;inset:0;z-index:3000;display:grid;place-items:center;padding:24px;background:var(--overlay, #101828a6);backdrop-filter:blur(4px)}
.textdoc-dialog{box-sizing:border-box;width:min(1200px,96vw);height:min(92dvh,960px);display:flex;flex-direction:column;overflow:hidden;background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:16px;box-shadow:0 30px 100px #0005;outline:none}
.textdoc-header{display:flex;align-items:center;gap:14px;padding:17px 22px;border-bottom:1px solid var(--border);flex-shrink:0}
.textdoc-icon{display:grid;place-items:center;width:42px;height:42px;border-radius:10px;background:var(--primary-light);color:var(--primary)}
h3{flex:1;font-size:16px;margin:0}.close-button{padding:7px;border:0}
.textdoc-body{display:flex;flex-direction:column;flex:1;min-height:0;padding:20px 24px;gap:18px;background:transparent}
.name-field{display:flex;flex-direction:column;gap:8px;flex-shrink:0}
.name-field span,.content-field>label{font-size:13px;color:var(--text2)}
.name-field input{box-sizing:border-box;width:100%;padding:10px 12px;font:inherit;font-size:14px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text)}
.name-field input:read-only{color:var(--text2);background:var(--surface2)}
.content-field{display:flex;flex-direction:column;gap:8px;flex:1;min-height:0}
.content-field :deep(.markdown-editor){flex:1;min-height:0;height:auto}
.plain-editor{box-sizing:border-box;flex:1;min-height:0;width:100%;padding:20px;resize:none;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text);font:14px/1.75 ui-monospace,SFMono-Regular,Consolas,monospace}
.content-field :deep(.markdown-editor:focus-within){border-color:var(--primary);box-shadow:0 0 0 2px var(--primary-light)}
.textdoc-footer{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 24px;border-top:1px solid var(--border);flex-shrink:0}
.editor-feedback{min-width:0}.hint,.edit-error{font-size:12px;line-height:1.6;margin:0;color:var(--text3)}.edit-error{color:var(--danger, #dc2626);overflow-wrap:anywhere}
.actions{display:flex;gap:10px;flex-shrink:0}
@media(max-width:640px){.textdoc-overlay{padding:0}.textdoc-dialog{width:100vw;height:100dvh;border-radius:0}.textdoc-header{padding:12px;gap:8px}.textdoc-icon{display:none}.textdoc-body{padding:12px;gap:12px}.textdoc-footer{padding:12px;align-items:stretch;flex-direction:column;gap:8px}.actions{justify-content:flex-end}}
</style>

<template>
  <div ref="editorRoot" class="markdown-editor" :aria-label="ariaLabel" :aria-labelledby="ariaLabelledby"></div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Editor from '@toast-ui/editor'
import '@toast-ui/editor/dist/toastui-editor.css'
import '@toast-ui/editor/dist/theme/toastui-editor-dark.css'

const props = defineProps({
  modelValue: { type: String, default: '' },
  ariaLabel: { type: String, default: 'Markdown 文档编辑器' },
  ariaLabelledby: { type: String, default: undefined },
})
const emit = defineEmits(['update:modelValue'])

const editorRoot = ref(null)
let editor
let changingFromEditor = false
let appearanceObserver
const syncAppearance = () => editorRoot.value?.classList.toggle('toastui-editor-dark', !editorRoot.value?.closest('.textdoc-dialog') && document.documentElement.dataset.theme === 'dark')

const toolbarItems = [
  ['heading', 'bold', 'italic', 'strike'],
  ['hr', 'quote'],
  ['ul', 'ol', 'task', 'indent', 'outdent'],
  ['table', 'link', 'code', 'codeblock'],
]

onMounted(() => {
  editor = new Editor({
    el: editorRoot.value,
    height: '100%',
    initialValue: props.modelValue,
    initialEditType: 'wysiwyg',
    previewStyle: 'vertical',
    hideModeSwitch: true,
    usageStatistics: false,
    autofocus: false,
    toolbarItems,
  })
  editor.on('change', () => {
    changingFromEditor = true
    emit('update:modelValue', editor.getMarkdown())
    changingFromEditor = false
  })
  const input = editorRoot.value.querySelector('.toastui-editor-ww-container [contenteditable="true"]')
  input?.setAttribute('role', 'textbox')
  input?.setAttribute('aria-multiline', 'true')
  input?.setAttribute('aria-label', props.ariaLabel)
  if (props.ariaLabelledby) input?.setAttribute('aria-labelledby', props.ariaLabelledby)
  syncAppearance()
  appearanceObserver = new MutationObserver(syncAppearance)
  appearanceObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
})

watch(() => props.modelValue, value => {
  if (!editor || changingFromEditor || value === editor.getMarkdown()) return
  editor.setMarkdown(value || '', false)
})

onBeforeUnmount(() => {
  appearanceObserver?.disconnect()
  editor?.destroy()
  editor = undefined
})
</script>

<style scoped>
.markdown-editor {
  position: relative;
  box-sizing: border-box;
  min-height: 240px;
  height: 100%;
  overflow: hidden;
  border: 1px solid var(--border, #d1d5db);
  border-radius: 8px;
  background: var(--surface, #fff);
}

.markdown-editor :deep(.toastui-editor-defaultUI) {
  /* Anchor the editor to the actual frame, avoiding percentage heights in
     auto-sized flex children collapsing the editable area to zero. */
  position: absolute;
  inset: 0;
  height: 100%;
  border: 0;
}

.markdown-editor :deep(.toastui-editor-main) {
  background: var(--surface, #fff);
}

.markdown-editor :deep(.toastui-editor-ww-container) {
  background: var(--surface, #fff);
}

.markdown-editor :deep(.toastui-editor-ww-container .ProseMirror) {
  min-height: 100%;
  cursor: text;
}

.markdown-editor :deep(.toastui-editor-contents) {
  color: var(--text, #334155);
  font-family: inherit;
  font-size: 14px;
  line-height: 1.75;
}

.markdown-editor :deep(.toastui-editor-toolbar) {
  background: var(--surface2, #f8fafc);
  border-bottom-color: var(--border, #e2e8f0);
}

@media (max-width: 640px) {
  .markdown-editor :deep(.toastui-editor-toolbar-icons) { transform: scale(.92); }
}
</style>

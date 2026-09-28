<template>
  <Teleport v-if="pageTabActive" to="body">
    <div class="confirm-backdrop" @click.self="!busy && $emit('cancel')" @keydown.esc.stop="!busy && $emit('cancel')" @keydown.tab="trapFocus">
      <section ref="dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" class="confirm-dialog">
        <div class="danger-icon"><Trash2 :size="24" /></div>
        <h3 id="confirm-title">{{ title }}</h3>
        <p>{{ message }}</p>
        <div class="confirm-actions">
          <button ref="cancelButton" :disabled="busy" @click="$emit('cancel')">取消</button>
          <button class="danger" :disabled="busy" @click="$emit('confirm')">{{ busy ? '删除中…' : '确认删除' }}</button>
        </div>
      </section>
    </div>
  </Teleport>
</template>
<script setup>
import { inject as injectPageTab } from 'vue'
const pageTabActive = injectPageTab('pageTabActive', true)

import { ref, onMounted, onBeforeUnmount } from 'vue'
import { Trash2 } from 'lucide-vue-next'
defineProps({ title: String, message: String, busy: Boolean })
defineEmits(['confirm', 'cancel'])
const dialog = ref(null)
const cancelButton = ref(null)
let previousFocus
onMounted(() => { previousFocus = document.activeElement; cancelButton.value?.focus() })
onBeforeUnmount(() => previousFocus?.focus())
function trapFocus(event) {
  const buttons = [...dialog.value.querySelectorAll('button:not(:disabled)')]
  const index = buttons.indexOf(document.activeElement)
  event.preventDefault()
  buttons[(index + (event.shiftKey ? -1 : 1) + buttons.length) % buttons.length]?.focus()
}
</script>
<style scoped>
.confirm-backdrop{position:fixed;inset:0;background:var(--overlay);z-index:4000;display:grid;place-items:center;padding:20px}
.confirm-dialog{background:var(--surface-dialog);color:var(--text);border:1px solid var(--border);border-radius:var(--radius);padding:28px;width:420px;max-width:100%;box-shadow:var(--shadow-dialog);box-sizing:border-box}
.danger-icon{width:48px;height:48px;border-radius:var(--radius);background:var(--danger-bg);color:var(--danger);display:grid;place-items:center}.confirm-dialog h3{font-size:18px;margin:18px 0 10px}.confirm-dialog p{white-space:pre-line;max-height:40vh;overflow:auto;font-size:14px;line-height:1.7;overflow-wrap:anywhere;margin:0}.confirm-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:24px}button{padding:9px 18px;border-radius:var(--radius-sm);border:1px solid var(--border);background:var(--surface);color:inherit;cursor:pointer;font:inherit;font-size:14px}button.danger{background:var(--danger);color:var(--surface);border-color:var(--danger)}button:disabled{opacity:.6;cursor:wait}
</style>

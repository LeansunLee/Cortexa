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
.confirm-backdrop{position:fixed;inset:0;background:var(--overlay);z-index:4000;display:grid;place-items:center;padding:20px;backdrop-filter:blur(3px)}
.confirm-dialog{background:var(--surface,#fff);color:var(--text,#334155);border:1px solid var(--border,#e2e8f0);border-radius:18px;padding:28px;width:420px;max-width:100%;box-shadow:0 24px 70px #0003;box-sizing:border-box}
.danger-icon{width:48px;height:48px;border-radius:14px;background:#ef444418;color:#ef4444;display:grid;place-items:center}.confirm-dialog h3{font-size:18px;margin:18px 0 10px}.confirm-dialog p{white-space:pre-line;max-height:40vh;overflow:auto;font-size:14px;line-height:1.7;overflow-wrap:anywhere;margin:0}.confirm-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:24px}button{padding:9px 18px;border-radius:8px;border:1px solid var(--border,#ddd);background:var(--surface,#fff);color:inherit;cursor:pointer;font:inherit;font-size:14px}button.danger{background:#dc2626;color:#fff;border-color:#dc2626}button:disabled{opacity:.6;cursor:wait}
</style>

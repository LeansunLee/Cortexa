<template>
  <Teleport v-if="pageActive" to="body">
    <div class="modal-overlay memory-overlay" @click.self="close">
      <section ref="dialog" class="modal memory-dialog" role="dialog" aria-modal="true" :aria-labelledby="titleId" tabindex="-1">
        <header class="modal-header">
          <h3 :id="titleId">{{ title }}</h3>
          <button type="button" class="modal-close" :disabled="busy" aria-label="关闭弹窗" @click="close"><X :size="20" /></button>
        </header>
        <div class="modal-body"><p v-if="error" class="dialog-error" role="alert">{{ error }}</p><slot /></div>
        <footer v-if="$slots.footer" class="modal-footer"><slot name="footer" /></footer>
      </section>
    </div>
  </Teleport>
</template>
<script>
const scrollLocks = new Set()
let unlockedOverflow = ''
</script>
<script setup>
import { computed, inject, nextTick, onBeforeUnmount, ref, unref, useId, watch } from 'vue'
import { X } from 'lucide-vue-next'
const props = defineProps({ title: String, busy: Boolean, error: String })
const emit = defineEmits(['close'])
const active = inject('pageTabActive', true)
const pageActive = computed(() => unref(active))
const dialog = ref(null), titleId = useId()
const returnFocus = document.activeElement
const lockId = Symbol('memory-dialog')
function lockScroll() {
  if (!scrollLocks.size) unlockedOverflow = document.body.style.overflow
  scrollLocks.add(lockId)
  document.body.style.overflow = 'hidden'
}
function unlockScroll() {
  if (!scrollLocks.delete(lockId)) return
  if (!scrollLocks.size) document.body.style.overflow = unlockedOverflow
}
const focusable = () => [...(dialog.value?.querySelectorAll('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href],summary,[tabindex="0"]') || [])].filter(el => el.getClientRects().length)
function close() { if (!props.busy) emit('close') }
function keydown(event) {
  if (!pageActive.value || event.defaultPrevented) return
  if (event.key === 'Escape') { event.preventDefault(); close() }
  if (event.key !== 'Tab') return
  const nodes = focusable(), first = nodes[0], last = nodes.at(-1)
  if (!first) { event.preventDefault(); dialog.value?.focus(); return }
  if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.value)) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
function focusin(event) {
  if (!pageActive.value || !dialog.value || dialog.value.contains(event.target) || event.target.closest('.search-select-menu')) return
  dialog.value.focus()
}
watch(pageActive, async value => {
  if (value) {
    lockScroll()
    await nextTick()
    dialog.value?.focus()
  } else unlockScroll()
}, { immediate: true })
document.addEventListener('keydown', keydown)
document.addEventListener('focusin', focusin)
onBeforeUnmount(() => {
  document.removeEventListener('keydown', keydown)
  document.removeEventListener('focusin', focusin)
  unlockScroll()
  if (pageActive.value && returnFocus?.isConnected) nextTick(() => returnFocus.focus())
})
</script>
<style scoped>
.memory-overlay { padding: 20px; z-index: 2600; background: var(--overlay, rgba(0,0,0,.5)); }
.memory-dialog { display: flex; flex-direction: column; width: 720px; max-width: 100%; max-height: calc(100dvh - 40px); overflow: hidden; border: 1px solid var(--border); color: var(--text); }
.memory-dialog:focus { outline: none; }
.modal-header, .modal-footer { flex-shrink: 0; }
.modal-body { overflow-y: auto; min-height: 0; }
.modal-footer { flex-wrap: wrap; }
.modal-close { display: flex; align-items: center; justify-content: center; }
.dialog-error { color: var(--danger); margin: 0 0 16px; font-size: 13px; }
@media(max-width:640px) {
  .memory-overlay { padding: 12px; }
  .memory-dialog { max-height: calc(100dvh - 24px); }
  .modal-header, .modal-body, .modal-footer { padding: 16px; }
}
</style>

<template>
  <button ref="trigger" type="button" class="memory-help" :aria-label="label + '说明'" :aria-describedby="opened ? tipId : undefined" @mouseenter="show" @mouseleave="opened=false" @focus="show" @blur="opened=false" @click="show" @keydown.esc.stop.prevent="opened=false"><CircleHelp :size="16" /></button>
  <Teleport to="body">
    <span v-if="opened" :id="tipId" role="tooltip" class="memory-help-tooltip" :style="position">{{ text }}</span>
  </Teleport>
</template>
<script setup>
import { onBeforeUnmount, ref, useId } from 'vue'
import { CircleHelp } from 'lucide-vue-next'
const props = defineProps({ label: String, text: String })
const opened = ref(false), trigger = ref(null), position = ref({}), tipId = useId()
function show() {
  const rect = trigger.value.getBoundingClientRect()
  const width = Math.min(280, window.innerWidth - 32)
  position.value = { width: width+'px', left: Math.max(16, Math.min(rect.right-width, window.innerWidth-width-16))+'px', ...(window.innerHeight-rect.bottom > 130 ? { top: rect.bottom+8+'px' } : { bottom: window.innerHeight-rect.top+8+'px' }) }
  opened.value = true
}
function hide() { opened.value = false }
window.addEventListener('scroll', hide, true)
window.addEventListener('resize', hide)
onBeforeUnmount(() => { window.removeEventListener('scroll', hide, true); window.removeEventListener('resize', hide) })
</script>
<style scoped>
.memory-help { flex: none; display: inline-flex; justify-content: center; align-items: center; width: 28px; height: 32px; padding: 0; border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--text3); cursor: help; }
.memory-help:hover, .memory-help:focus-visible { color: var(--primary); background: var(--primary-light); }
.memory-help-tooltip { position: fixed; z-index: 5100; box-sizing: border-box; padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface); color: var(--text2); box-shadow: 0 8px 28px color-mix(in srgb, var(--text) 15%, transparent); font-size: 12px; line-height: 1.7; pointer-events: none; }
</style>

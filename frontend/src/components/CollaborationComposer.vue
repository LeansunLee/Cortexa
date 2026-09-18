<template>
  <section v-if="drafts.length" class="collaboration-composer" aria-label="协作任务，按从左到右执行">
    <div v-for="(draft, index) in drafts" :key="draft.agent_id" class="agent-chip">
      <span class="chip-order">{{ index + 1 }}</span>
      <label class="chip-name" :for="'task-' + draft.agent_id" :title="draft.name">{{ draft.name }}</label>
      <span class="chip-input-wrap">
        <span class="chip-input-measure" aria-hidden="true">{{ draft.task || '输入协作任务' }}</span>
      <input
        :ref="el => { if (el) taskInputs[draft.agent_id] = el; else delete taskInputs[draft.agent_id] }"
        :id="'task-' + draft.agent_id" class="chip-input" type="text"
        :value="draft.task" :disabled="disabled" :aria-label="'给' + draft.name + '的协作任务'"
        placeholder="输入协作任务" :title="draft.task || '只输入给该 Agent 的任务；Enter 返回主输入框'"
        @input="$emit('update', draft.agent_id, { task: $event.target.value, dirty: true, basedOn: input })"
        @keydown="handleKey"
      />
      </span>
      <span class="context-policy" :title="draft.agent_type === 'proxy' ? 'Proxy：只发送本轮任务和补充提示词，不携带上下文' : 'LLM：自动携带最近对话及本轮前面 Agent 的成功输出，以本轮任务为准'">{{ draft.agent_type === 'proxy' ? 'Proxy · 仅任务' : 'LLM · 带上下文' }}</span>
      <div class="chip-controls">
        <button type="button" :disabled="disabled || index === 0" :aria-label="'向左移动' + draft.name" title="提前执行" @click="$emit('move', draft.agent_id, -1)">‹</button>
        <button type="button" :disabled="disabled || index === drafts.length - 1" :aria-label="'向右移动' + draft.name" title="延后执行" @click="$emit('move', draft.agent_id, 1)">›</button>
        <button type="button" :disabled="disabled" :aria-label="'移除' + draft.name" title="移除协作" @click="$emit('remove', draft)">×</button>
      </div>
    </div>

  </section>
</template>
<script setup>
import { nextTick } from 'vue'
const props = defineProps({ drafts: Array, input: String, conversationId: String, disabled: Boolean })
const emit = defineEmits(['update', 'remove', 'move', 'finish'])
const taskInputs = {}
async function focusTask(id) {
  if (props.disabled) return
  await nextTick()
  const element = taskInputs[id]
  element?.focus()
  if (element) element.selectionStart = element.selectionEnd = element.value?.length || 0
}
function handleKey(event) {
  if (event.isComposing || event.keyCode === 229) return
  if (event.key === 'Enter' || event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    emit('finish')
  }
}
defineExpose({ focusTask })
</script>
<style scoped>
.collaboration-composer{display:flex;gap:7px;overflow-x:auto;width:100%;min-width:0;padding:8px 2px;scrollbar-width:thin;box-sizing:border-box}
.agent-chip{display:flex;align-items:center;gap:6px;flex:0 0 auto;max-width:100%;box-sizing:border-box;padding:5px 5px 5px 9px;border:1px solid color-mix(in srgb,var(--primary) 35%,var(--border));border-radius:10px;background:color-mix(in srgb,var(--primary) 10%,var(--surface));color:var(--primary);transition:background .15s,border-color .15s}
.agent-chip:focus-within{background:color-mix(in srgb,var(--primary) 16%,var(--surface));border-color:var(--primary)}
.chip-order{font-size:10px;opacity:.7}.chip-name{font-size:12px;font-weight:600;max-width:90px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:text;flex-shrink:0}
.chip-input-wrap{position:relative;display:block;flex:0 1 auto;min-width:36px;max-width:480px;overflow:hidden}
.chip-input-measure{display:block;visibility:hidden;white-space:pre;padding:4px 9px;font:inherit;font-size:12px;line-height:20px}
.chip-input{position:absolute;inset:0;display:block;box-sizing:border-box;width:100%;min-width:0;padding:4px 5px;border:0;border-radius:4px;outline:none;background:transparent;box-shadow:none;color:var(--primary);font:inherit;font-size:12px;line-height:20px}
.chip-input::placeholder{color:var(--primary);opacity:.65}.chip-input:focus{background:color-mix(in srgb,var(--surface) 55%,transparent)}
.chip-controls{display:flex;flex-shrink:0}.chip-controls button{border:0;background:transparent;color:var(--primary);padding:2px;width:22px;height:26px;font:inherit;font-size:17px;line-height:22px;border-radius:5px;cursor:pointer}
.chip-controls button:hover:enabled{background:color-mix(in srgb,var(--primary) 12%,transparent)}button:disabled,input:disabled{opacity:.35;cursor:default}
@media(max-width:600px){.chip-name{max-width:70px}.agent-chip{gap:4px}.chip-controls button{width:20px}}
</style>

<style scoped>
.context-policy {font-size:10px;white-space:nowrap;opacity:.75;flex-shrink:0}
</style>

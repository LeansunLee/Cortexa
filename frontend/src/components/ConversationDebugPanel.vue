<template>
  <aside class="debug-panel" aria-label="对话调试窗口">
    <header class="debug-header">
      <div>
        <div class="debug-title"><Bug :size="16" />调试窗口</div>
        <div class="debug-subtitle">上下文、检索与协作传递</div>
      </div>
      <button class="debug-close" type="button" title="关闭调试窗口" aria-label="关闭调试窗口" @click="$emit('close')">
        <X :size="17" />
      </button>
    </header>

    <div v-if="rounds.length" class="debug-round-select">
      <label for="debug-round">对话轮次</label>
      <SearchSelect
        id="debug-round"
        v-model="selectedId"
        :options="roundOptions"
        placeholder="选择对话轮次"
        aria-label="对话轮次"
      />
    </div>

    <div v-if="selectedRound" class="debug-body">
      <div class="debug-round-meta">
        <span>{{ selectedRound.entries.length }} 个事件</span>
        <span v-if="selectedRound.isLive" class="live-badge"><i></i>实时更新</span>
        <span v-else>{{ formatTime(selectedRound.createdAt) }}</span>
      </div>

      <div v-if="!selectedRound.entries.length" class="debug-empty">正在等待调试事件…</div>
      <ol v-else class="debug-timeline">
        <li v-for="entry in selectedRound.entries" :key="entry.seq" :class="['debug-event', `status-${entry.status || 'info'}`]">
          <span class="event-dot"></span>
          <div class="event-card">
            <div class="event-heading">
              <span class="event-stage">{{ stageLabel(entry.stage) }}</span>
              <time>{{ formatEventTime(entry.timestamp) }}</time>
            </div>
            <div class="event-title">{{ entry.title }}</div>
            <div v-if="entry.summary" class="event-summary">{{ entry.summary }}</div>
            <details v-if="hasDetail(entry.detail)" class="event-detail">
              <summary>查看传递内容</summary>
              <pre>{{ formatDetail(entry.detail) }}</pre>
            </details>
          </div>
        </li>
      </ol>
    </div>
    <div v-else class="debug-empty debug-empty-main">
      <Bug :size="22" />
      <span>该对话还没有可查看的调试记录</span>
      <small>开启功能后产生的新对话轮次会保留轨迹</small>
    </div>
  </aside>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Bug, X } from 'lucide-vue-next'

const props = defineProps({
  rounds: { type: Array, default: () => [] },
})
defineEmits(['close'])

const selectedId = ref('')
const selectedRound = computed(() =>
  props.rounds.find(round => round.id === selectedId.value) || props.rounds.at(-1) || null
)
const roundOptions = computed(() => props.rounds.map(round => ({
  value: round.id,
  label: (round.isLive ? '实时 · ' : '') + round.label,
})))

watch(() => props.rounds.map(round => `${round.id}:${round.entries.length}:${round.isLive}`).join('|'), () => {
  const live = props.rounds.find(round => round.isLive)
  if (live) selectedId.value = live.id
  else if (!props.rounds.some(round => round.id === selectedId.value)) selectedId.value = props.rounds.at(-1)?.id || ''
}, { immediate: true })

const labels = {
  round: '轮次', agent: 'Agent', retrieval: '检索计划', knowledge: '知识库', memory: '记忆',
  attachment: '附件', collaboration: '协作', capability: '工具能力', context: '上下文', tool: '工具调用',
  proxy: 'Proxy', response: '生成回复',
}
const stageLabel = stage => labels[stage] || stage || '过程'
const hasDetail = detail => detail && typeof detail === 'object' && Object.keys(detail).length > 0
const formatDetail = detail => JSON.stringify(detail, null, 2)
const formatEventTime = value => value ? new Date(value).toLocaleTimeString('zh-CN', { hour12: false }) : ''
const formatTime = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '历史记录'
</script>

<style scoped>
.debug-panel {
  width: 390px; min-width: 320px; max-width: 42%; min-height: 0;
  display: flex; flex-direction: column; background: var(--surface); border-left: 1px solid var(--border);
}
.debug-header { display: flex; align-items: flex-start; justify-content: space-between; padding: 15px 16px 13px; border-bottom: 1px solid var(--border); }
.debug-title { display: flex; align-items: center; gap: 7px; color: var(--text); font-size: 14px; font-weight: 650; }
.debug-subtitle { margin-top: 3px; color: var(--text3); font-size: 11px; }
.debug-close { width: 30px; height: 30px; display: grid; place-items: center; border: 0; border-radius: 7px; background: transparent; color: var(--text3); cursor: pointer; }
.debug-close:hover { color: var(--text); background: var(--surface2); }
.debug-round-select { padding: 12px 16px; border-bottom: 1px solid var(--border); }
.debug-round-select label { display: block; margin-bottom: 5px; color: var(--text3); font-size: 11px; }
.debug-round-select :deep(.search-select-trigger) { min-height: 34px; padding: 7px 9px; border-radius: 7px; background: var(--surface2); font-size: 12px; }
.debug-body { flex: 1; min-height: 0; overflow-y: auto; padding: 13px 14px 20px; }
.debug-round-meta { display: flex; justify-content: space-between; align-items: center; margin: 0 2px 12px; color: var(--text3); font-size: 11px; }
.live-badge { display: inline-flex; align-items: center; gap: 5px; color: var(--success); }
.live-badge i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; animation: debug-pulse 1.2s infinite; }
@keyframes debug-pulse { 50% { opacity: .3; } }
.debug-timeline { list-style: none; padding: 0 0 0 13px; margin: 0; border-left: 1px solid var(--border); }
.debug-event { position: relative; margin: 0 0 12px 0; padding-left: 13px; }
.event-dot { position: absolute; left: -17px; top: 11px; width: 7px; height: 7px; border-radius: 50%; background: var(--text3); box-shadow: 0 0 0 3px var(--surface); }
.status-running .event-dot { background: var(--primary); }
.status-success .event-dot { background: var(--success); }
.status-error .event-dot { background: var(--danger); }
.status-empty .event-dot, .status-skipped .event-dot { background: var(--text3); }
.event-card { padding: 10px 11px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface2); }
.event-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.event-stage { color: var(--primary); font-size: 10px; font-weight: 650; text-transform: uppercase; letter-spacing: .04em; }
.event-heading time { color: var(--text3); font-size: 10px; font-variant-numeric: tabular-nums; }
.event-title { margin-top: 5px; color: var(--text); font-size: 12px; font-weight: 600; }
.event-summary { margin-top: 4px; color: var(--text2); font-size: 11px; line-height: 1.55; overflow-wrap: anywhere; }
.event-detail { margin-top: 7px; }
.event-detail summary { color: var(--text3); cursor: pointer; font-size: 11px; }
.event-detail pre { max-height: 320px; overflow: auto; margin: 7px 0 0; padding: 9px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text2); font: 10px/1.55 'SFMono-Regular', Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.debug-empty { padding: 24px 12px; color: var(--text3); text-align: center; font-size: 12px; }
.debug-empty-main { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; }
.debug-empty-main small { max-width: 240px; line-height: 1.5; }
@media (max-width: 1000px) { .debug-panel { width: 340px; max-width: 48%; } }
@media (max-width: 760px) {
  .debug-panel { position: absolute; inset: 0 0 0 auto; z-index: 20; width: min(92vw, 390px); max-width: none; box-shadow: var(--shadow-md); }
}
</style>

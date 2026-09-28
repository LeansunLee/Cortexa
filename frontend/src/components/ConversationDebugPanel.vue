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

      <section v-if="runtimeInfo" class="runtime-budget-card" aria-label="Runtime Budget 运行预算">
        <div class="runtime-budget-title"><Gauge :size="16" /> Effective Runtime Policy <small>最终运行策略</small></div>
        <p><strong>Policy Source · 策略来源</strong> {{ runtimeInfo.collaborationSource }}</p>
        <p><strong>Collaboration Mode · 协作模式</strong> {{ runtimeInfo.mode }}</p>
        <p><strong>Budget State · 预算状态</strong> <b>{{ runtimeInfo.phase }}</b></p>
        <div class="runtime-budget-grid">
          <div v-for="field in runtimeFields" :key="field.key" class="runtime-budget-item">
            <span>{{ field.label }} <small>{{ field.zh }}</small></span>
            <strong>{{ runtimeInfo.consumed[field.key] ?? (field.key === 'duration' && runtimeInfo.limits.duration !== UNLIMITED_BUDGET ? runtimeInfo.limits.duration - (runtimeInfo.remaining.duration ?? runtimeInfo.limits.duration) : 0) }} / {{ formatBudgetValue(runtimeInfo.limits[field.key]) }}</strong>
            <small>{{ runtimeInfo.sources[field.key]?.source || 'Platform default' }} · Remaining {{ formatBudgetValue(runtimeInfo.remaining[field.key], runtimeInfo.limits[field.key]) }}</small>
          </div>
        </div>
        <p><strong>Finalization Reserve · 收尾保留</strong> {{ formatCompact(runtimeInfo.reserve) }}</p>
        <details v-if="runtimeInfo.allocations.length" class="runtime-extra">
          <summary>Child Budget Allocation · 子预算分配（{{ runtimeInfo.allocations.length }}）</summary>
          <pre>{{ formatDetail(runtimeInfo.allocations) }}</pre>
        </details>
        <div v-if="runtimeInfo.failure" class="runtime-budget-failure">
          <strong>Budget Failure · 预算失败</strong>
          <span>{{ runtimeInfo.failure.resource }}：{{ runtimeInfo.failure.current }} / {{ formatBudgetValue(runtimeInfo.failure.limit) }} · {{ runtimeInfo.failure.runtime }} · {{ runtimeInfo.failure.agent_id || '—' }} · {{ runtimeInfo.failure.phase }}</span>
        </div>
      </section>

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
            <div v-if="entry.detail?.memory_trace" class="memory-trace">
              <p>候选 {{ entry.detail.memory_trace.candidate_count || 0 }} 条 · 注入上下文 {{ entry.detail.memory_trace.injected_ids?.length || 0 }} 条 · {{ entry.detail.memory_trace.duration_ms || 0 }} ms</p>
              <p v-if="entry.detail.memory_trace.time?.historical">历史时间查询：{{ entry.detail.memory_trace.time.from }} 至 {{ entry.detail.memory_trace.time.to }}</p>
              <article v-for="m in entry.detail.memory_trace.candidates || []" :key="m.memory_id">
                <strong>{{ m.injected ? '已进入上下文' : '未注入' }} · {{ m.category }} · {{ m.kind || '未知类型' }}</strong>
                <small>{{ m.memory_id }}</small>
                <span>相关性 {{ m.relevance }} · 可信度 {{ m.confidence }} · 得分 {{ m.final_score }}</span>
                <span v-if="m.filter_reason">筛除原因：{{ m.filter_reason }}</span>
              </article>
            </div>
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
import { Bug, Gauge, X } from 'lucide-vue-next'

const props = defineProps({
  rounds: { type: Array, default: () => [] },
})
defineEmits(['close'])
const UNLIMITED_BUDGET = 1000000000000000
const formatBudgetValue = (value, limit = value) => limit === UNLIMITED_BUDGET ? '不限' : value ?? '—'

const selectedId = ref('')
const selectedRound = computed(() =>
  props.rounds.find(round => round.id === selectedId.value) || props.rounds.at(-1) || null
)
const roundOptions = computed(() => props.rounds.map(round => ({
  value: round.id,
  label: (round.isLive ? '实时 · ' : '') + round.label,
})))
const runtimeFields = [
  { key: 'duration', label: 'Duration', zh: '时长' },
  { key: 'llm_calls', label: 'LLM Calls', zh: '模型调用' },
  { key: 'tool_calls', label: 'Tool Calls', zh: '工具调用' },
  { key: 'tool_iterations', label: 'Tool Iterations', zh: '工具轮次' },
  { key: 'web_calls', label: 'Web Calls', zh: '网页调用' },
  { key: 'agent_calls', label: 'Agent Calls', zh: '协作调用' },
  { key: 'agent_depth', label: 'Agent Depth', zh: '协作层级' },
  { key: 'max_collaborators', label: 'Collaborators', zh: '参与者' },
  { key: 'max_steps', label: 'Goal Steps', zh: '目标步骤' },
  { key: 'max_replans', label: 'Replans', zh: '重规划' },
  { key: 'max_failures', label: 'Failures', zh: '失败次数' },
  { key: 'context_tokens', label: 'Context Tokens', zh: '上下文额度' },
  { key: 'output_tokens', label: 'Output Tokens', zh: '输出额度' },
]
const runtimeInfo = computed(() => {
  const entries = selectedRound.value?.entries?.filter(entry => entry.stage === 'runtime_goal') || []
  const policy = entries.find(entry => entry.detail?.policy_source && entry.detail?.limits)?.detail
  if (!policy) return null
  const latest = entries.at(-1)?.detail || policy
  const failure = entries.findLast(entry => entry.detail?.budget_failure)?.detail?.budget_failure
  return {
    limits: policy.limits,
    sources: policy.policy_source?.budget || {},
    collaborationSource: policy.policy_source?.collaboration?.source || 'Platform default',
    mode: policy.collaboration_mode || 'EXPLICIT_ONLY',
    phase: latest.budget_phase || 'NORMAL',
    consumed: latest.consumed_budget || {},
    remaining: latest.remaining_budget || {},
    reserve: latest.finalization_reserve || {},
    failure,
    allocations: entries.filter(entry => entry.title === 'Child Budget Allocation' || entry.title === 'Child Budget Result').map(entry => ({ event: entry.title, ...entry.detail })),
  }
})
const formatCompact = value => Object.entries(value || {}).map(([key, amount]) => `${key}: ${amount}`).join(' · ')

watch(() => props.rounds.map(round => `${round.id}:${round.entries.length}:${round.isLive}`).join('|'), () => {
  const live = props.rounds.find(round => round.isLive)
  if (live) selectedId.value = live.id
  else if (!props.rounds.some(round => round.id === selectedId.value)) selectedId.value = props.rounds.at(-1)?.id || ''
}, { immediate: true })

const labels = {
  round: '轮次', agent: 'Agent', retrieval: '检索计划', knowledge: '知识库', memory: '记忆',
  attachment: '附件', collaboration: '协作', capability: '工具能力', context: '上下文', tool: '工具调用',
  proxy: 'Proxy', response: '生成回复', runtime_goal: '目标执行', goal_shadow: '目标识别', capability_shadow: '能力匹配',
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
.runtime-budget-card { margin-bottom: 15px; padding: 11px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface2); font-size: 11px; color: var(--text2); }
.runtime-budget-title { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 700; color: var(--text); }
.runtime-budget-title small, .runtime-budget-item small { color: var(--text3); font-size: 10px; font-weight: 400; }
.runtime-budget-card p { margin: 8px 0; overflow-wrap: anywhere; }
.runtime-budget-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; margin: 10px 0; }
.runtime-budget-item { display: grid; gap: 3px; padding: 7px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); }
.runtime-budget-item span { color: var(--text); font-weight: 600; }
.runtime-budget-item strong { font-variant-numeric: tabular-nums; }
.runtime-extra pre { max-height: 220px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 10px; }
.runtime-budget-failure { display: grid; gap: 5px; color: var(--danger); padding: 8px; border: 1px solid var(--danger); border-radius: 6px; }
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
.memory-trace {font-size:11px;overflow-wrap:anywhere;color:var(--text2)}
.memory-trace article{display:grid;gap:4px;border-top:1px solid var(--border);padding:8px 0}
.memory-trace small{color:var(--text3)}
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

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

      <section v-if="executionBranches.length" class="inspector-section branch-section" aria-label="执行分支">
        <div class="inspector-heading"><span>执行分支</span><small>{{ executionBranches.length }} 个判断</small></div>
        <div class="branch-list">
          <article v-for="branch in executionBranches" :key="branch.key" :class="['branch-item', `branch-${branch.status}`]">
            <span class="branch-marker" aria-hidden="true"></span>
            <div class="branch-copy">
              <strong>{{ branch.label }}</strong>
              <span>{{ branch.value }}</span>
              <small v-if="branch.note">{{ branch.note }}</small>
            </div>
            <span class="branch-state">{{ branch.statusLabel }}</span>
          </article>
        </div>
      </section>

      <section v-if="contextSnapshots.length" class="inspector-section context-section" aria-label="模型与协作上下文">
        <div class="inspector-heading"><span>上下文快照</span><small>{{ contextSnapshots.length }} 组</small></div>
        <details v-for="snapshot in contextSnapshots" :key="snapshot.key" class="context-snapshot" :open="snapshot.kind === 'model'">
          <summary>
            <span>{{ snapshot.title }}</span>
            <small>{{ snapshot.caption }}</small>
          </summary>
          <div v-if="snapshot.messages?.length" class="context-messages">
            <article v-for="(message, index) in snapshot.messages" :key="`${snapshot.key}-${index}`" :class="['context-message', `role-${message.role || 'other'}`]">
              <div><strong>{{ roleLabel(message.role) }}</strong><small>{{ message.name || message.type || `第 ${index + 1} 条` }}</small></div>
              <pre>{{ contextText(message.content) }}</pre>
            </article>
          </div>
          <pre v-else class="context-raw">{{ formatDetail(snapshot.content) }}</pre>
        </details>
      </section>

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
const executionBranches = computed(() => {
  const entries = selectedRound.value?.entries || []
  const latest = (stage, predicate = () => true) => entries.findLast(entry => entry.stage === stage && predicate(entry))
  const branches = []
  const goal = latest('goal')
  const route = goal?.detail?.route
  if (route) branches.push({
    key: 'route', label: '目标路由', value: route.route || route.proposed_route || '未路由',
    note: goal.detail.execution === 'LEGACY_UNCHANGED' ? '影子判定；本轮仍按现有对话流程执行' : '',
    status: route.route === 'direct' ? 'neutral' : 'selected', statusLabel: '已判定',
  })

  const retrieval = latest('retrieval')
  if (retrieval) {
    const d = retrieval.detail || {}
    branches.push({ key: 'retrieval', label: '检索策略', value: retrieval.summary || '已制定',
      note: `知识库 ${boolLabel(d.knowledge)} · 记忆 ${boolLabel(d.memory)} · 网页 ${boolLabel(d.web)}`,
      status: 'selected', statusLabel: '已判定' })
  }
  for (const [stage, label] of [['knowledge', '知识库检索'], ['memory', '长期记忆']]) {
    const decision = latest(stage, e => e.status !== 'running') || latest(stage)
    if (decision) branches.push({ key: stage, label, value: decision.title, note: decision.summary,
      status: statusKind(decision.status), statusLabel: statusLabel(decision.status) })
    else if (retrieval?.detail?.[stage === 'knowledge' ? 'knowledge' : 'memory']) branches.push({
      key: stage, label, value: '计划检索，尚无结果事件', status: 'pending', statusLabel: '等待中',
    })
  }

  const mentions = latest('retrieval')?.detail?.has_collaboration
  const collabEntries = entries.filter(entry => entry.stage === 'collaboration')
  if (mentions !== undefined || collabEntries.length) {
    const targets = [...new Set(collabEntries.map(e => e.detail?.target_agent?.name).filter(Boolean))]
    const outcome = collabEntries.at(-1)
    branches.push({ key: 'collaboration', label: 'Agent 协作',
      value: targets.length ? `涉及 ${targets.join('、')}` : mentions ? '检测到协作意图' : '未触发协作',
      note: outcome?.summary || (mentions ? '检查协作事件获取匹配与传递详情' : ''),
      status: collabEntries.length ? statusKind(outcome?.status) : mentions ? 'pending' : 'neutral',
      statusLabel: collabEntries.length ? statusLabel(outcome?.status) : mentions ? '已识别' : '未触发' })
  }
  const toolCalls = entries.filter(entry => entry.stage === 'tool' && entry.title?.startsWith('调用工具'))
  const capability = latest('capability')
  if (capability || toolCalls.length) branches.push({
    key: 'tools', label: '业务工具',
    value: toolCalls.length ? `调用 ${toolCalls.length} 次工具` : '未调用工具',
    note: capability?.summary || '', status: toolCalls.length ? 'selected' : 'neutral',
    statusLabel: toolCalls.length ? '已执行' : '未触发',
  })
  return branches
})
const contextSnapshots = computed(() => {
  const entries = selectedRound.value?.entries || []
  const snapshots = []
  for (const entry of entries) {
    const detail = entry.detail || {}
    if (Array.isArray(detail.messages_sent_to_model)) snapshots.push({
      key: `model-${entry.seq}`, kind: 'model', title: '主 Agent → 模型',
      caption: `${detail.messages_sent_to_model.length} 条消息 · ${entry.summary || ''}`,
      messages: detail.messages_sent_to_model,
    })
    if (detail.target_agent && (detail.background_context || detail.dependency_results || detail.task)) {
      snapshots.push({
        key: `collab-${entry.seq}`, kind: 'collaboration',
        title: `${detail.source_agent?.name || '主 Agent'} → ${detail.target_agent.name || '协作 Agent'}`,
        caption: detail.task || entry.summary || '协作输入',
        messages: [
          { role: 'user', name: '任务', content: detail.question || detail.task },
          { role: 'context', name: '背景上下文', content: detail.background_context },
          { role: 'context', name: '前置协作结果', content: detail.dependency_results },
        ].filter(item => item.content != null && item.content !== ''),
      })
    }
    if (detail.conversation_context && entry.title?.includes('Proxy')) snapshots.push({
      key: `proxy-${entry.seq}`, kind: 'collaboration', title: '对话 → Proxy Agent',
      caption: `${Array.isArray(detail.conversation_context) ? detail.conversation_context.length : 1} 个上下文片段`,
      content: { current_task: detail.current_task, conversation_context: detail.conversation_context },
    })
  }
  return snapshots
})
const formatCompact = value => Object.entries(value || {}).map(([key, amount]) => `${key}: ${amount}`).join(' · ')
const boolLabel = value => value ? '启用' : '跳过'
const statusKind = status => ({ success: 'selected', error: 'error', skipped: 'neutral', empty: 'neutral', running: 'pending', info: 'neutral' }[status] || 'neutral')
const statusLabel = status => ({ success: '完成', error: '失败', skipped: '跳过', empty: '无结果', running: '进行中', info: '记录' }[status] || '记录')
const roleLabel = role => ({ system: '系统提示', user: '用户消息', assistant: '模型回复', tool: '工具结果', context: '上下文' }[role] || role || '其他')
const contextText = value => typeof value === 'string' ? value : formatDetail(value)

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
.inspector-section { margin: 0 0 15px; padding: 11px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface2); }
.inspector-heading { display: flex; justify-content: space-between; align-items: center; margin-bottom: 9px; color: var(--text); font-size: 12px; font-weight: 700; }
.inspector-heading small { color: var(--text3); font-size: 10px; font-weight: 400; }
.branch-list { display: grid; gap: 7px; }
.branch-item { display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; align-items: start; gap: 8px; padding: 8px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface); }
.branch-marker { width: 7px; height: 7px; margin-top: 4px; border-radius: 50%; background: var(--text3); }
.branch-selected .branch-marker { background: var(--success); }
.branch-error .branch-marker { background: var(--danger); }
.branch-pending .branch-marker { background: var(--primary); }
.branch-copy { display: grid; gap: 3px; min-width: 0; }
.branch-copy strong { color: var(--text); font-size: 11px; }
.branch-copy span, .branch-copy small { color: var(--text2); font-size: 10px; line-height: 1.45; overflow-wrap: anywhere; }
.branch-copy small { color: var(--text3); }
.branch-state { color: var(--text3); font-size: 9px; white-space: nowrap; }
.branch-selected .branch-state { color: var(--success); }
.branch-error .branch-state { color: var(--danger); }
.context-snapshot { margin-top: 7px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface); }
.context-snapshot > summary { display: grid; gap: 3px; padding: 9px; cursor: pointer; list-style-position: inside; color: var(--text); font-size: 11px; font-weight: 650; }
.context-snapshot > summary small { padding-left: 16px; color: var(--text3); font-size: 10px; font-weight: 400; overflow-wrap: anywhere; }
.context-messages { display: grid; gap: 7px; padding: 0 8px 8px; }
.context-message { min-width: 0; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
.context-message > div { display: flex; justify-content: space-between; gap: 7px; padding: 6px 7px; background: var(--surface2); font-size: 10px; }
.context-message > div strong { color: var(--primary); }
.context-message > div small { color: var(--text3); overflow-wrap: anywhere; text-align: right; }
.context-message pre, .context-raw { max-height: 240px; overflow: auto; margin: 0; padding: 8px; color: var(--text2); font: 10px/1.5 'SFMono-Regular', Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.context-raw { margin: 0 8px 8px; border: 1px solid var(--border); border-radius: 6px; }
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

<template>
  <details class="runtime-timeline" :open="live">
    <summary class="flow-header">
      <span class="flow-title"><Activity :size="16" /> {{ live ? '执行过程' : '执行记录' }}</span>
      <span class="flow-count">{{ steps.length }} 个步骤</span>
      <span class="flow-total">{{ reported.length ? `已报告 ${number(total)} Token` : live ? 'Token 等待返回' : '供应商未提供 Token 用量' }}</span>
    </summary>
    <div class="flow-body">
      <div v-if="goal" class="flow-goal"><Target :size="16" /><div><span class="flow-label">本次目标</span><p>{{ goal }}</p></div></div>
      <details v-if="reported.length" class="flow-usage">
        <summary>输入 {{ number(input) }} · 输出 {{ number(output) }} <span>查看各 Agent 消耗</span></summary>
        <div v-for="agent in agentUsage" :key="agent.key" class="usage-row"><span>{{ agent.name }}</span><span>输入 {{ number(agent.input) }} / 输出 {{ number(agent.output) }}</span><strong>{{ number(agent.total) }}</strong></div>
        <p v-if="reported.length < usage.length" class="flow-note">部分模型未返回用量；仅统计供应商已报告的 Token。</p>
      </details>
      <div v-if="notices.length" class="flow-budget" aria-label="本轮预算说明">
        <span class="flow-budget-title">本轮预算说明</span>
        <ul>
          <li v-for="item in notices" :key="item.field">
            {{ item.label }}：{{ number(item.used) }} / {{ number(item.limit) }} {{ item.unit }}。<template v-if="item.kind === 'limit'">已达到上限。</template><template v-else-if="item.kind === 'reserve'">剩余 {{ number(item.reserve) }} {{ item.unit }} 已预留给最终回复，停止新增执行。</template><template v-else>剩余预算不足以执行下一次调用<template v-if="item.requested">（需要 {{ number(item.requested) }} {{ item.unit }}）</template>。</template>
          </li>
        </ul>
      </div>
      <ol class="flow-list">
        <li v-for="(step, index) in steps" :key="index" :class="['flow-step', outcome(step, index)]">
          <span class="flow-node"><Loader v-if="outcome(step, index) === 'running'" :size="14" class="flow-spinner" /><AlertCircle v-else-if="outcome(step, index) === 'error'" :size="14" /><Check v-else :size="14" /></span>
          <div class="flow-step-body">
            <div class="flow-step-title"><span>{{ step.message }}</span>
              <DataResultTag v-if="step.tool && (step.data_result || /返回 \d+ 条数据；状态/.test(step.message || ''))" :action-id="step.tool" :conversation-id="conversationId" /><PromptTag v-for="prompt in canInspectPrompts ? step.prompts || [] : []" :key="prompt.id" :prompt="prompt" :conversation-id="conversationId" /><small v-if="step.usage?.token_count != null">{{ number(step.usage.token_count) }} Token</small></div>
            <div v-if="step.sources?.length" class="flow-sources">
              <button v-for="(source, i) in documents(step.sources)" :key="i" @click="$emit('source', source)" :title="[source.name || source.title, source.purpose].filter(Boolean).join(' · ')"><FileText :size="13" /><span>{{ source.name || source.title || (source.type === 'memory' ? '记忆来源' : '参考来源') }}</span><small v-if="source.evidence_grade">{{ { DIRECT:'直接证据', RELATED:'相关参考', BACKGROUND:'背景资料' }[source.evidence_grade] || source.evidence_grade }}</small></button>
            </div>
            <details v-if="step.draft" class="flow-draft" :open="live && index === steps.length - 1">
              <summary><MessageSquare :size="13" /> {{ step.agent_name || 'Agent' }} · {{ live ? '实时回复草稿' : '回复摘录' }}</summary>
              <div class="flow-draft-content" v-html="formatMessage(step.draft)"></div>
            </details>
          </div>
        </li>
      </ol>
    </div>
  </details>
</template>

<script setup>
import { computed } from 'vue'
import { Activity, Target, FileText, MessageSquare, Check, Loader, AlertCircle } from 'lucide-vue-next'
import PromptTag from './PromptTag.vue'
import DataResultTag from './DataResultTag.vue'
import { stepOutcome } from '../utils/statusSteps'
const props = defineProps({ steps: { type: Array, default: () => [] }, goal: { type: String, default: '' }, usage: { type: Array, default: () => [] }, notices: { type: Array, default: () => [] }, live: Boolean, conversationId: String, canInspectPrompts: Boolean, formatMessage: { type: Function, required: true } })
defineEmits(['source'])
const reported = computed(() => props.usage.filter(item => item.token_count != null))
const total = computed(() => reported.value.reduce((sum, item) => sum + item.token_count, 0))
const input = computed(() => reported.value.reduce((sum, item) => sum + (item.input_tokens || 0), 0))
const output = computed(() => reported.value.reduce((sum, item) => sum + (item.output_tokens || 0), 0))
const agentUsage = computed(() => {
  const groups = new Map()
  for (const item of reported.value) {
    const name = item.agent_name || 'Agent'
    const key = item.agent_id || name
    const group = groups.get(key) || { key, name, input: 0, output: 0, total: 0 }
    group.input += item.input_tokens || 0; group.output += item.output_tokens || 0; group.total += item.token_count
    groups.set(key, group)
  }
  return [...groups.values()]
})
const number = value => Number(value || 0).toLocaleString('zh-CN')
const outcome = (step, index) => stepOutcome(step, index, props.steps, props.live)
const documents = sources => [...new Map(sources.map((source, i) => [source.memory_id || source.document_id || source.url || `${source.name}:${i}`, source])).values()]
</script>

<style scoped>
.runtime-timeline { border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); overflow: hidden; margin-bottom: 12px; }
.flow-header { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 14px 18px; cursor: pointer; color: var(--text2); font-size: 12px; }
.flow-title { display: inline-flex; align-items: center; gap: 8px; color: var(--text); font-size: 14px; font-weight: 600; }
.flow-count { color: var(--text3); }
.flow-total { margin-left: auto; padding: 4px 9px; border-radius: 20px; background: var(--surface2); font-variant-numeric: tabular-nums; }
.flow-body { padding: 0 18px 18px; }
.flow-goal { display: flex; gap: 10px; padding: 12px; border-radius: 10px; background: var(--surface2); margin-bottom: 14px; }
.flow-goal svg { flex-shrink: 0; color: var(--primary); margin-top: 2px; }
.flow-label { font-size: 11px; color: var(--text3); }
.flow-goal p { margin: 4px 0 0; color: var(--text); font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
.flow-usage { margin-bottom: 16px; font-size: 12px; color: var(--text2); }
.flow-budget { margin-bottom: 16px; padding: 10px 12px; border: 1px solid color-mix(in srgb, var(--primary) 30%, var(--border)); border-radius: var(--radius-sm, 10px); background: color-mix(in srgb, var(--primary) 5%, var(--surface)); font-size: 12px; color: var(--text2); }
.flow-budget-title { display: block; font-weight: 600; color: var(--primary); margin-bottom: 4px; }
.flow-budget ul { list-style: none; margin: 0; padding: 0; }
.flow-budget li + li { margin-top: 3px; }
.flow-usage summary { cursor: pointer; }.flow-usage summary span { color: var(--text3); margin-left: 8px; }
.usage-row { display: flex; flex-wrap: wrap; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--border); }.usage-row strong { margin-left: auto; }
.flow-note { color: var(--text3); font-size: 11px; }
.flow-list { list-style: none; padding: 0; margin: 0; }
.flow-step { position: relative; display: flex; gap: 12px; padding: 0 0 14px; }.flow-step:last-child { padding-bottom: 0; }
.flow-step:not(:last-child)::before { content: ''; position: absolute; left: 10px; top: 23px; bottom: 0; width: 1px; background: var(--border); }
.flow-node { width: 21px; height: 21px; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; border-radius: 50%; color: var(--success); background: var(--surface2); }
.flow-step.running .flow-node { color: var(--primary); }.flow-step.error .flow-node { color: var(--danger); }
.flow-step-body { flex: 1; min-width: 0; }.flow-step-title { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px; color: var(--text2); font-size: 13px; line-height: 21px; }.flow-step.running .flow-step-title { color: var(--text); }
.flow-step-title small { margin-left: auto; font-size: 10px; white-space: nowrap; color: var(--text3); }
.flow-sources { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 7px; }
.flow-sources button { display: inline-flex; align-items: center; gap: 5px; max-width: 100%; border: 1px solid var(--border); border-radius: 6px; background: var(--surface2); color: var(--text2); padding: 5px 8px; font-size: 11px; cursor: pointer; }
.flow-sources button small { flex-shrink:0; color:var(--primary); font-size:10px; }
.flow-sources button span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.flow-sources button:hover { color: var(--primary); border-color: var(--primary); }
.flow-draft { margin-top: 8px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface2); }.flow-draft summary { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text3); cursor: pointer; }
.flow-draft-content { margin-top: 9px; font-size: 13px; line-height: 1.7; color: var(--text); overflow-x: auto; }
.flow-draft-content :deep(p) { margin: 6px 0; }.flow-draft-content :deep(table) { border-collapse: collapse; font-size: 12px; }.flow-draft-content :deep(td), .flow-draft-content :deep(th) { border: 1px solid var(--border); padding: 5px 8px; }
.flow-draft-content :deep(h1), .flow-draft-content :deep(h2), .flow-draft-content :deep(h3) { font-size: 14px; line-height: 1.5; margin: 12px 0 6px; }
.flow-spinner { animation: flow-spin 1s linear infinite; }@keyframes flow-spin { to { transform: rotate(360deg); } }@media (prefers-reduced-motion: reduce) { .flow-spinner { animation: none; } }
</style>

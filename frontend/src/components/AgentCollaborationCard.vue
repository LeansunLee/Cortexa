<template>
  <div class="collab-card" :class="{ expanded: isExpanded }" v-if="collabs.length > 0 || pendingCollabs.length > 0">
    <!-- Compact view: single line summary -->
    <button type="button" class="collab-summary" :aria-expanded="isExpanded" @click="isExpanded = !isExpanded">
      <div class="collab-summary-icon">
        <AppIcon name="Layers" :size="14" />
      </div>
      <div class="collab-summary-text">
        <template v-if="pendingCollabs.length > 0">
          正在协同 {{ pendingCollabs.map(c => c.agent_name || c.target_name).join('、') }}...
        </template>
        <template v-else-if="running">正在整理协作结果...</template>
        <template v-else-if="completedCollabs.length > 0">
          协作结束 · {{ completedCollabs.map(c => c.agent_name).join('、') }}
        </template>
      </div>
      <div class="collab-summary-meta" v-if="completedCollabs.length > 0">
        <span v-for="c in completedCollabs" :key="c.agent_name" class="collab-chip" :class="c.status">
          <span class="collab-chip-icon"><AppIcon :name="c.status === 'success' ? 'Check' : 'X'" :size="12" /></span>
          {{ c.agent_name }}
          <span v-if="c.duration_ms" class="collab-chip-time">{{ formatDuration(c.duration_ms) }}</span>
        </span>
      </div>
      <div class="collab-expand-arrow" :class="{ rotated: isExpanded }">
        <AppIcon name="ChevronDown" :size="12" />
      </div>
    </button>

    <!-- Pending collaboration animations -->
    <div v-if="pendingCollabs.length > 0 && !isExpanded" class="collab-pending-strip">
      <div v-for="p in pendingCollabs" :key="p.target_name || p.agent_name" class="collab-pending-item">
        <div class="collab-pending-avatar">
          <AgentAvatar v-if="isImagePath(p.target_agent_avatar)" :avatar="p.target_agent_avatar" class="collab-avatar-img" />
          <span v-else><AppIcon name="Bot" :size="20" /></span>
          <div class="collab-pending-spinner"></div>
        </div>
        <span class="collab-pending-text">{{ p.target_name || p.agent_name }} 协作中...</span>
      </div>
    </div>

    <!-- Expanded view: detailed flow -->
    <transition name="expand">
      <div v-if="isExpanded" class="collab-detail">
        <div class="collab-flow">
          <!-- Source agent -->
          <div class="flow-node source">
            <div class="flow-node-avatar">
              <AgentAvatar v-if="isImagePath(sourceAvatar)" :avatar="sourceAvatar" class="collab-avatar-img" />
              <span v-else><AppIcon name="Bot" :size="20" /></span>
            </div>
            <div class="flow-node-info">
              <span class="flow-node-label">{{ sourceName }}</span>
              <span class="flow-node-role">发起协作</span>
            </div>
          </div>

          <!-- Arrow down -->
          <div class="flow-arrow">
            <svg width="2" height="24" viewBox="0 0 2 24"><path d="M1 0V20M1 20L-1 18M1 20L3 18" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </div>

          <!-- Target agents -->
          <template v-for="c in allCollabs" :key="c.agent_name">
            <div class="flow-node target" :class="c.status || 'pending'">
              <div class="flow-node-avatar" :class="c.status">
                <AgentAvatar v-if="isImagePath(c.agent_avatar)" :avatar="c.agent_avatar" class="collab-avatar-img" />
                <span v-else><AppIcon name="Bot" :size="20" /></span>
                <div v-if="!c.status || c.status === 'pending'" class="flow-spinner"></div>
              </div>
              <div class="flow-node-info">
                <span class="flow-node-label">{{ c.agent_name }}</span>
                <span class="flow-node-role">{{ c.task || '协作任务' }}</span>
                <span v-if="c.status === 'success'" class="flow-node-time">
                  <AppIcon name="Check" :size="12" /> 已完成<span v-if="c.duration_ms"> · {{ formatDuration(c.duration_ms) }}</span>
                </span>
                <span v-else-if="c.status === 'failed'" class="flow-node-time error">
                  <AppIcon name="X" :size="12" /> {{ resultStatus(c) }}
                </span>
                <span v-else-if="c.status === 'timeout'" class="flow-node-time error">
                  <AppIcon name="Clock" :size="12" /> 协作超时
                </span>
                <span v-else-if="c.status === 'input_required'" class="flow-node-time warning">
                  <AppIcon name="AlertTriangle" :size="12" /> 等待补充参数
                </span>
                <span v-else class="flow-node-time pending">
                  <AppIcon name="Loader" :size="12" class="runtime-spinner" /> 进行中
                </span>
              </div>
            </div>

            <!-- Arrow back -->
            <div class="flow-arrow" v-if="c !== allCollabs.at(-1) || (!running && pendingCollabs.length === 0)">
              <svg width="2" height="24" viewBox="0 0 2 24"><path d="M1 0V20M1 20L-1 18M1 20L3 18" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </div>
          </template>

          <!-- Source agent again (synthesized) -->
          <div class="flow-node source synthesized" v-if="!running && pendingCollabs.length === 0 && completedCollabs.length > 0">
            <div class="flow-node-avatar">
              <AgentAvatar v-if="isImagePath(sourceAvatar)" :avatar="sourceAvatar" class="collab-avatar-img" />
              <span v-else><AppIcon name="Bot" :size="20" /></span>
            </div>
            <div class="flow-node-info">
              <span class="flow-node-label">{{ sourceName }}</span>
              <span class="flow-node-role">协作结束</span>
            </div>
          </div>
        </div>

        <!-- Result summaries -->
        <div v-if="completedCollabs.length > 0" class="collab-results">
          <div v-for="c in completedCollabs" :key="c.agent_name" class="collab-result-item" :class="{ 'has-error': c.status === 'failed' || c.status === 'timeout', 'needs-input': c.status === 'input_required' }" v-show="c.result || c.summary">
            <div class="result-header">
              <div class="result-avatar">
                <AgentAvatar v-if="isImagePath(c.agent_avatar)" :avatar="c.agent_avatar" class="collab-avatar-img" />
                <span v-else><AppIcon name="Bot" :size="20" /></span>
              </div>
              <span class="result-name">{{ c.agent_name }}</span>
              <span class="result-status" :class="c.status">{{ resultStatus(c) }}</span>
              <span v-if="c.background?.mode" class="result-mode">{{ backgroundLabel(c.background.mode) }}</span>
            </div>
            <div v-if="c.summary || c.background?.reason" class="result-text">{{ c.summary || c.background.reason }}</div>
            <div class="result-details">
              <details v-if="hasBackgroundDetails(c)" class="result-full">
                <summary>背景详情<AppIcon name="ChevronDown" :size="12" /></summary>
                <div class="result-detail-body">
                  <p v-if="c.background.reason && c.background.reason !== c.summary">{{ c.background.reason }}</p>
                  <div v-for="(fact, i) in c.background.facts" :key="i" class="result-fact"><small>{{ fact.source }}</small><pre>{{ fact.quote }}</pre></div>
                </div>
              </details>
              <details v-if="c.input_snapshot && Object.keys(c.input_snapshot).length" class="result-full" @toggle="loadInput(c, $event)">
                <summary>实际输入<AppIcon name="ChevronDown" :size="12" /></summary>
                <pre class="result-detail-body">{{ JSON.stringify(c.input_snapshot.snapshot_id ? (snapshots[c.input_snapshot.snapshot_id] || '正在读取快照…') : c.input_snapshot, null, 2) }}</pre>
              </details>
              <details v-if="c.result && c.result !== c.summary && c.result !== c.background?.reason" class="result-full">
                <summary>完整输出 <span class="result-count">{{ c.result.length }} 字符</span><AppIcon name="ChevronDown" :size="12" /></summary>
                <pre class="result-detail-body">{{ c.result }}</pre>
              </details>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import AgentAvatar from './AgentAvatar.vue'
import { ref, computed } from 'vue'
import { collaborationApi } from '../api/index.js'

const props = defineProps({
  collabs: { type: Array, default: () => [] },       // completed collabs from done event
  pendingCollabs: { type: Array, default: () => [] }, // in-progress collabs
  sourceName: { type: String, default: '' },
  sourceAvatar: { type: String, default: 'Bot' },
  running: { type: Boolean, default: false },
})

const isExpanded = ref(false)
const snapshots = ref({})
async function loadInput(c, event) {
  const value = c.input_snapshot
  if (!event.target.open && typeof snapshots.value[value?.snapshot_id] === 'string') delete snapshots.value[value.snapshot_id]
  if (!event.target.open || !value?.snapshot_id || snapshots.value[value.snapshot_id]) return
  try { snapshots.value[value.snapshot_id] = (await collaborationApi.inputSnapshot(value.conversation_id, value.snapshot_id)).data }
  catch { snapshots.value[value.snapshot_id] = '读取失败，请重新展开重试'; }
}

function backgroundLabel(mode) {
  return { conversation: 'LLM · 带上下文', auto: '背景 · 自动', none: 'Proxy · 仅任务', manual: '背景 · 指定' }[mode] || '背景'
}
function resultStatus(c) {
  if (c.status === 'success') return '已完成'
  if (c.status === 'timeout') return '已超时'
  if (c.status === 'input_required') return '等待补充参数'
  if (c.status === 'failed') return c.background?.status && c.background.status !== 'ready' || c.summary?.includes('本任务未执行') ? '未执行' : '协作失败'
  return '进行中'
}
function hasBackgroundDetails(c) {
  return c.background?.facts?.length || (c.background?.reason && c.background.reason !== c.summary)
}

function isImagePath(avatar) {
  return avatar && (avatar.startsWith('/') || avatar.startsWith('http'))
}

const completedCollabs = computed(() => props.collabs || [])
const allCollabs = computed(() => [...props.collabs, ...props.pendingCollabs]
  .map((collab, index) => ({ ...collab, order: collab.order ?? index }))
  .sort((left, right) => left.order - right.order))

function formatDuration(ms) {
  if (!ms) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
</script>

<style scoped>
.collab-card {
  margin: 8px 0;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface2);
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.collab-summary {
  display: flex;
  width: 100%;
  border: 0;
  background: transparent;
  text-align: left;
  font: inherit;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  cursor: pointer;
  transition: background 0.1s;
}

.collab-summary:hover {
  background: var(--surface2);
}

.collab-summary-icon {
  color: var(--accent, var(--primary));
  flex-shrink: 0;
}

.collab-summary-text {
  font-size: 13px;
  color: var(--text2);
  flex: 1;
}

.collab-summary-meta {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.collab-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
}

.collab-chip.success {
  background: var(--success-bg);
  color: var(--success);
}

.collab-chip.failed,
.collab-chip.timeout {
  background: var(--danger-bg);
  color: var(--danger);
}

.collab-chip-icon {
  font-size: 10px;
}

.collab-chip-time {
  font-size: 11px;
  opacity: 0.7;
}

.collab-expand-arrow {
  color: var(--text3);
  transition: transform 0.2s;
  flex-shrink: 0;
}

.collab-expand-arrow.rotated {
  transform: rotate(180deg);
}

/* Pending strip */
.collab-pending-strip {
  padding: 0 14px 10px;
  display: flex;
  gap: 12px;
}

.collab-pending-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.collab-pending-avatar {
  width: 24px;
  height: 24px;
  min-width: 24px;
  min-height: 24px;
  border-radius: 8px;
  background: var(--primary);
  background-image: var(--theme-gradient, none);
  color: var(--primary-text, #fff);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  position: relative;
  overflow: hidden;
  flex-shrink: 0;
}

.collab-pending-spinner {
  position: absolute;
  inset: -2px;
  border: 2px solid transparent;
  border-top-color: var(--accent, var(--primary));
  border-radius: 50%;
  animation: collabSpin 1s linear infinite;
}

.collab-pending-text {
  font-size: 12px;
  color: var(--accent, var(--primary));
  font-weight: 500;
}

@keyframes collabSpin {
  to { transform: rotate(360deg); }
}

/* Detail view */
.collab-detail {
  padding: 12px 16px 16px;
  border-top: 1px solid var(--border);
}

.collab-flow {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding-left: 4px;
}

.flow-node {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  max-width: 100%;
}

.flow-node.source {
  border-color: color-mix(in srgb, var(--primary) 25%, var(--border));
  background: var(--primary-light);
}

.flow-node.source.synthesized {
  border-color: color-mix(in srgb, var(--primary) 45%, var(--border));
  margin-top: 2px;
}

.flow-node-avatar {
  width: 28px;
  height: 28px;
  min-width: 28px;
  min-height: 28px;
  border-radius: 8px;
  background: var(--primary);
  background-image: var(--theme-gradient, none);
  color: var(--primary-text, #fff);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  flex-shrink: 0;
  position: relative;
  overflow: hidden;
}

.flow-node-avatar.success { background: linear-gradient(135deg, #22C55E 0%, #16A34A 100%); }
.flow-node-avatar.failed,
.flow-node-avatar.timeout { background: linear-gradient(135deg, #EF4444 0%, #DC2626 100%); }

.flow-spinner {
  position: absolute;
  inset: -2px;
  border: 2px solid transparent;
  border-top-color: var(--accent, var(--primary));
  border-radius: 50%;
  animation: collabSpin 1s linear infinite;
}

.flow-node-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.flow-node-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.flow-node-role {
  font-size: 12px;
  color: var(--text3);
}

.flow-node-time {
  font-size: 11px;
  color: #16A34A;
  margin-top: 2px;
}

.flow-node-time.error {
  color: #DC2626;
}
.flow-node-time.warning { color: var(--warning, #b45309); }

.flow-node-time.pending {
  color: var(--accent, var(--primary));
}

.flow-arrow {
  color: var(--border);
  display: flex;
  justify-content: center;
  padding-left: 16px;
}

/* Results */
.collab-results {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.collab-result-item {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
}

.result-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.result-avatar {
  font-size: 14px;
  width: 18px;
  height: 18px;
  min-width: 18px;
  min-height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-radius: 4px;
  flex-shrink: 0;
}

.result-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}

.result-text {
  font-size: 13px;
  color: var(--text2);
  line-height: 1.5;
  white-space: pre-wrap;
}

/* Expand transition */
.expand-enter-active,
.expand-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}
.collab-avatar-img {
  width: 100%;
  height: 100%;
  max-width: 100%;
  max-height: 100%;
  min-width: 0;
  min-height: 0;
  object-fit: cover;
  border-radius: inherit;
  display: block;
}

</style>

<style scoped>
.collab-result-item { min-width: 0; padding: 12px 14px; border-radius: 10px; }
.collab-result-item.has-error { border-color: color-mix(in srgb,var(--danger) 28%,var(--border)); background: var(--danger-bg); }
.collab-result-item.needs-input { border-color: color-mix(in srgb,#f59e0b 35%,var(--border)); background: color-mix(in srgb,#f59e0b 8%,var(--surface)); }
.result-header { gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.result-name { font-size: 13px; }
.result-status, .result-mode { font-size: 11px; line-height: 20px; border-radius: 5px; padding: 0 6px; font-weight: 500; }
.result-status { color: var(--text2); background: var(--surface2); }
.result-status.failed, .result-status.timeout { color: var(--danger); background: var(--danger-bg); }
.result-status.input_required { color: light-dark(#92400e,#fbbf24); background: color-mix(in srgb,#f59e0b 14%,transparent); }
.result-status.success { color: var(--success); background: var(--success-bg); }
.result-mode { margin-left: auto; color: var(--text3); background: var(--surface2); }
.result-text { font-size: 13px; line-height: 1.65; overflow-wrap: anywhere; }
.result-details { display: flex; flex-direction: column; gap: 6px; }
.result-details:has(> details) { margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border); }
.result-full { min-width: 0; font-size: 12px; line-height: 1.6; }
.result-full summary { display: flex; align-items: center; gap: 6px; width: fit-content; max-width: 100%; cursor: pointer; color: var(--text2); list-style: none; border-radius: 4px; padding: 2px 4px; margin-left: -4px; }
.result-full summary::-webkit-details-marker { display: none; }
.result-full summary:hover { color: var(--primary); background: var(--surface2); }
.result-full summary:focus-visible, .collab-summary:focus-visible { outline: 2px solid var(--primary); outline-offset: -2px; }
.result-full[open] > summary :deep(svg) { transform: rotate(180deg); }
.result-count { color: var(--text3); font-size: 11px; }
.result-full .result-detail-body { margin: 8px 0 2px; padding: 10px 12px; border-radius: 6px; background: var(--surface2); color: var(--text2); }
.result-full p { margin: 0; }
.result-full pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.65; margin: 4px 0 0; max-height: 360px; overflow: auto; }
.result-fact + .result-fact { margin-top: 10px; }
.result-fact small { color: var(--text3); }
@media (max-width: 640px) {
  .collab-summary { flex-wrap: wrap; gap: 6px; }
  .collab-summary-meta { flex-wrap: wrap; flex-shrink: 1; }
  .collab-detail { padding: 10px; }
  .result-mode { margin-left: 0; }
}
</style>

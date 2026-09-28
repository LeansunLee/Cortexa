<template>
  <Teleport v-if="pageTabActive" to="body">
    <div v-if="visible" class="mention-popover" :style="popoverStyle" ref="popoverRef">
      <div class="mention-popover-header">
        <span class="mention-popover-title">邀请 Agent 协作</span>
      </div>
      <div class="mention-popover-list" ref="listRef">
        <div v-if="loading" class="mention-popover-loading">
          <span class="mention-loading-dot"></span>
          <span>加载中...</span>
        </div>
        <div v-else-if="filteredAgents.length === 0" class="mention-popover-empty">
          <span>未找到匹配的智能体</span>
        </div>
        <div
          v-for="(agent, idx) in filteredAgents"
          :key="agent.id"
          :class="['mention-popover-item', { active: idx === activeIndex }]"
          @mouseenter="activeIndex = idx"
          @mousedown.prevent="selectAgent(agent)"
        >
          <div class="mention-agent-avatar">
            <AgentAvatar v-if="agent.avatar && agent.avatar.startsWith('/')" :avatar="agent.avatar" />
            <span v-else><AppIcon name="Bot" :size="20" /></span>
          </div>
          <div class="mention-agent-info">
            <div class="mention-agent-name">{{ agent.name }}</div>
            <div class="mention-agent-desc">{{ agent.role || agent.description || '智能体' }}</div>
          </div>
          <div class="mention-agent-status">
            <span class="status-dot online"></span>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { inject as injectPageTab } from 'vue'
const pageTabActive = injectPageTab('pageTabActive', true)

import AgentAvatar from './AgentAvatar.vue'
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { collaborationApi } from '../api/index.js'

const props = defineProps({
  visible: Boolean,
  query: { type: String, default: '' },
  position: { type: Object, default: () => ({ top: 0, left: 0 }) },
  excludeAgentId: { type: String, default: '' },
})

const emit = defineEmits(['select', 'close', 'state-update'])

const agents = ref([])
const loading = ref(false)
const activeIndex = ref(0)
const popoverRef = ref(null)
const listRef = ref(null)

const filteredAgents = computed(() => {
  if (!props.query) return agents.value
  const q = props.query.toLowerCase()
  return agents.value.filter(a =>
    a.name.toLowerCase().includes(q) ||
    (a.role && a.role.toLowerCase().includes(q)) ||
    (a.description && a.description.toLowerCase().includes(q))
  )
})

const popoverStyle = computed(() => ({
  position: 'fixed',
  bottom: props.position.bottom || '120px',
  left: props.position.left || '200px',
  zIndex: 9999,
}))

watch(() => props.visible, (val) => {
  if (val) {
    activeIndex.value = 0
    loadAgents()
  }
})

watch(() => props.query, () => {
  activeIndex.value = 0
  emitState()
})

watch(filteredAgents, () => {
  activeIndex.value = 0
  emitState()
})

watch(activeIndex, () => {
  emitState()
})

function emitState() {
  emit('state-update', {
    filteredAgents: filteredAgents.value,
    activeIndex: activeIndex.value,
  })
}

async function loadAgents() {
  loading.value = true
  try {
    const resp = await collaborationApi.listAgents(props.excludeAgentId)
    agents.value = resp.data || []
  } catch (e) {
    console.error('[Mention] Failed to load agents:', e)
    agents.value = []
  } finally {
    loading.value = false
  }
}

function selectAgent(agent) {
  emit('select', agent)
}

function handleKeydown(e) {
  if (!props.visible) return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    activeIndex.value = Math.min(activeIndex.value + 1, filteredAgents.value.length - 1)
    scrollToActive()
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIndex.value = Math.max(activeIndex.value - 1, 0)
    scrollToActive()
  } else if (e.key === 'Enter' && filteredAgents.value.length > 0) {
    e.preventDefault()
    selectAgent(filteredAgents.value[activeIndex.value])
  } else if (e.key === 'Escape') {
    emit('close')
  }
}

function scrollToActive() {
  if (listRef.value) {
    const activeEl = listRef.value.children[activeIndex.value]
    if (activeEl) activeEl.scrollIntoView({ block: 'nearest' })
  }
}

onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped>
.mention-popover {
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12), 0 2px 8px rgba(0, 0, 0, 0.06);
  width: 320px;
  max-height: 360px;
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  animation: mentionFadeIn 0.15s ease-out;
}

@keyframes mentionFadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.mention-popover-header {
  padding: 12px 16px 8px;
  border-bottom: 1px solid var(--border);
}

.mention-popover-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.mention-popover-list {
  overflow-y: auto;
  max-height: 300px;
  padding: 4px;
}

.mention-popover-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.1s;
}

.mention-popover-item:hover,
.mention-popover-item.active {
  background: var(--surface2);
}

.mention-agent-avatar {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: var(--navigation-background);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
  overflow: hidden;
}

.mention-agent-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.mention-agent-info {
  flex: 1;
  min-width: 0;
}

.mention-agent-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.3;
}

.mention-agent-desc {
  font-size: 12px;
  color: var(--text3);
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mention-agent-status {
  flex-shrink: 0;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.status-dot.online {
  background: var(--success);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--success) 20%, transparent);
}

.mention-popover-loading,
.mention-popover-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 16px;
  font-size: 13px;
  color: var(--text3);
}

.mention-loading-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary);
  animation: mentionPulse 1s ease-in-out infinite;
}

@keyframes mentionPulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 1; }
}
</style>

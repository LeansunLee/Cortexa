<template>
  <div v-if="settings.enabled" class="robot-assistant" :class="[`side-${settings.side}`, { collapsed: settings.collapsed }]"
       :style="rootStyle" data-testid="robot-assistant">
    <div class="robot-stage" ref="stage" role="button" tabindex="0"
         :aria-label="`AI 助手：${stateLabel}，点击打开快捷面板`"
         :title="stateLabel"
         @pointerdown="onPointerDown" @keydown.enter.prevent="panelOpen = !panelOpen" @keydown.space.prevent="panelOpen = !panelOpen">
      <RobotArt :state="currentState" :animations="animationsOn" :theme="theme" @art-error="fallback = true" />
      <div v-if="fallback" class="robot-fallback" aria-hidden="true">
        <Bot :size="settings.collapsed ? 18 : 30" />
      </div>
      <span v-if="activeCount" class="robot-badge">{{ activeCount > 9 ? '9+' : activeCount }}</span>
      <span class="robot-pulse" :data-state="controller?.faceState?.() || 'idle'" aria-hidden="true"></span>
    </div>
    <button class="robot-fold" type="button" :title="settings.collapsed ? '展开助手' : '收起助手'"
            :aria-label="settings.collapsed ? '展开助手' : '收起助手'" @click.stop="setCollapsed(!settings.collapsed)">
      <ChevronDown v-if="!settings.collapsed" :size="12" />
      <ChevronUp v-else :size="12" />
    </button>

    <TransitionGroup name="robot-bubble" tag="div" class="robot-bubbles">
      <button v-for="bubble in bubbles" :key="bubble.id" type="button" class="robot-bubble" :class="`bubble-${bubble.type}`"
              @click="openPanelFromBubble()" :aria-label="`通知：${bubble.title}`">
        <strong>{{ bubble.title }}</strong>
        <span>{{ bubble.body }}</span>
        <em v-if="bubble.count > 1">{{ bubble.count }} 条</em>
      </button>
    </TransitionGroup>

    <Transition name="robot-panel">
      <div v-if="panelOpen" class="robot-panel" role="dialog" aria-label="助手快捷面板" @pointerdown.stop>
        <div class="robot-panel-head">
          <strong>AI 助手</strong>
          <span class="robot-panel-state" :data-state="currentState">{{ stateLabel }}</span>
        </div>
        <div class="robot-panel-section">
          <span class="robot-panel-title">进行中的任务</span>
          <p v-if="!tasks.length" class="robot-panel-empty">当前没有正在执行的任务</p>
          <ul v-else class="robot-task-list">
            <li v-for="task in tasks" :key="task.id">
              <span class="robot-task-dot" :data-phase="task.phase"></span>
              <span class="robot-task-name">{{ task.title }}</span>
              <span class="robot-task-meta">{{ phaseLabel(task) }}</span>
            </li>
          </ul>
        </div>
        <div class="robot-panel-section">
          <span class="robot-panel-title">最近通知</span>
          <p v-if="!history.length" class="robot-panel-empty">暂无通知</p>
          <ul v-else class="robot-notice-list">
            <li v-for="notice in history" :key="notice.id">
              <span class="robot-notice-dot" :class="`dot-${notice.type}`"></span>
              <span class="robot-notice-text">{{ notice.title }}</span>
            </li>
          </ul>
        </div>
        <div class="robot-panel-actions">
          <label class="robot-switch"><input type="checkbox" :checked="settings.animations" @change="setAnimations($event.target.checked)" /><span>漂浮动画</span></label>
          <button type="button" class="robot-action" @click="setCollapsed(true)">收起</button>
          <button type="button" class="robot-action danger" @click="disableRobot">关闭助手</button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
// RobotAssistant: global floating widget. The mascot is a single 2D pixel
// image (public/themes/robot/base.png) whose visor face (RobotArt) expresses
// the business state from RobotController, alongside the status dot, badge,
// task list and bubbles. No 3D rendering.
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { Bot, ChevronDown, ChevronUp } from 'lucide-vue-next'
import { ROBOT_EVENT } from './bus.js'
import { createRobotController, STATE_LABELS } from './RobotController.js'
import { readRobotSettings, writeRobotSettings } from './settings.js'
import RobotArt from './RobotArt.vue'
import { readTheme, normalizeTheme } from '../../utils/theme'

const stage = ref(null)
const fallback = ref(false)
const panelOpen = ref(false)
const settings = ref(readRobotSettings())
const tasks = ref([])
const bubbles = ref([])
const history = ref([])
const currentState = ref('idle')
const theme = ref(normalizeTheme(readTheme()))
const activeCount = computed(() => tasks.value.length)
const animationsOn = computed(() => settings.value.animations)

let controller = null
let cleanup = []
let bubbleSeq = 0
let dragState = null
let rootStyle = ref({})

const stateLabel = computed(() => STATE_LABELS[currentState.value] || '待机中')

function computeStyle() {
  const y = Math.max(8, Math.min(window.innerHeight - 220, Math.round(settings.value.yRatio * window.innerHeight)))
  rootStyle.value = { top: `${y}px` }
}

function persist(patch) {
  settings.value = { ...settings.value, ...patch }
  writeRobotSettings(patch)
}

function setCollapsed(value) {
  persist({ collapsed: value })
  if (value) panelOpen.value = false
}

function setAnimations(value) {
  persist({ animations: value })
}

function disableRobot() {
  persist({ enabled: false })
  panelOpen.value = false
}

function phaseLabel(task) {
  if (task.phase === 'waiting') return '待确认'
  if (task.phase === 'thinking') return '思考中'
  if (task.collab) return `协作 · ${task.collab}`
  if (task.tool && Date.now() < (task.toolUntil || 0)) return `工具 · ${String(task.tool).slice(0, 12)}`
  return '执行中'
}

// ---- Drag: pointer-based, snap to the nearest left/right edge on release. ----
function onPointerDown(event) {
  if (event.button !== 0 && event.pointerType === 'mouse') return
  const rect = stage.value.getBoundingClientRect()
  dragState = { startX: event.clientX, startY: event.clientY, moved: false, baseTop: rect.top, baseLeft: rect.left, width: rect.width, pointerId: event.pointerId }
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
}

function onPointerMove(event) {
  if (!dragState) return
  const dx = event.clientX - dragState.startX
  const dy = event.clientY - dragState.startY
  if (!dragState.moved && Math.hypot(dx, dy) < 6) return
  dragState.moved = true
  const top = Math.max(8, Math.min(window.innerHeight - 220, dragState.baseTop + dy))
  rootStyle.value = { top: `${top}px`, left: `${dragState.baseLeft + dx}px`, right: 'auto' }
}

function onPointerUp() {
  if (!dragState) return
  const moved = dragState.moved
  dragState = null
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  if (!moved) {
    panelOpen.value = !panelOpen.value
    return
  }
  const element = stage.value.getBoundingClientRect()
  const side = element.left + element.width / 2 < window.innerWidth / 2 ? 'left' : 'right'
  const yRatio = Math.max(0.05, Math.min(0.95, element.top / window.innerHeight))
  persist({ side, yRatio })
  computeStyle()
}

function prefersReduced() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

// ---- Notification bubbles: merged when consecutive toasts arrive quickly. ----
function pushBubble({ message, type }) {
  const now = Date.now()
  const last = bubbles.value[bubbles.value.length - 1]
  if (last && now - last.ts < 2500 && last.type === type) {
    last.count += 1
    last.ts = now
    last.title = message
  } else {
    const id = ++bubbleSeq
    bubbles.value.push({ id, title: message, body: '', type: type || 'success', ts: now, count: 1 })
    history.value.unshift({ id, title: message, type: type || 'success', ts: now })
    history.value = history.value.slice(0, 6)
    setTimeout(() => { bubbles.value = bubbles.value.filter(item => item.id !== id) }, 5200)
  }
  if (bubbles.value.length > 3) bubbles.value = bubbles.value.slice(-3)
}

function openPanelFromBubble() {
  panelOpen.value = true
}

function syncFromController() {
  tasks.value = controller.tasks
  currentState.value = controller.faceState()
}

function bindEvent(name, handler, target = window) {
  target.addEventListener(name, handler)
  cleanup.push(() => target.removeEventListener(name, handler))
}

onMounted(() => {
  controller = createRobotController()
  controller.on(syncFromController)

  // Event adapter: robot bus facts + platform toasts.
  bindEvent(ROBOT_EVENT, event => {
    const { type, payload } = event.detail || {}
    controller.dispatch(type, payload)
  })
  bindEvent('toast', event => {
    const { message, type } = event.detail || {}
    controller.dispatch('notify')
    pushBubble({ message, type })
  })
  bindEvent('resize', () => { computeStyle() })
  // saveTheme() broadcasts the new color; keep the mascot's tint in sync.
  bindEvent('theme-change', event => { theme.value = normalizeTheme(event.detail) })
  bindEvent('robot-assistant-reset', () => {
    settings.value = readRobotSettings()
    computeStyle()
  })

  computeStyle()

  // Idle → sleeping / one-shot expiry needs a slow tick even without events.
  const idleTimer = setInterval(() => { controller.dispatch('tick', {}); syncFromController() }, 15000)
  cleanup.push(() => clearInterval(idleTimer))
})

onBeforeUnmount(() => {
  cleanup.forEach(fn => fn())
  cleanup = []
})
</script>

<style scoped>
.robot-assistant { position: fixed; z-index: 820; display: flex; flex-direction: column; align-items: center; gap: 6px; --robot-size: 190px; }
.robot-assistant.side-right { right: 18px; }
.robot-assistant.side-left { left: 18px; }
.robot-assistant.collapsed { --robot-size: 46px; }
.robot-stage { position: relative; width: var(--robot-size); height: calc(var(--robot-size) * 477 / 540); cursor: grab; touch-action: none;
  display: flex; align-items: center; justify-content: center;
  transition: width .2s, height .2s; }
.robot-stage:active { cursor: grabbing; }
.robot-stage:focus-visible { outline: 2px solid var(--primary); outline-offset: 3px; border-radius: 50%; }

.robot-fallback { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: var(--primary); }
.robot-badge { position: absolute; top: 0; right: -2px; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 9px;
  background: var(--danger, #E5484D); color: #fff; font-size: 10px; font-weight: 700; line-height: 18px; text-align: center;
  border: 2px solid var(--surface); box-sizing: content-box; }
.robot-pulse { position: absolute; bottom: 2px; left: 50%; width: 6px; height: 6px; margin-left: -3px; border-radius: 50%; background: var(--text3); opacity: .6; }
.robot-pulse[data-state="working"], .robot-pulse[data-state="thinking"] { background: var(--primary); animation: robot-pulse 1.6s ease-in-out infinite; }
.robot-pulse[data-state="waiting"] { background: var(--warning, #F5A524); animation: robot-pulse 1.1s ease-in-out infinite; }
.robot-pulse[data-state="error"] { background: var(--danger, #E5484D); }
.robot-pulse[data-state="success"] { background: var(--success, #30A46C); }
.robot-pulse[data-state="sleeping"] { opacity: .25; }
@keyframes robot-pulse { 50% { transform: scale(1.6); opacity: .3; } }

.robot-fold { width: 22px; height: 16px; display: flex; align-items: center; justify-content: center; border: 1px solid var(--border);
  border-radius: 6px; background: color-mix(in srgb, var(--surface) 80%, transparent); color: var(--text2); cursor: pointer; padding: 0; }
.robot-fold:hover { color: var(--primary); border-color: var(--primary); }

.robot-bubbles { position: absolute; right: 0; bottom: calc(100% + 10px); display: flex; flex-direction: column; gap: 8px; width: 240px; pointer-events: none; }
.side-left .robot-bubbles { right: auto; left: 0; }
.robot-bubble { pointer-events: auto; display: flex; flex-direction: column; gap: 3px; text-align: left; padding: 10px 12px; border-radius: 12px; cursor: pointer;
  background: color-mix(in srgb, var(--surface) 78%, transparent);
  border: 1px solid color-mix(in srgb, var(--primary) 26%, var(--border));
  backdrop-filter: blur(18px) saturate(140%);
  -webkit-backdrop-filter: blur(18px) saturate(140%);
  box-shadow: 0 8px 24px rgba(15, 23, 42, .14); font: inherit; }
.robot-bubble strong { font-size: 12px; color: var(--text); }
.robot-bubble span { font-size: 11px; color: var(--text2); }
.robot-bubble em { font-style: normal; font-size: 10px; color: var(--primary); }
.robot-bubble.bubble-error { border-color: var(--danger, #E5484D); }
.robot-bubble.bubble-success { border-color: color-mix(in srgb, var(--success, #30A46C) 45%, var(--border)); }

.robot-panel { position: absolute; bottom: calc(100% + 12px); right: 0; width: 272px; padding: 14px; border-radius: 14px;
  background: color-mix(in srgb, var(--surface) 88%, transparent);
  border: 1px solid color-mix(in srgb, var(--primary) 22%, var(--border));
  backdrop-filter: blur(24px) saturate(140%);
  -webkit-backdrop-filter: blur(24px) saturate(140%);
  box-shadow: 0 14px 40px rgba(15, 23, 42, .18); }
.side-left .robot-panel { right: auto; left: 0; }
.robot-panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.robot-panel-head strong { font-size: 13px; }
.robot-panel-state { font-size: 11px; color: var(--primary); background: var(--primary-light); border-radius: 999px; padding: 2px 8px; }
.robot-panel-section { margin-bottom: 10px; }
.robot-panel-title { display: block; font-size: 11px; font-weight: 600; color: var(--text2); margin-bottom: 6px; }
.robot-panel-empty { margin: 0; font-size: 11px; color: var(--text3); }
.robot-task-list, .robot-notice-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; }
.robot-task-list li { display: flex; align-items: center; gap: 7px; font-size: 11px; }
.robot-task-dot { flex: none; width: 7px; height: 7px; border-radius: 50%; background: var(--primary); }
.robot-task-dot[data-phase="waiting"] { background: var(--warning, #F5A524); }
.robot-task-dot[data-phase="thinking"] { background: var(--text3); }
.robot-task-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
.robot-task-meta { flex: none; color: var(--text3); font-size: 10px; }
.robot-notice-list li { display: flex; align-items: center; gap: 7px; font-size: 11px; }
.robot-notice-dot { flex: none; width: 6px; height: 6px; border-radius: 50%; background: var(--primary); }
.robot-notice-dot.dot-error { background: var(--danger, #E5484D); }
.robot-notice-dot.dot-success { background: var(--success, #30A46C); }
.robot-notice-text { color: var(--text2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.robot-panel-actions { display: flex; align-items: center; gap: 8px; padding-top: 10px; border-top: 1px solid var(--border); }
.robot-switch { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--text2); cursor: pointer; }
.robot-action { border: 1px solid var(--border); background: transparent; color: var(--text2); border-radius: 7px; padding: 4px 9px; font: inherit; font-size: 11px; cursor: pointer; }
.robot-action:hover { color: var(--primary); border-color: var(--primary); }
.robot-action.danger:hover { color: var(--danger, #E5484D); border-color: var(--danger, #E5484D); }

.robot-bubble-enter-active, .robot-bubble-leave-active { transition: opacity .25s, transform .25s; }
.robot-bubble-enter-from, .robot-bubble-leave-to { opacity: 0; transform: translateY(6px); }
.robot-panel-enter-active, .robot-panel-leave-active { transition: opacity .2s, transform .2s; }
.robot-panel-enter-from, .robot-panel-leave-to { opacity: 0; transform: translateY(8px); }

@media (max-width: 768px) {
  .robot-assistant { --robot-size: 126px; right: max(10px, env(safe-area-inset-right)); }
  .robot-assistant.collapsed { --robot-size: 42px; }
  .robot-assistant.side-left { left: max(10px, env(safe-area-inset-left)); }
  .robot-panel { width: min(272px, calc(100vw - 32px)); }
  .robot-bubbles { width: min(240px, calc(100vw - 32px)); }
}
</style>

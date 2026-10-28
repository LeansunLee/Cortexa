// State machine for the robot assistant: aggregates platform-wide task facts
// (not per-agent), applies the priority rules and exposes what the face and
// body should show. One-shot states display for a few seconds, then fall back
// to the highest-priority continuous state. Waiting/error are sticky — they
// survive ordinary working events until explicitly resolved.
//
// Priority: waiting/error > notification > success > working > thinking > idle > sleeping.

const ONE_SHOT = { success: 3200, notification: 3200, error: 3800 }
const CONTINUOUS_PRIORITY = ['waiting', 'working', 'thinking', 'idle', 'sleeping']
const SLEEP_AFTER_MS = 120000
const TOOL_FLASH_MS = 1600

export function createRobotController() {
  const tasks = new Map() // id -> {id, title, phase: thinking|working|waiting, tool?, collab?}
  let oneShot = null // {name, until}
  let sleepTimer = Date.now()
  let lastState = 'idle'
  let animationsEnabled = true
  const listeners = new Set()

  const notify = () => listeners.forEach(fn => fn(exported))

  function tasksByPhase(phase) {
    return [...tasks.values()].filter(task => task.phase === phase)
  }

  function continuousState() {
    for (const phase of CONTINUOUS_PRIORITY) {
      if (phase === 'sleeping') break
      if (tasksByPhase(phase).length) return phase
    }
    return Date.now() - sleepTimer > SLEEP_AFTER_MS ? 'sleeping' : 'idle'
  }

  const exported = {
    get tasks() { return [...tasks.values()] },
    faceState() {
      if (oneShot && Date.now() < oneShot.until) return oneShot.name
      if (oneShot) oneShot = null
      return continuousState()
    },
    animationsActive() { return animationsEnabled && this.faceState() !== 'sleeping' },
    dirty: true,

    on(listener) { listeners.add(listener); return () => listeners.delete(listener) },

    setAnimationsEnabled(value) {
      animationsEnabled = value
      exported.dirty = true
      notify()
    },

    dispatch(type, payload = {}) {
      const now = Date.now()
      sleepTimer = now
      let triggerName = null
      const task = payload.id ? tasks.get(payload.id) : null
      switch (type) {
        case 'task:submitted':
          tasks.set(payload.id, { id: payload.id, title: payload.title || '新任务', phase: 'thinking' })
          break
        case 'task:working':
          if (!task) tasks.set(payload.id, { id: payload.id, title: payload.title || '后台任务', phase: 'working' })
          else task.phase = 'working'
          break
        case 'task:tool':
          if (task) {
            task.phase = task.phase === 'waiting' ? 'waiting' : 'working'
            if (!task.toolUntil || now - task.toolUntil > TOOL_FLASH_MS) {
              task.tool = payload.tool
              task.toolUntil = now + TOOL_FLASH_MS
            }
          }
          break
        case 'task:collab':
          if (task) task.collab = payload.agent || '协作 Agent'
          break
        case 'task:waiting':
          if (!task) tasks.set(payload.id, { id: payload.id, title: payload.title || '待确认', phase: 'waiting' })
          else task.phase = 'waiting'
          break
        case 'task:resolved':
          if (task && task.phase === 'waiting') task.phase = 'working'
          break
        case 'task:done':
          tasks.delete(payload.id)
          if (!payload.question) {
            oneShot = { name: 'success', until: now + ONE_SHOT.success }
            triggerName = 'success'
          }
          break
        case 'task:error':
          tasks.delete(payload.id)
          oneShot = { name: 'error', until: now + ONE_SHOT.error, message: payload.message }
          triggerName = 'error'
          break
        case 'notify':
          oneShot = { name: 'notification', until: now + ONE_SHOT.notification }
          triggerName = 'notification'
          break
        case 'runtime:snapshot': {
          tasks.clear()
          for (const task of payload.tasks || []) tasks.set(task.id, { ...task })
          break
        }
        default:
          return
      }
      exported.dirty = true
      notify()
      return { state: exported.faceState(), trigger: triggerName }
    },
  }
  return exported
}

export const STATE_LABELS = {
  idle: '待机中',
  thinking: '思考中',
  working: '执行任务',
  success: '任务完成',
  notification: '新通知',
  waiting: '等待确认',
  error: '执行出错',
  sleeping: '休息中',
}

// Persistence for the robot assistant: per-account keys via the project's
// preferenceKey helper (same convention as theme-color / ui-appearance).
import { preferenceKey } from '../../utils/preferences.js'

const KEY = 'robot-assistant'
const DEFAULTS = {
  enabled: true,
  animations: true,
  collapsed: false,
  side: 'right',       // snap edge after dragging
  yRatio: 0.72,        // vertical position as a ratio of viewport height
}

export function readRobotSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(preferenceKey(KEY)) || 'null')
    if (saved && typeof saved === 'object') return { ...DEFAULTS, ...saved }
  } catch { /* Storage can be disabled by the browser. */ }
  return { ...DEFAULTS }
}

export function writeRobotSettings(settings) {
  try {
    localStorage.setItem(preferenceKey(KEY), JSON.stringify({ ...readRobotSettings(), ...settings }))
  } catch { /* Storage can be disabled by the browser. */ }
}

export function resetRobotSettings() {
  try { localStorage.removeItem(preferenceKey(KEY)) } catch { /* ignore */ }
  return { ...DEFAULTS }
}

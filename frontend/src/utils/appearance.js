import { preferenceKey } from './preferences.js'

export const APPEARANCE_KEY = 'ui-appearance'
export const appearanceOptions = [
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
  { value: 'system', label: '跟随系统' },
]

const isAppearance = value => appearanceOptions.some(option => option.value === value)
const systemDark = () => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false

export function readAppearance(storage = localStorage) {
  try {
    const saved = storage.getItem(preferenceKey(APPEARANCE_KEY, storage))
    if (isAppearance(saved)) return saved
  } catch { /* Browser storage can be unavailable. */ }
  return 'system'
}

export function resolveAppearance(value) {
  return value === 'system' ? (systemDark() ? 'dark' : 'light') : value
}

export function applyAppearance(value = readAppearance()) {
  const preference = isAppearance(value) ? value : 'system'
  const resolved = resolveAppearance(preference)
  const root = document.documentElement
  root.dataset.appearance = preference
  root.dataset.theme = resolved
  root.style.colorScheme = resolved
  return resolved
}

export function saveAppearance(value) {
  if (!isAppearance(value)) return
  localStorage.setItem(preferenceKey(APPEARANCE_KEY), value)
  applyAppearance(value)
  window.dispatchEvent(new CustomEvent('appearance-change', { detail: value }))
}

let listening = false
export function watchSystemAppearance() {
  if (listening || !window.matchMedia) return () => {}
  listening = true
  const media = window.matchMedia('(prefers-color-scheme: dark)')
  const update = () => {
    if (readAppearance() === 'system') applyAppearance('system')
  }
  media.addEventListener?.('change', update)
  return () => {
    media.removeEventListener?.('change', update)
    listening = false
  }
}

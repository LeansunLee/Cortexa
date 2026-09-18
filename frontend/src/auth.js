import { reactive } from 'vue'
import api from './api'
import { activatePreferences } from './utils/preferences.js'
import { applyTheme, readTheme } from './utils/theme.js'
import { applyAppearance } from './utils/appearance.js'

export const auth = reactive({ user: null, loaded: false, workspaceId: localStorage.getItem('currentWorkspace') || '' })
let pending
export async function refreshAuth() {
  if (pending) return pending
  pending = api.get('/auth/me', { skipAuthRedirect: true }).then(({ data }) => {
    activatePreferences(data.id)
    applyTheme(readTheme())
    applyAppearance()
    auth.user = data
    const ids = data.memberships.map(m => m.workspace_id)
    if (!ids.includes(auth.workspaceId)) setWorkspace(ids[0] || '')
    return data
  }).catch(error => {
    auth.user = null
    if (error.response?.status !== 401) throw error
    return null
  }).finally(() => { auth.loaded = true; pending = null })
  return pending
}
export function setWorkspace(id) {
  auth.workspaceId = id || ''
  localStorage.setItem('currentWorkspace', auth.workspaceId)
}
export function can(code) {
  if (!auth.user) return false
  if (auth.user.system_permissions.includes(code)) return true
  return auth.user.memberships.find(m => m.workspace_id === auth.workspaceId)?.permissions.includes(code) || false
}
export function canAdmin() {
  return ['users.manage', 'roles.manage', 'members.manage', 'audit.read', 'identity.manage'].some(can)
}
export async function logout() {
  await api.post('/auth/logout')
  auth.user = null
  setWorkspace('')
  window.location.assign('/login')
}

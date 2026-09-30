<template>
  <router-view v-if="route.path === '/login' || route.path === '/change-password'" />
  <div v-else class="app-layout">
    <aside class="sidebar">
      <div class="sidebar-brand">
        <span class="logo"><Bot :size="24" /></span>
        <span class="brand-text">Cortexa</span>
      </div>
      <div class="sidebar-workspace">
        <SearchSelect v-model="currentWorkspace" class="workspace-select" aria-label="切换工作空间" placeholder="选择工作空间" :options="[{ value: '', label: '选择工作空间' }, ...workspaces.map(ws => ({ value: ws.id, label: ws.name }))]" @change="onWorkspaceChange" />
      </div>
      <nav class="sidebar-nav">
        <router-link v-if="auth.workspaceId" to="/works" class="nav-item" title="工作" aria-label="工作"><ClipboardList :size="20" /><span class="nav-text">工作</span></router-link>
        <router-link v-if="can('agent.use')" to="/chat" class="nav-item" title="对话" aria-label="对话">
          <MessageSquare :size="18" />
          <span class="nav-text">对话</span>
        </router-link>
        <router-link v-if="can('meeting.use')" to="/meetings" class="nav-item" title="会议" aria-label="会议">
          <Calendar :size="18" />
          <span class="nav-text">会议</span>
        </router-link>
        <router-link v-if="can('agent.use')" to="/my-agents" class="nav-item" title="我的 Agent" aria-label="我的 Agent">
          <Bot :size="18" />
          <span class="nav-text">我的 Agent</span>
        </router-link>
        <div class="nav-divider"></div>
        <router-link v-if="can('agent.read')" to="/workspaces" class="nav-item" title="工作空间" aria-label="工作空间">
          <LayoutDashboard :size="18" />
          <span class="nav-text">工作空间</span>
        </router-link>
        <router-link v-if="can('agent.read')" to="/agents" class="nav-item" title="智能体" aria-label="智能体">
          <Bot :size="18" />
          <span class="nav-text">智能体</span>
        </router-link>
        <router-link v-if="can('knowledge.manage') || can('knowledge.use')" to="/knowledge" class="nav-item" title="空间知识库" aria-label="空间知识库">
          <BookOpen :size="18" />
          <span class="nav-text">空间知识库</span>
        </router-link>
        <router-link v-if="can('data.manage')" to="/data-sources" class="nav-item" title="数据源" aria-label="数据源">
          <Database :size="18" />
          <span class="nav-text">数据源</span>
        </router-link>
        <router-link v-if="can('workflows.manage')" to="/workflows" class="nav-item" title="工作流" aria-label="工作流"><Workflow :size="18" /><span class="nav-text">工作流</span></router-link>
        <router-link v-if="can('tasks.manage')" to="/tasks" class="nav-item" title="任务" aria-label="任务"><ClipboardList :size="18" /><span class="nav-text">任务</span></router-link>
      </nav>
      <div class="sidebar-footer">
        <router-link v-if="canAdmin()" to="/access" class="nav-item" title="用户与权限" aria-label="用户与权限">
          <ShieldCheck :size="18" />
          <span class="nav-text">用户与权限</span>
        </router-link>
        <router-link v-if="auth.user?.is_superadmin" to="/model-usage" class="nav-item" title="模型用量" aria-label="模型用量"><ChartNoAxesCombined :size="18" /><span class="nav-text">模型用量</span></router-link>
        <router-link v-if="can('config.manage')" to="/settings" class="nav-item" title="系统配置" aria-label="系统配置">
          <Settings :size="18" />
          <span class="nav-text">系统配置</span>
        </router-link>
          <div ref="userMenu" class="user-menu" @keydown.esc.stop="closeUserMenu(true)">
            <button ref="userMenuTrigger" type="button" class="user-menu-trigger" aria-label="账号菜单" :aria-expanded="showUserMenu" aria-controls="account-dropdown" @click="showUserMenu = !showUserMenu">
            <div class="user-avatar">{{ auth.user?.display_name?.charAt(0) || 'U' }}</div>
            <span class="user-name">{{ auth.user?.display_name }}</span>
            <ChevronUp :size="14" />
            </button>
            <div v-if="showUserMenu" id="account-dropdown" class="user-dropdown">
              <div class="user-dropdown-header">
                <div class="user-avatar-lg">{{ auth.user?.display_name?.charAt(0) || 'U' }}</div>
                <div class="user-info">
                  <div class="user-display-name">{{ auth.user?.display_name }}</div>
                  <div class="user-username">{{ auth.user?.username }}</div>
                </div>
              </div>
              <div class="dropdown-divider"></div>
              <router-link to="/personalization" class="dropdown-item" @click="showUserMenu = false">
                <Palette :size="16" /><span>个性化设置</span>
              </router-link>
              <router-link to="/change-password" class="dropdown-item" @click="showUserMenu = false">
                <KeyRound :size="16" />
                <span>修改密码</span>
              </router-link>
              <div class="dropdown-divider"></div>
              <button class="dropdown-item logout" @click="logout">
                <LogOut :size="16" />
                <span>退出登录</span>
              </button>
            </div>
          </div>
      </div>
    </aside>
    <div class="main-area">
      <div ref="tabBar" class="page-tabs" role="tablist" aria-label="已打开的页面">
        <div v-for="(tab, index) in pageTabs" :key="tab.id" class="page-tab" :class="{ active: tab.location.fullPath === route.fullPath }" role="presentation">
          <button :id="`page-tab-${tab.id}`" class="page-tab-label" :title="tab.title" role="tab" :aria-selected="tab.location.fullPath === route.fullPath" :aria-controls="`page-panel-${tab.id}`" :tabindex="tab.location.fullPath === route.fullPath ? 0 : -1" @click="router.push(tab.location.fullPath)" @keydown="onTabKeydown($event, index)">{{ tab.title }}</button>
          <button v-if="pageTabs.length > 1" class="page-tab-close" :aria-label="`关闭${tab.title}标签页`" :title="`关闭${tab.title}`" @click="closePageTab(tab)"><X :size="14" /></button>
        </div>
      </div>
      <main class="main-content">
        <PageTabPanel v-for="tab in pageTabs" :key="tab.id" :location="tab.location" :active="tab.location.fullPath === route.fullPath" :label-id="`page-tab-${tab.id}`" :panel-id="`page-panel-${tab.id}`" @title-change="tab.title = $event" />
      </main>
    </div>

    <!-- Global Toast -->
    <Transition name="toast">
      <div v-if="toast.show" :class="['global-toast', 'toast-' + toast.type]">
        <span class="toast-icon"><AppIcon :name="toast.type === 'success' ? 'Check' : toast.type === 'error' ? 'X' : 'Info'" /></span>
        <span class="toast-msg">{{ toast.message }}</span>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import {
  ChartNoAxesCombined, ClipboardList, LayoutDashboard, Bot, Workflow, Calendar, BookOpen, Database,
  MessageSquare, Palette, Settings, ShieldCheck, KeyRound, LogOut, Bot as BotIcon, ChevronUp, X
} from 'lucide-vue-next'

import { ref, onMounted, onUnmounted, watch, computed, nextTick, markRaw } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { auth, can, canAdmin, refreshAuth, setWorkspace, logout } from './auth'
const route = useRoute(), router = useRouter()
import { workspaceApi } from './api'
import PageTabPanel from './components/PageTabPanel.vue'

const pageTabs = ref([])
const tabBar = ref(null)
let nextTabId = 0
const pageTitles = {
  '/model-usage': '模型用量',
  '/': '首页', '/works': '工作', '/chat': '对话', '/meetings': '会议',
  '/my-agents': '我的 Agent', '/workspaces': '工作空间', '/agents': '智能体',
  '/knowledge': '空间知识库', '/data-sources': '数据源', '/settings': '系统配置',
  '/personalization': '个性化设置', '/access': '用户与权限', '/workflows': '工作流', '/tasks': '任务',
}
const isIdentityPage = () => ['/login', '/change-password'].includes(route.path)
function openCurrentTab() {
  if (isIdentityPage() || !auth.user || !route.matched.length) return
  if ((route.meta.superadmin && !auth.user?.is_superadmin) || (route.meta.permission && !can(route.meta.permission)) || (route.meta.admin && !canAdmin())) return
  if (!pageTabs.value.some(tab => tab.location.fullPath === route.fullPath)) {
    pageTabs.value.push({
      id: ++nextTabId,
      title: pageTitles[route.path] || (route.path.startsWith('/agent-operations/') ? 'Agent 运维' : route.path.startsWith('/works/') ? '工作详情' : '页面'),
      location: markRaw(router.resolve(route.fullPath)),
    })
  }
  nextTick(() => tabBar.value?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' }))
}
async function closePageTab(tab) {
  if (pageTabs.value.length <= 1) return
  const index = pageTabs.value.indexOf(tab)
  if (tab.location.fullPath === route.fullPath) {
    const next = pageTabs.value[index + 1] || pageTabs.value[index - 1]
    await router.push(next.location.fullPath)
    if (route.fullPath === tab.location.fullPath) return
  }
  pageTabs.value = pageTabs.value.filter(item => item.id !== tab.id)
  await nextTick()
  tabBar.value?.querySelector('[aria-selected="true"]')?.focus()
}
async function onTabKeydown(event, index) {
  const count = pageTabs.value.length
  let target
  if (event.key === 'ArrowRight') target = (index + 1) % count
  else if (event.key === 'ArrowLeft') target = (index - 1 + count) % count
  else if (event.key === 'Home') target = 0
  else if (event.key === 'End') target = count - 1
  else if (event.key === 'Delete') { event.preventDefault(); return closePageTab(pageTabs.value[index]) }
  else return
  event.preventDefault()
  await router.push(pageTabs.value[target].location.fullPath)
  await nextTick()
  tabBar.value?.querySelector('[aria-selected="true"]')?.focus()
}
watch(() => route.fullPath, openCurrentTab, { immediate: true })
watch(() => [auth.user?.id, auth.workspaceId], () => {
  pageTabs.value = []
  openCurrentTab()
})
watch(() => auth.user, () => {
  pageTabs.value = pageTabs.value.filter(tab =>
    (!tab.location.meta.superadmin || auth.user?.is_superadmin) &&
    (!tab.location.meta.permission || can(tab.location.meta.permission)) &&
    (!tab.location.meta.admin || canAdmin()))
  if (!isIdentityPage() && ((route.meta.superadmin && !auth.user?.is_superadmin) || (route.meta.permission && !can(route.meta.permission)) || (route.meta.admin && !canAdmin()))) router.replace('/')
})

// Share the same storage and color tokens with the settings preview.
import { readTheme, applyTheme } from './utils/theme'
import { applyAppearance } from './utils/appearance'
import { installGlassLighting } from './utils/glassLighting'
window.addEventListener('theme-change', (event) => applyTheme(event.detail))
window.addEventListener('appearance-change', (event) => applyAppearance(event.detail))

const workspaces = ref([])
const currentWorkspace = computed({ get: () => auth.workspaceId, set: setWorkspace })

const loadWorkspaces = async () => {
  try {
    const { data } = await workspaceApi.list()
    workspaces.value = data
    if (!data.some(ws => ws.id === currentWorkspace.value) && data.length > 0) {
      currentWorkspace.value = data[0].id
      localStorage.setItem('currentWorkspace', data[0].id)
    }
  } catch (e) {
    console.error('Failed to load workspaces:', e)
  }
}

const onWorkspaceChange = () => {
  setWorkspace(currentWorkspace.value)
  if ((route.meta.superadmin && !auth.user?.is_superadmin) || (route.meta.permission && !can(route.meta.permission)) || (route.meta.admin && !canAdmin())) router.replace('/')
  window.dispatchEvent(new CustomEvent('workspace-changed', { detail: currentWorkspace.value }))
}

// Global toast state
const showUserMenu = ref(false)
const userMenu = ref(null)
const userMenuTrigger = ref(null)
const closeUserMenu = (restoreFocus = false) => {
  showUserMenu.value = false
  if (restoreFocus) userMenuTrigger.value?.focus()
}
const onOutsidePointer = event => {
  if (!userMenu.value?.contains(event.target)) closeUserMenu()
}
const onOutsideFocus = event => {
  if (!userMenu.value?.contains(event.target)) closeUserMenu()
}
let removeGlassLighting
onMounted(() => {
  document.addEventListener('pointerdown', onOutsidePointer)
  document.addEventListener('focusin', onOutsideFocus)
  removeGlassLighting = installGlassLighting()
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', onOutsidePointer)
  document.removeEventListener('focusin', onOutsideFocus)
  removeGlassLighting?.()
})
watch(() => route.path, () => closeUserMenu())
const toast = ref({ show: false, message: '', type: 'success' })

const showToast = (message, type = 'success') => {
  toast.value = { show: true, message, type }
  setTimeout(() => { toast.value.show = false }, 3000)
}

// Expose globally via window
window.__showToast = showToast

onMounted(() => {
  if (auth.user && !auth.user.must_change_password) loadWorkspaces()
  applyTheme(readTheme())
  window.addEventListener('workspace-changed', async () => {
    setWorkspace(localStorage.getItem('currentWorkspace') || '')
    await refreshAuth()
    await loadWorkspaces()
  })
  window.addEventListener('toast', (e) => showToast(e.detail.message, e.detail.type))
})
watch(() => auth.user, user => { if (user && !user.must_change_password) loadWorkspaces() })
</script>

<style>
:root {
  --page-padding-y: 24px;
  --page-padding-x: 32px;
  --page-tabs-height: 44px;
  --page-viewport-height: calc(100dvh - var(--page-tabs-height) - var(--page-padding-y) * 2);
  --bg: #F8F9FC;
  --surface: #FFFFFF;
  --surface2: #F8F9FC;
  --surface-elevated: var(--surface);
  --surface-overlay: var(--surface);
  --surface-muted: var(--surface2);
  --surface-card: var(--surface);
  --surface-panel: var(--surface);
  --surface-dialog: var(--surface-overlay);
  --surface-table: var(--surface);
  --text: #111827;
  --text2: #4B5563;
  --text3: #667085;
  --text-primary: var(--text);
  --text-secondary: var(--text2);
  --text-muted: var(--text3);
  --border: #E5E7EB;
  --border-card: var(--border);
  --divider: var(--border);
  --primary: #7C3AED;
  --primary-hover: #6D28D9;
  --primary-light: #F3EEFF;
  --primary-text: #FFFFFF;
  --accent: #8B5CF6;
  --accent-light: #FAF7FF;
  --success: #059669;
  --success-bg: #ECFDF5;
  --danger: #DC2626;
  --danger-bg: #FEF2F2;
  --overlay: rgba(15, 23, 42, 0.48);
  --radius: 14px;
  --radius-sm: 10px;
  --radius-xs: 6px;
  --shadow: 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.06);
  --shadow-card: none;
  --shadow-panel: var(--shadow);
  --shadow-dialog: 0 20px 60px rgba(0,0,0,.2);
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --control-height: 40px;
  --transition: 150ms ease;
}

:root[data-theme="dark"] {
  --bg: #0F1117;
  --surface: #171A22;
  --surface2: #20242E;
  --text: #F3F4F6;
  --text2: #B8C0CC;
  --text3: #98A2B3;
  --border: #303642;
  --success: #34D399;
  --success-bg: rgba(16, 185, 129, .14);
  --danger: #F87171;
  --danger-bg: rgba(239, 68, 68, .14);
  --overlay: rgba(0, 0, 0, .66);
  --shadow: 0 1px 2px rgba(0,0,0,.3);
  --shadow-md: 0 8px 24px rgba(0,0,0,.32);
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body { 
  background: var(--bg); 
  color: var(--text); 
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; 
}
button, input, textarea, select { font-family: inherit; }
input, textarea, select { color: var(--text); background-color: var(--surface); }
input::placeholder, textarea::placeholder { color: var(--text3); }

/* Compatibility layer for legacy page-scoped light colors. New UI must use semantic tokens. */
:root[data-theme="dark"]:not([data-color-theme="glass"]) :is(.modal, .modal-box, .card, .panel, .work-panel, .agent-card, .knowledge-card, .confirm-dialog, .document-preview, .mention-popover) {
  background-color: var(--surface) !important;
  color: var(--text);
  border-color: var(--border) !important;
}
:root[data-theme="dark"] :is(.tabs, .schema-header, .test-result-block, .empty-state, .preview-toolbar) {
  border-color: var(--border) !important;
}
a { text-decoration: none; color: inherit; }

.app-layout {
  display: flex;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
}
.sidebar {
  width: 240px;
  min-height: 0;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 48px;
  padding: 0 20px;
  flex-shrink: 0;
}
.logo { font-size: 24px; }
.brand-text { font-weight: 700; font-size: 16px; color: var(--text); }
.sidebar-workspace {
  padding: 12px 16px;
}
.sidebar-workspace .workspace-select {
  width: 100%;
  font-size: 13px;
}
.nav-divider {
  height: 1px;
  background: var(--border);
  margin: 8px 16px;
}
.sidebar-nav {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-radius: var(--radius-sm);
  text-decoration: none;
  color: var(--text2);
  font-size: 14px;
  font-weight: 500;
  transition: all var(--transition);
  min-height: 42px;
  flex-shrink: 0;
}
.nav-item:hover { background: var(--surface2); color: var(--text); }
.nav-item.router-link-active {
  background: var(--navigation-background, var(--accent-light));
  color: var(--navigation-color, var(--accent));
  font-weight: 600;
}
.nav-icon { font-size: 18px; width: 24px; text-align: center; }
.sidebar-footer {
  flex-shrink: 0;
  padding: 12px;
  border-top: 1px solid var(--border);
}
/* Account access stays in the sidebar on every authenticated page. */
.user-menu { position: relative; margin-top: 8px; }
.user-menu-trigger {
  display: flex; align-items: center; gap: 10px; width: 100%;
  padding: 10px; border: 0; border-radius: var(--radius-sm);
  background: transparent; color: var(--text); font: inherit;
  text-align: left; cursor: pointer;
}
.user-menu-trigger:hover, .user-menu-trigger[aria-expanded="true"] { background: var(--surface2); }
.user-menu-trigger:focus-visible, .dropdown-item:focus-visible { outline: 2px solid var(--primary); outline-offset: -2px; }
.user-menu-trigger > svg, .user-avatar, .user-avatar-lg { flex-shrink: 0; }
.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary) 0%, var(--primary-hover, #6D28D9) 100%);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
}
.user-avatar-lg {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary) 0%, var(--primary-hover, #6D28D9) 100%);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 600;
}
.user-name {
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
}
.user-dropdown {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  width: max(100%, 220px);
  max-width: calc(100vw - 24px);
  max-height: calc(100dvh - 88px);
  overflow-y: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.12);
  min-width: 200px;
  z-index: 1000;
}
.user-dropdown-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
}
.user-info { display: flex; flex-direction: column; min-width: 0; overflow-wrap: anywhere; }
.user-display-name { font-size: 14px; font-weight: 600; color: var(--text); }
.user-username { font-size: 12px; color: var(--text3); }
.dropdown-divider {
  height: 1px;
  background: var(--border);
  margin: 4px 0;
}
.dropdown-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  font-size: 13px;
  color: var(--text2);
  text-decoration: none;
  transition: background 0.1s;
  width: 100%;
  border: none;
  background: none;
  cursor: pointer;
  text-align: left;
}
.dropdown-item:hover { background: var(--surface2); color: var(--text); }
.dropdown-item.logout { color: #DC2626; }
.dropdown-item.logout:hover { background: #FEF2F2; color: #DC2626; }
:root[data-theme="dark"] .user-menu-trigger:hover,
:root[data-theme="dark"] .user-menu-trigger[aria-expanded="true"] {
  background: color-mix(in srgb, var(--surface2) 88%, #ffffff 12%);
}
:root[data-theme="dark"] .user-dropdown {
  background: color-mix(in srgb, var(--surface) 94%, #ffffff 6%);
  color: var(--text);
  border-color: color-mix(in srgb, var(--border) 82%, #ffffff 18%);
  box-shadow: 0 22px 54px rgba(0,0,0,.42);
}
:root[data-theme="dark"] .dropdown-divider { background: color-mix(in srgb, var(--border) 82%, #ffffff 18%); }
:root[data-theme="dark"] .dropdown-item { color: var(--text2); }
:root[data-theme="dark"] .dropdown-item:hover,
:root[data-theme="dark"] .dropdown-item:focus-visible {
  background: color-mix(in srgb, var(--primary) 16%, var(--surface2));
  color: var(--text);
}
:root[data-theme="dark"] .dropdown-item.logout { color: #F87171; }
:root[data-theme="dark"] .dropdown-item.logout:hover,
:root[data-theme="dark"] .dropdown-item.logout:focus-visible {
  background: color-mix(in srgb, #ef4444 18%, var(--surface2));
  color: #FCA5A5;
}
:root[data-theme="dark"] .user-menu-trigger:focus-visible,
:root[data-theme="dark"] .dropdown-item:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--primary) 40%, transparent);
}
:root[data-color-theme="glass"] .user-dropdown {
  isolation: isolate;
  background-color: var(--glass-menu-background, var(--surface));
  background-image: var(--glass-popover-gradient, none);
  background-clip: padding-box;
  border-color: var(--glass-edge-border);
  box-shadow: var(--glass-edge-shadow), 0 18px 44px color-mix(in srgb, var(--text) 20%, transparent);
  backdrop-filter: var(--glass-menu-backdrop);
  -webkit-backdrop-filter: var(--glass-menu-backdrop);
}
:root[data-color-theme="glass"] .user-dropdown::before,
:root[data-color-theme="glass"] .user-dropdown::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  border-radius: inherit;
  z-index: 0;
}
:root[data-color-theme="glass"] .user-dropdown::before {
  background: none;
}
:root[data-color-theme="glass"] .user-dropdown::after {
  background: linear-gradient(180deg, rgba(255,255,255,calc(var(--glass-edge-alpha) * .22)) 0%, transparent 14%);
  box-shadow: inset 0 0 0 1px rgba(255,255,255,calc(var(--glass-edge-alpha) * .38)), inset 0 1px 0 rgba(255,255,255,calc(var(--glass-edge-alpha) * .72)), inset 0 -1px 0 rgba(15,23,42,calc(var(--glass-edge-alpha) * .16));
}
:root[data-color-theme="glass"] .user-dropdown > * { position: relative; z-index: 1; }
:root[data-color-theme="glass"] .user-menu-trigger:hover,
:root[data-color-theme="glass"] .user-menu-trigger[aria-expanded="true"] {
  background: var(--glass-selection-background, var(--primary-light));
  color: var(--text);
  backdrop-filter: var(--glass-control-backdrop);
  -webkit-backdrop-filter: var(--glass-control-backdrop);
}
:root[data-color-theme="glass"] .dropdown-item:hover,
:root[data-color-theme="glass"] .dropdown-item:focus-visible {
  background: var(--glass-selection-background, var(--primary-light));
  color: var(--text);
}
:root[data-color-theme="glass"] .dropdown-divider { background: var(--glass-edge-border-soft); }
:root[data-theme="dark"][data-color-theme="glass"] .user-dropdown {
  background-color: var(--glass-menu-background, color-mix(in srgb, var(--surface) 88%, transparent));
  background-image: var(--glass-popover-gradient, none);
  border-color: var(--glass-edge-border-soft);
  box-shadow: var(--glass-edge-shadow, none), 0 24px 58px rgba(0,0,0,.48);
  backdrop-filter: var(--glass-menu-backdrop, blur(24px) saturate(135%)) !important;
  -webkit-backdrop-filter: var(--glass-menu-backdrop, blur(24px) saturate(135%)) !important;
}
:root[data-theme="dark"][data-color-theme="glass"] .user-dropdown::before {
  background: none;
}
:root[data-theme="dark"][data-color-theme="glass"] .user-dropdown::after {
  background: linear-gradient(180deg, rgba(255,255,255,calc(var(--glass-edge-alpha) * .16)) 0%, transparent 14%);
  box-shadow: inset 0 0 0 1px rgba(255,255,255,calc(var(--glass-edge-alpha) * .30)), inset 0 1px 0 rgba(255,255,255,calc(var(--glass-edge-alpha) * .52)), inset 0 -1px 0 rgba(0,0,0,.22);
}
:root[data-theme="dark"][data-color-theme="glass"] .user-menu-trigger:hover,
:root[data-theme="dark"][data-color-theme="glass"] .user-menu-trigger[aria-expanded="true"],
:root[data-theme="dark"][data-color-theme="glass"] .dropdown-item:hover,
:root[data-theme="dark"][data-color-theme="glass"] .dropdown-item:focus-visible {
  background: var(--glass-selection-background, color-mix(in srgb, var(--primary) 24%, var(--surface2)));
  color: var(--text);
}
:root[data-theme="dark"][data-color-theme="glass"] .dropdown-item.logout:hover,
:root[data-theme="dark"][data-color-theme="glass"] .dropdown-item.logout:focus-visible {
  background: color-mix(in srgb, var(--danger) 16%, var(--glass-search-background, var(--surface2)));
  color: var(--danger);
}

/* Main Area */
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.page-tabs {
  display: flex; align-items: stretch; gap: 4px; flex-shrink: 0;
  height: var(--page-tabs-height); padding: 5px 12px 0;
  overflow-x: auto; scrollbar-width: thin; background: var(--surface);
  border-bottom: 1px solid var(--border);
}
.page-tab { display: flex; align-items: center; flex-shrink: 0; max-width: 220px; border-radius: 8px 8px 0 0; border-bottom: 2px solid transparent; color: var(--text2); }
.page-tab:hover { background: var(--surface2); }
.page-tab.active { color: var(--navigation-color, var(--accent)); background: var(--navigation-background, var(--accent-light)); border-bottom-color: var(--navigation-color, var(--accent)); }
.page-tab-label { min-width: 0; padding: 9px 12px; background: transparent; color: inherit; border: 0; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; }
.page-tab.active .page-tab-label { font-weight: 600; }
.page-tab-close { display: flex; align-items: center; justify-content: center; flex-shrink: 0; width: 26px; height: 26px; margin-right: 5px; border: 0; border-radius: 5px; background: transparent; color: inherit; cursor: pointer; }
.page-tab-close:hover { background: var(--border); color: var(--text); }
.page-tab-label:focus-visible, .page-tab-close:focus-visible { outline: 2px solid var(--primary); outline-offset: -2px; }

.main-content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.page-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--page-padding-y) var(--page-padding-x);
  max-width: none;
  width: 100%;
}

@media (max-width: 900px) {
  :root { --page-padding-y: 20px; --page-padding-x: 20px; }
  .sidebar { width: 200px; }
}
@media (max-width: 640px) {
  :root { --page-padding-y: 16px; --page-padding-x: 16px; }
  .sidebar { width: 72px; }
  .sidebar-brand { justify-content: center; padding: 0; }
  .brand-text, .nav-text, .user-name, .user-menu-trigger > svg { display: none; }
  .sidebar-workspace { padding: 8px 4px; }
  .sidebar-workspace .workspace-select { font-size: 11px; }
  .sidebar-nav, .sidebar-footer { padding: 8px; }
  .nav-item { padding: 10px; justify-content: center; }
  .user-menu-trigger { justify-content: center; padding: 8px; }
  .nav-divider { margin: 8px 4px; }
}

/* Global Toast - Top Right */
.global-toast {
  position: fixed;
  top: 20px;
  right: 24px;
  padding: 12px 20px;
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-weight: 500;
  z-index: 10000;
  display: flex;
  align-items: center;
  gap: 8px;
  box-shadow: var(--shadow-panel);
  max-width: 400px;
}
.toast-success { background: var(--success-bg); color: var(--success); border: 1px solid var(--success); }
.toast-error { background: var(--danger-bg); color: var(--danger); border: 1px solid var(--danger); }
.toast-info { background: var(--info-bg); color: var(--info); border: 1px solid var(--info); }
.toast-icon { font-size: 16px; font-weight: 700; }
.toast-msg { line-height: 1.4; }

.toast-enter-active { animation: toast-in 0.3s ease; }
.toast-leave-active { animation: toast-out 0.25s ease; }
@keyframes toast-in { from { opacity: 0; transform: translateX(40px); } to { opacity: 1; transform: translateX(0); } }
@keyframes toast-out { from { opacity: 1; transform: translateX(0); } to { opacity: 0; transform: translateX(40px); } }
</style>

<style>.signed-user{padding:12px 16px 6px;font-size:13px}.signed-user small{display:block;color:var(--text3);font-size:11px;margin-top:4px}.logout-button{border:0;background:none;width:100%;cursor:pointer;text-align:left}</style>

<style scoped>
.nav-item.router-link-active > svg { color: var(--navigation-icon, var(--accent)); }
</style>

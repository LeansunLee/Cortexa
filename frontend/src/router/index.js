import { createRouter, createWebHistory } from 'vue-router'

import { auth, can, canAdmin, refreshAuth } from '../auth'
const routes = [
  { path: "/model-usage", component: () => import("../views/ModelUsage.vue"), meta: { superadmin: true } },
  { path: '/personalization', name: 'Personalization', component: () => import('../views/Personalization.vue') },
  { path: "/works", component: () => import("../views/Works.vue") },
  { path: "/works/:id", component: () => import("../views/Works.vue") },
  { path: '/login', component: () => import('../views/Login.vue') },
  { path: '/change-password', component: () => import('../views/Login.vue') },
  { path: '/my-agents', component: () => import('../views/MyAgents.vue'), meta: { permission: 'agent.use' } },
  { path: '/agent-operations/:agentId', name: 'AgentOperations', component: () => import('../views/AgentOperations.vue'), meta: { permission: 'agent.operate' } },
  { path: '/access', component: () => import('../views/AccessAdmin.vue'), meta: { admin: true } },
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('../views/Dashboard.vue')
  },
  {
    path: '/settings',
    name: 'Settings',
    meta: { permission: 'config.manage' },
    component: () => import('../views/Settings.vue')
  },
  {
    path: '/chat',
    name: 'Chat',
    meta: { permission: 'agent.use' },
    component: () => import('../views/Chat.vue')
  },
  {
    path: '/agents',
    name: 'Agents',
    meta: { permission: 'agent.read' },
    component: () => import('../views/Agents.vue')
  },
  {
    path: '/workflows',
    name: 'Workflows',
    meta: { permission: 'workflows.manage' },
    component: () => import('../views/Workflows.vue')
  },
  {
    path: '/tasks',
    name: 'Tasks',
    meta: { permission: 'tasks.manage' },
    component: () => import('../views/Tasks.vue')
  },
  {
    path: '/meetings',
    name: 'Meetings',
    meta: { permission: 'meeting.use' },
    component: () => import('../views/Meetings.vue')
  },
  {
    path: '/knowledge',
    name: 'Knowledge',
    meta: { anyPermissions: ['knowledge.manage', 'knowledge.use'] },
    component: () => import('../views/KnowledgeBases.vue')
  },
  {
    path: '/data-sources',
    name: 'DataSources',
    meta: { permission: 'data.manage' },
    component: () => import('../views/DataSources.vue')
  },
  {
    path: '/workspaces',
    name: 'Workspaces',
    component: () => import('../views/Workspaces.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach(async to => {
  if (!auth.loaded) await refreshAuth()
  if (!auth.user) return to.path === '/login' ? true : '/login'
  if (auth.user.must_change_password && to.path !== '/change-password') return '/change-password'
  if (to.path === '/login') return '/'
  if (to.meta.permission && !can(to.meta.permission)) return '/'
  if (to.meta.anyPermissions && !to.meta.anyPermissions.some(permission => can(permission))) return '/'
  if (to.meta.superadmin && !auth.user?.is_superadmin) return '/'
  if (to.meta.admin && !canAdmin()) return '/'
})
export default router

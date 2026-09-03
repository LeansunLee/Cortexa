import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('../views/Dashboard.vue')
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/Settings.vue')
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('../views/Chat.vue')
  },
  {
    path: '/agents',
    name: 'Agents',
    component: () => import('../views/Agents.vue')
  },
  {
    path: '/workflows',
    name: 'Workflows',
    component: () => import('../views/Workflows.vue')
  },
  {
    path: '/meetings',
    name: 'Meetings',
    component: () => import('../views/Meetings.vue')
  },
  {
    path: '/knowledge',
    name: 'Knowledge',
    component: () => import('../views/KnowledgeBases.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router

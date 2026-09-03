<template>
  <div class="app-layout">
    <aside class="sidebar">
      <div class="sidebar-brand">
        <span class="logo">🤖</span>
        <span class="brand-text">AgentDevStu</span>
      </div>
      <div class="sidebar-workspace">
        <select v-model="currentWorkspace" class="workspace-select" @change="onWorkspaceChange">
          <option value="">选择工作空间</option>
          <option v-for="ws in workspaces" :key="ws.id" :value="ws.id">{{ ws.name }}</option>
        </select>
      </div>
      <nav class="sidebar-nav">
        <router-link to="/" class="nav-item">
          <span class="nav-icon">📊</span>
          <span class="nav-text">首页</span>
        </router-link>
        <router-link to="/agents" class="nav-item">
          <span class="nav-icon">🤖</span>
          <span class="nav-text">智能体</span>
        </router-link>
        <router-link to="/workflows" class="nav-item">
          <span class="nav-icon">🔄</span>
          <span class="nav-text">工作流</span>
        </router-link>
        <router-link to="/meetings" class="nav-item">
          <span class="nav-icon">📋</span>
          <span class="nav-text">会议</span>
        </router-link>
        <router-link to="/knowledge" class="nav-item">
          <span class="nav-icon">📚</span>
          <span class="nav-text">知识库</span>
        </router-link>
        <router-link to="/chat" class="nav-item">
          <span class="nav-icon">💬</span>
          <span class="nav-text">对话</span>
        </router-link>
      </nav>
      <div class="sidebar-footer">
        <router-link to="/settings" class="nav-item">
          <span class="nav-icon">⚙️</span>
          <span class="nav-text">设置</span>
        </router-link>
      </div>
    </aside>
    <main class="main-content">
      <div class="page-content">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { workspaceApi } from './api'

const workspaces = ref([])
const currentWorkspace = ref(localStorage.getItem('currentWorkspace') || '')

const loadWorkspaces = async () => {
  try {
    const { data } = await workspaceApi.list()
    workspaces.value = data
    if (!currentWorkspace.value && data.length > 0) {
      currentWorkspace.value = data[0].id
      localStorage.setItem('currentWorkspace', data[0].id)
    }
  } catch (e) {
    console.error('Failed to load workspaces:', e)
  }
}

const onWorkspaceChange = () => {
  localStorage.setItem('currentWorkspace', currentWorkspace.value)
  window.dispatchEvent(new CustomEvent('workspace-changed', { detail: currentWorkspace.value }))
}

onMounted(() => {
  loadWorkspaces()
  window.addEventListener('workspace-changed', loadWorkspaces)
})
</script>

<style>
:root {
  --bg: #F7F7F5;
  --surface: #FFFFFF;
  --surface2: #FAFAF8;
  --text: #171717;
  --text2: #737373;
  --text3: #A3A3A3;
  --border: #E7E7E4;
  --primary: #111111;
  --primary-text: #FFFFFF;
  --primary-hover: #333333;
  --accent: #8B7EC8;
  --success: #4D7C0F;
  --success-bg: #F0FDF4;
  --danger: #B91C1C;
  --danger-bg: #FEF2F2;
  --radius: 12px;
  --radius-sm: 8px;
  --shadow: 0 1px 3px rgba(0,0,0,0.08);
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body { 
  background: var(--bg); 
  color: var(--text); 
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; 
}
a { text-decoration: none; color: inherit; }

.app-layout {
  display: flex;
  min-height: 100vh;
}
.sidebar {
  width: 260px;
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
  padding: 20px 24px;
  border-bottom: 1px solid var(--border);
}
.logo { font-size: 26px; }
.brand-text { font-weight: 700; font-size: 17px; color: var(--text); }
.sidebar-workspace {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.sidebar-workspace .workspace-select {
  width: 100%;
  padding: 8px 12px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--text);
}
.sidebar-nav {
  flex: 1;
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-radius: var(--radius-sm);
  text-decoration: none;
  color: var(--text2);
  font-size: 15px;
  font-weight: 500;
  transition: all 0.15s;
}
.nav-item:hover { background: var(--surface2); color: var(--text); }
.nav-item.router-link-active { background: var(--primary); color: var(--primary-text); }
.nav-icon { font-size: 20px; width: 28px; text-align: center; }
.sidebar-footer {
  padding: 16px 12px;
  border-top: 1px solid var(--border);
}
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.page-content {
  flex: 1;
  overflow-y: auto;
  padding: 32px 40px;
  max-width: 1600px;
  width: 100%;
}
</style>

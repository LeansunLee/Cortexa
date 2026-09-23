<template>
  <div class="agent-operations">
    <PageHeader>
      <button class="btn btn-ghost" @click="router.push('/my-agents')">返回我的 Agent</button>
      <button class="btn btn-ghost" :disabled="loading" @click="load"><RefreshCw :size="15" />刷新</button>
    </PageHeader>
    <p v-if="error" class="error notice" role="alert">{{ error }}</p>
    <p v-if="loading && !resources" class="empty">正在加载 Agent 资源…</p>
    <template v-if="resources">
      <div class="agent-heading"><AgentAvatar v-if="resources.agent.avatar" :avatar="resources.agent.avatar" /><Bot v-else :size="32" /><div><strong>{{ resources.agent.name }}</strong><p>{{ resources.agent.description || '管理此 Agent 的使用资源' }}</p></div></div>
      <p v-if="resources.agent.agent_type === 'proxy'" class="notice">Proxy Agent 的知识和工具由外部系统执行；此处维护的平台资源不会自动同步到外部服务。</p>
      <div class="resource-layout">
        <nav class="resource-nav" aria-label="资源类型">
          <div class="resource-nav-label">资源管理</div>
          <button v-for="item in tabs" :key="item.id" class="resource-nav-item" :class="{ active: tab === item.id }" :aria-pressed="tab === item.id" @click="tab = item.id">
            <span class="resource-nav-indicator"></span>
            <component :is="item.icon" :size="16" />
            <span>{{ item.label }}</span>
          </button>
        </nav>
        <AgentResources :key="agentId + revision" class="resource-content" :agent-id="agentId" :section="tab" />
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bot, RefreshCw, BookOpen, Wrench, Database, Brain } from 'lucide-vue-next'
import { agentOpsApi } from '../api'
import AgentAvatar from '../components/AgentAvatar.vue'
import AgentResources from '../components/AgentResources.vue'
const route = useRoute(), router = useRouter(), agentId = route.params.agentId
const resources = ref(null), loading = ref(false), error = ref(''), tab = ref('knowledge'), revision = ref(0)
const tabs = [{ id: 'knowledge', label: '知识库', icon: BookOpen }, { id: 'tools', label: '工具', icon: Wrench }, { id: 'data', label: '数据', icon: Database }, { id: 'memory', label: '记忆', icon: Brain }]
async function load() {
  loading.value = true; error.value = ''
  try { resources.value = (await agentOpsApi.summary(agentId)).data; revision.value++ }
  catch (e) { error.value = e.response?.data?.detail || '加载失败，请重试' }
  finally { loading.value = false }
}
onMounted(load)
</script>
<style scoped>
.agent-operations { width:100%; min-width:0; }
.agent-heading {display:flex;gap:14px;align-items:center;margin-bottom:20px}
.agent-heading > div {min-width:0;overflow-wrap:anywhere}.agent-heading > svg {flex-shrink:0}
.agent-heading :is(img, .agent-avatar-inline) {flex-shrink:0;width:48px;height:48px;border-radius:12px;object-fit:cover}
.agent-heading strong {font-size:18px;line-height:26px}.agent-heading p {font-size:13px;color:var(--text2);margin:4px 0 0;line-height:22px}
.resource-layout { display:flex; align-items:flex-start; gap:24px; min-width:0; }
.resource-nav { width:200px; padding:16px 12px; border:1px solid var(--border); border-radius:var(--radius-sm); background:var(--surface); flex:0 0 auto; }
.resource-nav-label { padding:0 12px; margin-bottom:6px; color:var(--text3); font-size:11px; font-weight:600; letter-spacing:.5px; }
.resource-nav-item { position:relative; display:flex; align-items:center; gap:10px; width:100%; padding:9px 12px; margin-bottom:2px; border:0; border-radius:var(--radius-sm); background:transparent; color:var(--text2); cursor:pointer; font:inherit; font-size:14px; text-align:left; transition:all var(--transition); }
.resource-nav-item:hover { background:var(--surface2); color:var(--text); }
.resource-nav-item.active { background:var(--primary-light); color:var(--primary); font-weight:600; }
.resource-nav-indicator { position:absolute; left:0; width:3px; height:0; border-radius:2px; background:var(--primary); transition:height var(--transition); }
.resource-nav-item.active .resource-nav-indicator { height:20px; }
.resource-content { flex:1 1 auto; min-width:0; }
.notice {padding:12px 16px;background:var(--surface2);border-radius:8px;margin-bottom:16px;font-size:13px}.error {color:var(--danger)}
.btn {white-space:nowrap;flex-shrink:0;line-height:20px}.notice {line-height:22px;overflow-wrap:anywhere}
@media(max-width:700px) {
  .resource-layout { display:block; }
  .resource-nav { display:flex; align-items:center; gap:4px; width:auto; padding:8px; margin-bottom:16px; overflow-x:auto; }
  .resource-nav-label { display:none; }
  .resource-nav-item { width:auto; flex:0 0 auto; gap:8px; padding:8px 10px; white-space:nowrap; }
  .resource-nav-indicator { left:8px; bottom:0; width:20px; height:0; }
  .resource-nav-item.active .resource-nav-indicator { height:3px; }
}
</style>

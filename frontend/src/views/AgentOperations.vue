<template>
  <div class="agent-operations">
    <PageHeader>
      <button class="btn btn-ghost" @click="router.push('/my-agents')">返回我的 Agent</button>
      <button class="btn btn-ghost" :disabled="loading" @click="load"><RefreshCw :size="15" />刷新</button>
    </PageHeader>
    <p v-if="error" class="error notice" role="alert">{{ error }}</p>
    <p v-if="loading && !resources" class="empty">正在加载 Agent 资源…</p>
    <template v-if="resources">
      <div class="agent-heading"><img v-if="resources.agent.avatar" :src="avatarUrl(resources.agent.avatar)" alt="" /><Bot v-else :size="32" /><div><strong>{{ resources.agent.name }}</strong><p>{{ resources.agent.description || '管理此 Agent 的使用资源' }}</p></div></div>
      <p v-if="resources.agent.agent_type === 'proxy'" class="notice">Proxy Agent 的知识和工具由外部系统执行；此处维护的平台资源不会自动同步到外部服务。</p>
      <nav class="resource-tabs" aria-label="资源类型"><button v-for="item in tabs" :key="item.id" class="btn btn-ghost" :class="{ active: tab === item.id }" :aria-pressed="tab === item.id" @click="tab = item.id"><component :is="item.icon" :size="16" />{{ item.label }}</button></nav>
      <AgentResources :key="agentId + revision" :agent-id="agentId" :section="tab" />
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bot, RefreshCw, BookOpen, Wrench, Database, Brain } from 'lucide-vue-next'
import { agentOpsApi } from '../api'
import { avatarUrl } from '../utils/avatar'
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
.agent-heading img {flex-shrink:0;width:48px;height:48px;border-radius:12px;object-fit:cover}
.agent-heading strong {font-size:18px;line-height:26px}.agent-heading p {font-size:13px;color:var(--text2);margin:4px 0 0;line-height:22px}
.resource-tabs {display:flex;flex-wrap:wrap;gap:12px;margin-bottom:20px}.resource-tabs .active {color:var(--primary);background:var(--primary-light);border-color:var(--primary)}
.notice {padding:12px 16px;background:var(--surface2);border-radius:8px;margin-bottom:16px;font-size:13px}.error {color:var(--danger)}
.btn {white-space:nowrap;flex-shrink:0;line-height:20px}.notice {line-height:22px;overflow-wrap:anywhere}
@media(max-width:700px) {.resource-tabs {gap:6px}.resource-tabs .btn {padding:8px 10px}}
</style>

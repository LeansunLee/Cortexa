<template><div class="my-agents"><PageHeader><button class="btn btn-ghost" :disabled="loading" @click="load"><RefreshCw :size="16" /> 刷新</button></PageHeader><p v-if="error" role="alert">{{ error }}</p><div v-if="loading" class="empty">正在加载…</div><div v-else-if="!agents.length" class="empty"><Bot :size="40" /><h3>还没有可用的 Agent</h3><p>请联系空间管理员分配 Agent，并确认它已发布。</p></div><div v-else class="agent-grid"><article v-for="a in agents" :key="a.id"><div class="agent-avatar"><img v-if="a.avatar?.startsWith('/')" :src="avatarUrl(a.avatar)" /><Bot v-else :size="28" /></div><h2>{{ a.name }}</h2><p>{{ a.description || '准备好与你一起工作。' }}</p><div class="agent-actions"><button class="btn btn-primary" :disabled="busy === a.id" @click="start(a)">对话 <ArrowUpRight :size="16" /></button><button v-if="can('agent.operate')" class="btn btn-ghost ops-button" @click="router.push('/agent-operations/' + a.id)"><Wrench :size="16" />运维</button></div></article></div></div></template>
<script setup>
import { can } from '../auth'
import { avatarUrl } from '../utils/avatar'
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Bot, ArrowUpRight, RefreshCw, Wrench } from 'lucide-vue-next'
import api, { conversationApi } from '../api'
const router = useRouter(), agents = ref([]), loading = ref(false), error = ref(''), busy = ref('')
async function load(){loading.value=true;error.value='';try{agents.value=(await api.get('/auth/agents')).data}catch(e){error.value=e.response?.data?.detail||'加载失败'}finally{loading.value=false}}
async function start(a){busy.value=a.id;try{const {data}=await conversationApi.create({agent_id:a.id,title:a.name});await router.push({path:'/chat',query:{conversation:data.id}})}catch(e){error.value=e.response?.data?.detail||'创建对话失败'}finally{busy.value=''}}
onMounted(load)
</script>
<style scoped>
.my-agents { width:100%; min-width:0; padding:0; }
.agent-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(min(270px,100%),1fr)); gap:20px; }
article { min-width:0; background:var(--surface); color:var(--text); border:1px solid var(--border); border-radius:var(--radius); padding:24px; display:flex; flex-direction:column; align-items:flex-start; }
article:hover { border-color:color-mix(in srgb,var(--primary) 35%,var(--border)); }
.agent-avatar { width:52px; height:52px; border-radius:12px; background:var(--primary-light); color:var(--primary); display:grid; place-items:center; margin-bottom:16px; }
.agent-avatar img { width:100%; height:100%; object-fit:cover; border-radius:12px; }
article h2 { margin:0 0 8px; font-size:18px; line-height:26px; color:var(--text); overflow-wrap:anywhere; max-width:100%; }
article p { margin:0 0 20px; font-size:13px; line-height:22px; color:var(--text2); flex:1; overflow-wrap:anywhere; max-width:100%; }
.agent-actions { display:flex; gap:10px; width:100%; }
.agent-actions .btn { flex:1; min-width:0; justify-content:center; white-space:nowrap; padding:9px 12px; line-height:20px; }
.agent-actions svg { flex-shrink:0; }
.empty { padding:48px 20px; text-align:center; color:var(--text2); font-size:13px; line-height:22px; }
.empty h3 { margin:16px 0 8px; color:var(--text); }
@media(max-width:700px) { article { padding:20px; }.agent-grid { gap:16px; } }
</style>

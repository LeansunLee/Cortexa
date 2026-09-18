<template>
  <div class="knowledge-page">
    <PageHeader>
        <button v-if="can('knowledge.manage')" class="btn btn-primary btn-page-action" @click="showCreate = true"><Plus :size="16" />创建知识库</button>
      </PageHeader>
    <div v-if="!loading && !loadError && knowledgeBases.length" class="knowledge-summary">
      <span>共 {{ knowledgeBases.length }} 个知识库</span>
      <span class="scope-badge">当前工作空间共享</span>
    </div>
    <div v-if="loading" class="empty-state">正在加载知识库…</div>
    <div v-else-if="loadError" class="empty-state">{{ loadError }} <button @click="loadKBs">重试</button></div>
    <div v-else-if="!knowledgeBases.length" class="empty-state"><BookOpen :size="40" /><h3>构建团队的知识空间</h3><p>创建知识库，上传产品手册、业务资料或常见问题。</p><button class="btn btn-primary" @click="showCreate = true">创建第一个知识库</button></div>
    <div v-else class="kb-list"><KnowledgeBaseCard v-for="kb in knowledgeBases" :key="kb.id" :kb="kb" :can-manage="can('knowledge.manage')" :can-use="can('knowledge.use')" @deleted="removeKB" /></div>
    <Teleport v-if="pageTabActive" to="body"><div v-if="showCreate" class="create-overlay" @click.self="!creating && (showCreate = false)" @keydown.esc="!creating && (showCreate = false)"><form class="create-dialog" role="dialog" aria-modal="true" aria-labelledby="create-kb-title" @submit.prevent="createKB"><h3 id="create-kb-title">创建空间知识库</h3><p>同一工作空间的 Agent 可以共享此知识库。</p><label>知识库名称<input v-model="newName" autofocus maxlength="100" placeholder="例如：产品文档、业务手册" required /></label><label>描述（选填）<textarea v-model="newDesc" rows="3" placeholder="描述资料范围，方便团队查找" /></label><div class="create-actions"><button type="button" class="btn btn-ghost" :disabled="creating" @click="showCreate = false">取消</button><button type="submit" class="btn btn-primary" :disabled="creating || !newName.trim()">{{ creating ? '创建中…' : '创建知识库' }}</button></div></form></div></Teleport>
  </div>
</template>
<script setup>
import { inject as injectPageTab } from 'vue'
const pageTabActive = injectPageTab('pageTabActive', true)

import { ref, onMounted, onBeforeUnmount } from 'vue'
import { BookOpen, Plus } from 'lucide-vue-next'
import { knowledgeApi } from '../api'
import { can } from '../auth'
import KnowledgeBaseCard from '../components/knowledge/KnowledgeBaseCard.vue'
const knowledgeBases = ref([]), loading = ref(true), loadError = ref(''), showCreate = ref(false), newName = ref(''), newDesc = ref(''), creating = ref(false)
const toast = (message, type = 'success') => window.dispatchEvent(new CustomEvent('toast', { detail: { message, type } }))
let loadId = 0
async function loadKBs() {
  const id = ++loadId
  loading.value = true; loadError.value = ''
  try { const { data } = await knowledgeApi.list({ scope: 'workspace' }); if (id === loadId) knowledgeBases.value = data }
  catch (e) { if (id === loadId) loadError.value = '知识库加载失败，请重试' }
  finally { if (id === loadId) loading.value = false }
}
async function createKB() {
  if (!newName.value.trim() || creating.value) return
  creating.value = true
  try {
    const { data } = await knowledgeApi.create({ name: newName.value.trim(), description: newDesc.value.trim() || null })
    knowledgeBases.value.unshift(data); newName.value = ''; newDesc.value = ''; showCreate.value = false; toast('知识库已创建')
  } catch (e) { toast('创建失败：' + (e.response?.data?.detail || e.message), 'error') }
  finally { creating.value = false }
}
const removeKB = id => knowledgeBases.value = knowledgeBases.value.filter(kb => kb.id !== id)
onMounted(() => { loadKBs(); window.addEventListener('workspace-changed', loadKBs) })
onBeforeUnmount(() => { loadId++; window.removeEventListener('workspace-changed', loadKBs) })
</script>
<style scoped>
.knowledge-page { width: 100%; min-width: 0; margin: 0; padding: 0; }
.knowledge-summary {
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 8px 16px; margin-bottom: 16px;
  color: var(--text2); font-size: 13px; line-height: 20px;
}
.scope-badge { color: var(--text3); font-size: 12px; }
.kb-list { display: flex; flex-direction: column; gap: 20px; }
.empty-state{text-align:center;padding:70px 20px;border:1px dashed var(--border,#ddd);border-radius:14px;color:var(--text3,#64748b);font-size:14px}.empty-state h3{font-size:18px;color:var(--text,#334155)}.empty-state p{margin-bottom:24px}.create-overlay{position:fixed;inset:0;z-index:2500;background:#10182880;display:grid;place-items:center;padding:20px}.create-dialog{width:460px;max-width:100%;box-sizing:border-box;background:var(--surface,#fff);color:var(--text,#334155);padding:26px;border-radius:16px;box-shadow:0 20px 70px #0003}.create-dialog h3{font-size:18px;margin:0 0 8px}.create-dialog p{font-size:12px;color:var(--text3,#64748b);margin-bottom:24px}.create-dialog label{display:flex;flex-direction:column;gap:8px;font-size:13px;margin-bottom:18px}.create-dialog input,.create-dialog textarea{font:inherit;border:1px solid var(--border,#ddd);border-radius:8px;padding:10px;background:var(--surface2,#f8fafc);color:inherit;resize:vertical}.create-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:24px}button:disabled{opacity:.5;cursor:default}.spin{animation:spin 1s linear infinite}@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
</style>

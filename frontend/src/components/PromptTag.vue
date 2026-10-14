<template>
  <button ref="trigger" type="button" class="prompt-tag" :title="`${prompt.agent_name || 'Agent'} · ${prompt.kind === 'model' ? '模型请求' : '协作请求'}`" @click="open">Prompt</button>
  <Teleport to="body">
    <dialog ref="dialog" class="dialog prompt-dialog" :aria-labelledby="`prompt-title-${prompt.id}`" @close="reset" @click="outside">
      <header><div><h3 :id="`prompt-title-${prompt.id}`">{{ prompt.agent_name || 'Agent' }} · Prompt</h3><p>{{ prompt.kind === 'model' ? '实际发送给模型的请求' : '实际传给协作 Agent 的请求' }}</p></div><button type="button" class="btn btn-ghost" aria-label="关闭提示词" @click="dialog.close()"><X :size="18" /></button></header>
      <div class="prompt-content">
        <p v-if="loading" role="status">正在读取提示词…</p>
        <p v-else-if="error" role="alert">{{ error }} <button class="btn btn-ghost btn-sm" @click="load">重试</button></p>
        <template v-else-if="data">
          <template v-if="data.request.messages">
            <section v-for="(message, index) in data.request.messages" :key="index"><span class="role">{{ message.role }}</span><pre>{{ render(message.content) }}</pre><pre v-if="message.tool_calls?.length">{{ render(message.tool_calls) }}</pre><small v-if="message.tool_call_id">{{ message.tool_call_id }}</small></section>
            <details v-if="data.request.tools?.length"><summary>工具定义 · {{ data.request.tools.length }}</summary><pre>{{ render(data.request.tools) }}</pre></details>
            <details v-if="Object.keys(data.request.parameters || {}).length"><summary>调用参数</summary><pre>{{ render(data.request.parameters) }}</pre></details>
          </template>
          <pre v-else>{{ render(data.request) }}</pre>
        </template>
      </div>
    </dialog>
  </Teleport>
</template>
<script setup>
import { ref, onBeforeUnmount } from 'vue'
import { X } from 'lucide-vue-next'
import api from '../api'
const props = defineProps({ prompt: { type: Object, required: true }, conversationId: String })
const dialog = ref(null), trigger = ref(null), loading = ref(false), error = ref(''), data = ref(null)
let generation = 0
const render = value => typeof value === 'string' ? value : JSON.stringify(value, null, 2)
const load = async () => {
  const current = ++generation
  loading.value = true; error.value = ''; data.value = null
  try {
    const result = await api.get(`/conversations/${props.conversationId}/prompts/${props.prompt.id}`)
    if (current === generation) data.value = result.data
  } catch (e) { if (current === generation) error.value = e.response?.data?.detail || '读取失败，请重试' }
  finally { if (current === generation) loading.value = false }
}
const open = () => { dialog.value.showModal(); load() }
const reset = () => { generation++; data.value = null; error.value = ''; loading.value = false; trigger.value?.focus() }
const outside = event => { const r = dialog.value.getBoundingClientRect(); if (event.target === dialog.value && (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom)) dialog.value.close() }
onBeforeUnmount(() => { generation++; dialog.value?.close() })
</script>
<style scoped>
.prompt-tag{display:inline-flex;align-items:center;padding:2px 7px;border:1px solid color-mix(in srgb,var(--primary) 40%,transparent);border-radius:6px;background:color-mix(in srgb,var(--primary) 12%,var(--surface));color:var(--primary);font-size:11px;font-weight:600;line-height:1.4;cursor:pointer;flex-shrink:0}.prompt-tag:hover{background:color-mix(in srgb,var(--primary) 20%,var(--surface))}.prompt-tag:focus-visible{outline:2px solid var(--primary);outline-offset:2px}
.prompt-dialog{box-sizing:border-box;margin:auto;width:min(840px,calc(100vw - 32px));max-height:85dvh;padding:0;border:1px solid var(--border);border-radius:18px;background:var(--surface-card,var(--surface));color:var(--text);box-shadow:0 20px 70px #0004;overflow:hidden}.prompt-dialog::backdrop{background:var(--dialog-overlay,var(--overlay));backdrop-filter:var(--glass-reading-backdrop,blur(8px));-webkit-backdrop-filter:var(--glass-reading-backdrop,blur(8px))}header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:18px 22px;border-bottom:1px solid var(--border)}h3{font-size:16px;margin:0}header p{font-size:12px;color:var(--text2);margin:5px 0 0}.prompt-content{max-height:calc(85dvh - 94px);overflow:auto;overscroll-behavior:contain;padding:20px 22px;background:var(--surface)}section{padding:12px 14px;border:1px solid var(--border);border-radius:10px;margin-bottom:12px}.role{display:inline-block;color:var(--primary);font-size:11px;font-weight:600;margin-bottom:8px}pre{font-family:ui-monospace,SFMono-Regular,monospace;font-size:12px;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere;margin:0}details{margin-top:14px}summary{cursor:pointer;font-size:12px;color:var(--text2);margin-bottom:10px}small{color:var(--text3)}@media(max-width:600px){header{padding:14px}.prompt-content{padding:14px}}
</style>

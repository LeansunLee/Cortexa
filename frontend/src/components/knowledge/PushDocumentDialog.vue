<template>
  <Teleport v-if="pageTabActive" to="body">
    <div class="push-overlay" @click.self="!busy && $emit('close')" @keydown.esc.stop="!busy && $emit('close')" @keydown.tab="trapFocus">
      <section ref="dialog" class="push-dialog" role="dialog" aria-modal="true" aria-labelledby="push-title">
        <h3 id="push-title">推送到空间知识库</h3>
        <p>将「{{ doc.name }}」复制到当前工作空间的公共库，独立库中的原文档会保留。公共库中的资料可供同空间 Agent 使用。</p>
        <div v-if="loading" class="hint">正在加载空间知识库…</div>
        <div v-else-if="loadError" class="error">{{ loadError }} <button @click="loadTargets">重试</button></div>
        <div v-else-if="!targets.length" class="hint">当前空间暂无空间知识库，请先在「空间知识库」页面创建。</div>
        <div v-else class="target-list">
          <label v-for="target in targets" :key="target.id" :class="{ selected: targetId === target.id }">
            <input type="radio" name="push-target" :checked="targetId === target.id" :disabled="busy" @change="targetId = target.id" />
            <span><strong>{{ target.name }}</strong><small v-if="target.description">{{ target.description }}</small></span>
          </label>
        </div>
        <div v-if="pushError" class="error">{{ pushError }}</div>
        <div class="push-actions"><button ref="cancelButton" :disabled="busy" @click="$emit('close')">取消</button><button class="primary" :disabled="busy || loading || !targetId" @click="push">{{ busy ? '推送中…' : '确认推送' }}</button></div>
      </section>
    </div>
  </Teleport>
</template>
<script setup>
import { inject as injectPageTab } from 'vue'
const pageTabActive = injectPageTab('pageTabActive', true)

import { ref, onMounted, onBeforeUnmount } from 'vue'
import { knowledgeApi } from '../../api'
const props = defineProps({ kb: Object, doc: Object })
const emit = defineEmits(['close', 'pushed'])
const targets = ref([]), targetId = ref(''), loading = ref(true), loadError = ref(''), pushError = ref(''), busy = ref(false), dialog = ref(null), cancelButton = ref(null)
let previousFocus, active = true
async function loadTargets() {
  loading.value = true; loadError.value = ''; targetId.value = ''
  try {
    const { data } = await knowledgeApi.list({ scope: 'workspace' })
    if (active) targets.value = data.filter(kb => !kb.agent_id && kb.workspace_id === props.kb.workspace_id)
  } catch { if (active) loadError.value = '加载空间知识库失败，请重试' }
  finally { if (active) loading.value = false }
}
async function push() {
  if (busy.value || !targetId.value) return
  busy.value = true; pushError.value = ''
  try {
    const response = await knowledgeApi.pushDoc(props.kb.id, props.doc.id, targetId.value)
    if (!active) return
    window.dispatchEvent(new CustomEvent('toast', { detail: { message: response.status === 200 ? '该文档已推送到所选公共库，无需重复推送' : '已推送到空间知识库，原文档已保留', type: 'success' } }))
    emit('pushed', targetId.value); emit('close')
  } catch (e) { if (active) pushError.value = e.response?.data?.detail || '推送失败，请重试' }
  finally { busy.value = false }
}
function trapFocus(event) {
  const elements = [...dialog.value.querySelectorAll('button:not(:disabled), input:not(:disabled)')]
  if (!elements.length) { event.preventDefault(); return }
  const index = elements.indexOf(document.activeElement)
  event.preventDefault(); elements[(index + (event.shiftKey ? -1 : 1) + elements.length) % elements.length]?.focus()
}
onMounted(() => { previousFocus = document.activeElement; cancelButton.value?.focus(); loadTargets() })
onBeforeUnmount(() => { active = false; previousFocus?.focus() })
</script>
<style scoped>
.push-overlay{position:fixed;inset:0;background:var(--overlay);z-index:3500;display:grid;place-items:center;padding:20px;backdrop-filter:blur(3px)}.push-dialog{width:500px;max-width:100%;box-sizing:border-box;border-radius:16px;padding:26px;background:var(--surface,#fff);color:var(--text,#334155);box-shadow:0 24px 70px #0003}.push-dialog h3{font-size:18px;margin:0 0 12px}.push-dialog p{font-size:13px;line-height:1.8;overflow-wrap:anywhere;color:var(--text3,#64748b)}.target-list{display:flex;flex-direction:column;gap:8px;max-height:280px;overflow:auto;margin:20px 0}.target-list label{display:flex;align-items:center;gap:10px;padding:12px;border:1px solid var(--border,#ddd);border-radius:8px;cursor:pointer}.target-list label.selected{border-color:var(--primary,#7c3aed);background:#7c3aed08}.target-list span{min-width:0;display:flex;flex-direction:column;gap:5px;overflow-wrap:anywhere}.target-list strong{font-size:13px}.target-list small{font-size:12px;color:var(--text3,#64748b)}.push-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:22px}button{font:inherit;font-size:13px;border:1px solid var(--border,#ddd);border-radius:8px;padding:9px 16px;background:transparent;color:inherit;cursor:pointer}.primary{background:var(--primary,#7c3aed);color:white;border-color:transparent}button:disabled{opacity:.5;cursor:default}.hint,.error{font-size:13px;padding:16px 0;line-height:1.8}.error{color:var(--danger)}.hint{color:var(--text3,#64748b)}
</style>

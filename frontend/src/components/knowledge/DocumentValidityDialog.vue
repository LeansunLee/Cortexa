<template>
  <Teleport to="body">
    <div class="validity-overlay" @click.self="!saving && $emit('close')" @keydown.esc="!saving && $emit('close')">
      <form class="validity-dialog" role="dialog" aria-modal="true" aria-labelledby="validity-title" @submit.prevent="save">
        <h3 id="validity-title">{{ expired ? '续期文档' : '设置文档有效期' }}</h3>
        <p class="document-title" :title="doc.name">{{ doc.name }}</p>
        <label class="option"><input v-model="mode" type="radio" value="forever" />永久有效</label>
        <label class="option"><input v-model="mode" type="radio" value="date" />有效至指定日期（含当天）</label>
        <label v-if="mode === 'date'" class="date-field">有效日期<input v-model="dateValue" type="date" required autofocus /></label>
        <p v-if="mode === 'date' && dateValue && dateValue < today" class="warning">该日期已经过去，保存后文件会立即标记为过期，并停止被 Agent 检索。</p>
        <p class="hint">过期文件仍可下载和在线预览，也可以随时续期。</p>
        <div class="actions"><button type="button" class="btn btn-ghost btn-sm" :disabled="saving" @click="$emit('close')">取消</button><button type="submit" class="btn btn-primary btn-sm save" :disabled="saving || (mode === 'date' && !dateValue)">{{ saving ? '保存中…' : '保存' }}</button></div>
      </form>
    </div>
  </Teleport>
</template>
<script setup>
import { ref, computed } from 'vue'
import { knowledgeApi } from '../../api'
const props = defineProps({ kbId: { type: String, required: true }, doc: { type: Object, required: true } })
const emit = defineEmits(['close', 'saved'])
const shanghaiDate = () => { const parts = Object.fromEntries(new Intl.DateTimeFormat('en', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date()).map(part => [part.type, part.value])); return `${parts.year}-${parts.month}-${parts.day}` }
const today = shanghaiDate()
const mode = ref(props.doc.valid_until ? 'date' : 'forever')
const dateValue = ref(props.doc.valid_until || today)
const expired = computed(() => Boolean(props.doc.valid_until && props.doc.valid_until < today))
const saving = ref(false)
const toast = (message, type = 'success') => window.dispatchEvent(new CustomEvent('toast', { detail: { message, type } }))
async function save() {
  if (saving.value || (mode.value === 'date' && !dateValue.value)) return
  saving.value = true
  try {
    const { data } = await knowledgeApi.updateDocValidity(props.kbId, props.doc.id, mode.value === 'forever' ? null : dateValue.value)
    emit('saved', data)
  } catch (error) { toast('有效期保存失败：' + (error.response?.data?.detail || '请重试'), 'error') }
  finally { saving.value = false }
}
</script>
<style scoped>
.validity-overlay{position:fixed;inset:0;z-index:2600;background:#10182880;display:grid;place-items:center;padding:20px}.validity-dialog{width:440px;max-width:100%;box-sizing:border-box;background:var(--surface,#fff);color:var(--text,#334155);padding:26px;border-radius:16px;box-shadow:0 20px 70px #0003}.validity-dialog h3{font-size:18px;margin:0 0 8px}.document-title{font-size:13px;color:var(--text3,#64748b);margin:0 0 22px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.option{display:flex;align-items:center;gap:9px;margin:14px 0;font-size:14px;cursor:pointer}.option input{accent-color:var(--primary,#6366f1)}.date-field{display:flex;flex-direction:column;gap:8px;margin:14px 0 0 26px;font-size:13px}.date-field input{font:inherit;border:1px solid var(--border,#ddd);border-radius:8px;padding:9px;background:var(--surface2,#f8fafc);color:inherit}.hint,.warning{font-size:12px;line-height:1.6;margin:16px 0 0}.hint{color:var(--text3,#64748b)}.warning{color:#d97706}.actions{display:flex;justify-content:flex-end;gap:10px;margin-top:24px}.actions button:disabled{opacity:.5;cursor:default}
</style>

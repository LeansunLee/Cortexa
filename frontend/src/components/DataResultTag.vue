<template>
  <button ref="trigger" type="button" class="data-tag" @click="open">查看数据</button>
  <Teleport to="body">
    <dialog ref="dialog" class="data-dialog" aria-label="本次查询结果" @close="reset" @click="outside">
      <header><div><h3>本次查询结果</h3><p>已保存的实际返回内容，不会重新执行查询</p></div><button type="button" class="btn btn-ghost" aria-label="关闭查询结果" @click="dialog.close()"><X :size="18" /></button></header>
      <div class="result-content">
        <p v-if="loading" role="status">正在读取数据…</p>
        <p v-else-if="error" role="alert">{{ error }} <button class="btn btn-ghost btn-sm" @click="load">重试</button></p>
        <template v-else-if="data">
          <p class="result-info">状态 {{ data.status }} · 实际返回 {{ data.returned_rows }} 条<span v-if="data.row_count != null"> · 查询报告 {{ data.row_count }} 条</span></p>
          <p v-if="data.truncated" class="notice">结果已截断，此处仅展示本次实际返回的记录，并非全部数据。</p>
          <p v-if="!data.returned_rows">本次查询没有返回记录。</p>
          <div v-else class="table-scroll"><table v-if="data.columns.length"><thead><tr><th>序号</th><th v-for="column in data.columns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(row, index) in data.rows" :key="index"><td>{{ offset + index + 1 }}</td><td v-for="column in data.columns" :key="column">{{ render(row[column]) }}</td></tr></tbody></table><pre v-else>{{ render(data.rows) }}</pre></div>
          <details v-if="data.rows.length"><summary>当前页 JSON</summary><pre>{{ JSON.stringify(data.rows, null, 2) }}</pre></details>
        </template>
      </div>
      <footer><span v-if="data?.returned_rows">{{ offset + 1 }}–{{ Math.min(offset + pageSize, data.returned_rows) }} / {{ data.returned_rows }}</span><div><button class="btn btn-ghost btn-sm" :disabled="loading || offset === 0" @click="page(-1)">上一页</button><button class="btn btn-ghost btn-sm" :disabled="loading || !data || offset + pageSize >= data.returned_rows" @click="page(1)">下一页</button></div></footer>
    </dialog>
  </Teleport>
</template>
<script setup>
import { ref, onBeforeUnmount } from 'vue'
import { X } from 'lucide-vue-next'
import api from '../api'
const props = defineProps({ actionId: String, conversationId: String })
const dialog = ref(null), trigger = ref(null), loading = ref(false), error = ref(''), data = ref(null), offset = ref(0)
const pageSize = 50
let generation = 0
const render = value => value == null ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value)
const load = async () => {
  const current = ++generation
  loading.value = true; error.value = ''; data.value = null
  try {
    const result = await api.get(`/conversations/${props.conversationId}/data-results/${props.actionId}`, { params: { offset: offset.value, limit: pageSize } })
    if (current === generation) data.value = result.data
  } catch (e) { if (current === generation) error.value = e.response?.data?.detail || '读取失败，请重试' }
  finally { if (current === generation) loading.value = false }
}
const open = () => { offset.value = 0; dialog.value.showModal(); load() }
const page = direction => { offset.value += direction * pageSize; load() }
const reset = () => { generation++; data.value = null; error.value = ''; loading.value = false; trigger.value?.focus() }
const outside = event => { const r = dialog.value.getBoundingClientRect(); if (event.target === dialog.value && (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom)) dialog.value.close() }
onBeforeUnmount(() => { generation++; dialog.value?.close() })
</script>
<style scoped>
.data-tag{padding:2px 7px;border:1px solid var(--primary);border-radius:6px;background:var(--surface2);color:var(--primary);font-size:11px;cursor:pointer}.data-tag:focus-visible{outline:2px solid var(--primary);outline-offset:2px}
.data-dialog{box-sizing:border-box;margin:auto;width:min(1080px,calc(100vw - 32px));max-height:85dvh;padding:0;border:1px solid var(--border);border-radius:18px;background:var(--surface-card,var(--surface));color:var(--text);box-shadow:0 20px 70px #0004;overflow:hidden}.data-dialog::backdrop{background:var(--dialog-overlay,var(--overlay));backdrop-filter:var(--glass-reading-backdrop,blur(8px));-webkit-backdrop-filter:var(--glass-reading-backdrop,blur(8px))}header,footer{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:16px 22px}header{border-bottom:1px solid var(--border)}h3{font-size:16px;margin:0}header p,.result-info,footer{font-size:12px;color:var(--text2)}header p{margin:5px 0 0}.result-content{max-height:calc(85dvh - 170px);overflow:auto;overscroll-behavior:contain;padding:16px 22px;background:var(--surface)}.table-scroll{overflow:auto;max-height:48dvh;border:1px solid var(--border);border-radius:8px}table{border-collapse:collapse;font-size:13px;min-width:100%}th,td{text-align:left;vertical-align:top;padding:9px 12px;border-bottom:1px solid var(--border);white-space:pre-wrap;min-width:100px;max-width:360px;overflow-wrap:anywhere}th{position:sticky;top:0;background:var(--surface2);font-weight:600}td:first-child,th:first-child{min-width:48px}tbody tr:hover{background:var(--surface2)}.notice{color:var(--primary);font-size:13px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.6}details{margin-top:12px}summary{cursor:pointer;color:var(--text2);font-size:12px}footer{border-top:1px solid var(--border)}footer div{margin-left:auto;display:flex;gap:8px}@media(max-width:600px){header,footer,.result-content{padding:14px}}
</style>

<template>
  <div v-show="!compact || items.length" class="upload-box" :class="{ dragging, compact }" @dragover.prevent="dragging = !busy" @dragleave.prevent="dragging = false" @drop.prevent="dropFiles">
    <input ref="picker" type="file" multiple hidden :disabled="busy" @change="chooseFiles" />
    <div v-if="!compact" class="upload-intro">
      <div class="upload-symbol"><UploadCloud :size="24" /></div>
      <div class="upload-copy"><strong>上传知识文件</strong></div>
    </div>
    <div v-if="items.length" class="queue" aria-live="polite">
      <div class="queue-summary"><strong>{{ busy ? '正在上传' : '上传结果' }}</strong><span>{{ succeeded }} 成功 / {{ failed }} 失败 / 共 {{ items.length }} 个</span><button v-if="!busy" @click="items = []">收起结果</button></div>
      <div class="total-track" role="progressbar" aria-label="整体上传进度" :aria-valuenow="overall" aria-valuemin="0" aria-valuemax="100"><i :style="{ width: overall + '%' }" /></div>
      <div class="queue-files">
        <div v-for="item in items" :key="item.id" class="queue-file">
          <FileText :size="16" /><div class="file-copy"><span :title="item.file.name">{{ item.file.name }}</span><small v-if="item.error" class="error">{{ item.error }}</small><div v-if="['uploading', 'processing'].includes(item.status)" class="file-track"><i :style="{ width: item.percent + '%' }" /></div></div>
          <span class="file-status" :class="item.status">{{ statusText(item) }}</span>
          <button v-if="item.status === 'failed' && item.retryable && !busy" @click="retry(item)">重试</button>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, computed, onBeforeUnmount } from 'vue'
import { UploadCloud, FileText } from 'lucide-vue-next'
import { knowledgeApi } from '../../api'
const props = defineProps({ kbId: { type: String, required: true }, folderId: { type: String, default: null }, compact: { type: Boolean, default: false } })
const emit = defineEmits(['uploaded', 'busy'])
const picker = ref(null), dragging = ref(false), busy = ref(false), items = ref([])
let sequence = 0, controller
function openPicker() { if (!busy.value) picker.value?.click() }
defineExpose({ openPicker })
const succeeded = computed(() => items.value.filter(i => i.status === 'success').length)
const failed = computed(() => items.value.filter(i => i.status === 'failed').length)
const overall = computed(() => {
  const total = items.value.reduce((n, i) => n + Math.max(i.file.size, 1), 0)
  return total ? Math.round(items.value.reduce((n, i) => n + Math.max(i.file.size, 1) * (['success', 'failed'].includes(i.status) ? 100 : Math.min(i.percent, 99)), 0) / total) : 0
})
const statusText = item => ({ waiting: '等待上传', uploading: `${item.percent}%`, processing: '服务器处理中…', success: '已上传', failed: '失败' }[item.status])
function chooseFiles(event) { enqueue(Array.from(event.target.files || [])); event.target.value = '' }
function dropFiles(event) { dragging.value = false; if (!busy.value) enqueue(Array.from(event.dataTransfer.files || [])) }
function enqueue(files) {
  if (!files.length || busy.value) return
  items.value = files.map(file => {
    const error = file.size > 500 * 1024 * 1024 ? '超过 500 MB 限制' : !file.size ? '不能上传空文件' : ''
    return { id: ++sequence, file, percent: 0, status: error ? 'failed' : 'waiting', error, retryable: !error }
  })
  runQueue()
}
async function retry(item) { item.status = 'waiting'; item.error = ''; item.percent = 0; await runQueue() }
async function runQueue() {
  busy.value = true; emit('busy', true)
  controller = new AbortController()
  try {
    for (const item of items.value.filter(i => i.status === 'waiting')) {
      item.status = 'uploading'
      try {
        await knowledgeApi.uploadFile(props.kbId, item.file, event => {
          const percent = event.total ? Math.round(event.loaded / event.total * 100) : 0
          item.percent = Math.min(100, percent)
          item.status = percent >= 100 ? 'processing' : 'uploading'
        }, controller.signal, props.folderId)
        item.percent = 100; item.status = 'success'; emit('uploaded')
      } catch (error) {
        if (controller.signal.aborted) break
        item.status = 'failed'
        item.error = error.response?.data?.detail || (error.code === 'ECONNABORTED' ? '请求超时，请先刷新文档列表确认是否已上传' : '网络或服务器异常，请重试')
      }
    }
  } finally { busy.value = false; emit('busy', false) }
}
onBeforeUnmount(() => controller?.abort())
</script>
<style scoped>
.upload-box.compact{margin-top:12px;padding:12px;border-style:solid;min-width:0}.compact .queue{margin:0;padding:0;border:0}
.upload-box{border:1px dashed var(--border,#cbd5e1);border-radius:12px;padding:18px;background:var(--surface2,#f8fafc);transition:.2s}.upload-box.dragging{border-color:var(--primary,#6366f1);background:#6366f112}.upload-intro{display:flex;align-items:center;gap:14px}.upload-symbol{color:var(--primary,#6366f1);background:#6366f110;width:46px;height:46px;display:grid;place-items:center;border-radius:12px;flex-shrink:0}.upload-copy{display:flex;flex-direction:column;gap:5px;flex:1;min-width:0}.upload-copy strong{font-size:14px}.upload-copy span,.upload-copy small{font-size:12px;color:var(--text3,#64748b);line-height:1.5}.queue{margin-top:16px;border-top:1px solid var(--border,#ddd);padding-top:14px}.queue-summary{display:flex;align-items:center;gap:10px;font-size:12px;margin-bottom:10px}.queue-summary span{color:var(--text3,#64748b)}.queue-summary button{margin-left:auto}.queue button{border:0;background:transparent;color:var(--primary,#6366f1);cursor:pointer;font-size:12px;white-space:nowrap}.total-track,.file-track{height:5px;background:var(--border,#e2e8f0);border-radius:8px;overflow:hidden}.total-track i,.file-track i{display:block;height:100%;background:var(--primary,#6366f1);transition:width .15s}.queue-files{max-height:230px;overflow:auto}.queue-file{display:flex;align-items:center;gap:10px;padding-top:12px;font-size:12px}.file-copy{flex:1;min-width:0;display:flex;flex-direction:column;gap:6px}.file-copy>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.file-status{font-size:11px;white-space:nowrap;color:var(--text3,#64748b)}.file-status.success{color:#16a34a}.file-status.failed,.error{color:#dc2626}.file-track{height:3px}.error{font-size:11px}@media(max-width:640px){.upload-intro{flex-wrap:wrap}.upload-symbol{display:none}.upload-copy{flex:1 1 auto;min-width:130px}.queue-summary{flex-wrap:wrap}}
</style>

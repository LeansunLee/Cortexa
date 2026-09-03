<template>
  <div class="meetings-page">
    <!-- Meeting List -->
    <div v-if="!viewingMeeting && !creatingMeeting">
      <div class="page-header">
        <div>
          <h1>AI 会议</h1>
          <p class="subtitle">召集 AI 智能体讨论议题、形成决策</p>
        </div>
        <button class="btn btn-primary" @click="creatingMeeting = true">+ 发起会议</button>
      </div>

      <div class="meeting-list" v-if="meetings.length > 0">
        <div v-for="m in meetings" :key="m.id" class="meeting-card" @click="viewMeeting(m.id)">
          <div class="meeting-card-header">
            <span :class="['status-badge', 'status-' + m.status]">{{ statusText(m.status) }}</span>
            <span class="meeting-time">{{ formatTime(m.created_at) }}</span>
          </div>
          <h3 class="meeting-title">{{ m.title || m.topic.substring(0, 50) }}</h3>
          <p class="meeting-topic">{{ m.topic }}</p>
          <div class="meeting-meta">
            <span>{{ purposeText(m.purpose) }}</span>
            <span>Round {{ m.current_round }}/{{ m.max_rounds }}</span>
          </div>
        </div>
      </div>
      <div v-else class="empty-state">
        <div class="empty-icon">📋</div>
        <p>暂无会议，点击上方按钮发起</p>
      </div>
    </div>

    <!-- Create Meeting -->
    <div v-else-if="creatingMeeting" class="meeting-create">
      <div class="page-header">
        <button class="btn btn-ghost" @click="creatingMeeting = false">← 返回</button>
        <h2>发起 AI 会议</h2>
      </div>

      <div class="create-form">
        <div class="form-group">
          <label>会议议题 *</label>
          <textarea v-model="createForm.topic" rows="4"
            placeholder="这次会议要讨论什么？例如：我们准备在明年进入东南亚市场，请评估是否应该进入"></textarea>
        </div>
        <div class="form-group">
          <label>会议标题（可选）</label>
          <input v-model="createForm.title" placeholder="例如：东南亚市场进入评估" />
        </div>
        <div class="form-group">
          <label>会议目标</label>
          <div class="purpose-options">
            <button v-for="p in purposes" :key="p.value" :class="['purpose-btn', { active: createForm.purpose === p.value }]"
              @click="createForm.purpose = p.value">
              {{ p.icon }} {{ p.label }}
            </button>
          </div>
        </div>
        <div class="form-group">
          <label>选择参会智能体 *</label>
          <div class="agent-checkboxes">
            <label v-for="a in agents" :key="a.id" class="agent-checkbox">
              <input type="checkbox" :value="a.id" v-model="createForm.participant_agent_ids" />
              <span class="agent-check-avatar">
                <img v-if="a.avatar && a.avatar.startsWith('/')" :src="a.avatar" />
                <span v-else>{{ a.avatar || '🤖' }}</span>
              </span>
              <div class="agent-check-info">
                <div class="agent-check-name">{{ a.name }}</div>
                <div class="agent-check-role">{{ a.role || '未设置角色' }}</div>
              </div>
            </label>
          </div>
          <div v-if="agents.length === 0" class="empty-hint">当前工作空间暂无智能体</div>
        </div>
        <div class="form-group">
          <label>主持人</label>
          <select v-model="createForm.host_agent_id">
            <option value="">自动选择（第一个参会者）</option>
            <option v-for="a in selectedAgents" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </div>
        <div class="form-group">
          <label>最大讨论轮次</label>
          <input type="number" v-model.number="createForm.max_rounds" min="1" max="5" />
        </div>
        <div class="form-group">
          <label>参考材料（可选）</label>
          <div class="upload-zone"
               @dragover.prevent
               @drop="handleDrop"
               @click="$refs.fileInput.click()">
            <input ref="fileInput" type="file" multiple accept=".txt,.md,.csv,.json,.pdf,.doc,.docx,.xlsx,.xls"
              style="display:none" @change="handleFileUpload" />
            <div v-if="uploading" class="upload-loading">
              <span class="spinner"></span>
              <span>{{ uploadProgress }}</span>
            </div>
            <div v-else class="upload-placeholder">
              <span class="upload-icon">📎</span>
              <span>点击或拖拽文件到此处上传</span>
              <span class="upload-hint">支持 txt、md、csv、json、pdf、doc、docx、xlsx 等格式</span>
            </div>
          </div>
          <div v-if="createForm.attachments.length > 0" class="attachment-list">
            <div v-for="(att, idx) in createForm.attachments" :key="idx" class="attachment-item">
              <span class="attachment-name">📄 {{ att.name }}</span>
              <span class="attachment-size">{{ (att.size / 1024).toFixed(1) }} KB</span>
              <button class="attachment-remove" @click="removeAttachment(idx)">✕</button>
            </div>
          </div>
        </div>
        <button class="btn btn-primary btn-lg" @click="submitMeeting" :disabled="!createForm.topic.trim() || createForm.participant_agent_ids.length === 0">
          开始会议
        </button>
      </div>
    </div>

    <!-- Meeting Detail -->
    <div v-else-if="viewingMeeting" class="meeting-detail">
      <div class="page-header">
        <button class="btn btn-ghost" @click="leaveMeeting">← 返回</button>
        <div>
          <h2>{{ meetingDetail?.title || meetingDetail?.topic?.substring(0, 40) }}</h2>
          <span :class="['status-badge', 'status-' + meetingDetail?.status]">{{ statusText(meetingDetail?.status) }}</span>
        </div>
        <button v-if="meetingDetail?.status === 'preparing'" class="btn btn-primary" @click="startMeeting">
          ▶ 开始会议
        </button>
        <button v-if="meetingDetail?.status === 'running'" class="btn btn-danger btn-sm" @click="cancelMeeting">
          取消会议
        </button>
      </div>

      <!-- Participants -->
      <div class="detail-participants" v-if="meetingDetail?.participants">
        <div v-for="p in meetingDetail.participants" :key="p.id" :class="['participant-chip', { host: p.is_host }]">
          <span>{{ p.is_host ? '👑' : '🤖' }}</span>
          {{ p.name }}
          <span v-if="p.is_host" class="host-badge">主持人</span>
        </div>
      </div>

      <!-- Messages (SSE real-time) -->
      <div class="detail-messages" ref="detailMessages">
        <div v-if="meetingMessages.length === 0 && meetingDetail?.status === 'preparing'" class="empty-hint">
          点击「开始会议」启动 AI 讨论
        </div>
        <div v-for="msg in meetingMessages" :key="msg.id || msg.tempId" :class="['msg-item', 'msg-' + msg.sender_type]">
          <div class="msg-header">
            <span class="msg-avatar">{{ msg.sender_type === 'host' ? '👑' : '🤖' }}</span>
            <span class="msg-sender">{{ msg.sender_name }}</span>
            <span v-if="msg.sender_type === 'host'" class="host-tag">主持人</span>
            <span class="msg-type-tag">{{ msgTypeText(msg.message_type) }}</span>
            <span class="msg-round">R{{ msg.round_number }}</span>
          </div>
          <div class="msg-content" v-html="formatMsg(msg.content)"></div>
        </div>
        <div v-if="isStreaming" class="msg-item msg-system">
          <div class="typing-indicator"><span></span><span></span><span></span></div>
          <span class="typing-text">{{ streamingStatus }}</span>
        </div>
      </div>

      <!-- Conclusion -->
      <div v-if="meetingConclusion" class="detail-conclusion">
        <h3>📋 会议结论</h3>
        <div class="conclusion-content" v-html="formatMsg(meetingConclusion.summary)"></div>
      </div>

      <!-- Todos -->
      <div v-if="meetingTodos.length > 0" class="detail-todos">
        <h3>✅ 待办事项</h3>
        <div v-for="t in meetingTodos" :key="t.id" class="todo-item">
          <div class="todo-priority" :class="'priority-' + t.priority">{{ t.priority === 'high' ? '🔴' : t.priority === 'medium' ? '🟡' : '🟢' }}</div>
          <div class="todo-info">
            <div class="todo-title">{{ t.title }}</div>
            <div class="todo-desc" v-if="t.description">{{ t.description }}</div>
          </div>
          <div class="todo-meta">
            <span v-if="t.assignee_name">👤 {{ t.assignee_name }}</span>
            <span v-if="t.due_date">📅 {{ t.due_date }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { meetingApi, agentApi } from '../api'

const agents = ref([])
const meetings = ref([])
const creatingMeeting = ref(false)
const viewingMeeting = ref(null)
const meetingDetail = ref(null)
const meetingMessages = ref([])
const meetingConclusion = ref(null)
const meetingTodos = ref([])
const isStreaming = ref(false)
const streamingStatus = ref('')
const detailMessages = ref(null)
let eventSource = null

const createForm = ref({
  topic: '', title: '', purpose: 'analysis',
  participant_agent_ids: [], host_agent_id: '', max_rounds: 3,
  attachments: []
})

const purposes = [
  { value: 'decision', icon: '🎯', label: '做决策' },
  { value: 'solution', icon: '💡', label: '制定方案' },
  { value: 'risk_assessment', icon: '⚠️', label: '风险评估' },
  { value: 'problem_solving', icon: '🔧', label: '解决问题' },
  { value: 'analysis', icon: '📊', label: '分析情况' },
]

const selectedAgents = computed(() =>
  agents.value.filter(a => createForm.value.participant_agent_ids.includes(a.id))
)

const currentWorkspace = () => localStorage.getItem('currentWorkspace')

const loadAgents = async () => {
  try { const { data } = await agentApi.list(currentWorkspace()); agents.value = data } catch {}
}
const loadMeetings = async () => {
  try { const { data } = await meetingApi.list(); meetings.value = data } catch {}
}

const uploading = ref(false)
const uploadProgress = ref('')

const handleFileUpload = async (event) => {
  const files = event.target.files
  if (!files || files.length === 0) return
  uploading.value = true
  for (const file of files) {
    uploadProgress.value = `正在上传 ${file.name}...`
    try {
      const { data } = await meetingApi.uploadFile(file)
      createForm.value.attachments.push(data)
    } catch (e) {
      alert('上传失败: ' + (e.response?.data?.detail || e.message))
    }
  }
  uploadProgress.value = ''
  uploading.value = false
  event.target.value = ''
}

const removeAttachment = (index) => {
  createForm.value.attachments.splice(index, 1)
}

const handleDrop = async (event) => {
  event.preventDefault()
  const files = event.dataTransfer.files
  if (!files || files.length === 0) return
  uploading.value = true
  for (const file of files) {
    uploadProgress.value = `正在上传 ${file.name}...`
    try {
      const { data } = await meetingApi.uploadFile(file)
      createForm.value.attachments.push(data)
    } catch (e) {
      alert('上传失败: ' + (e.response?.data?.detail || e.message))
    }
  }
  uploadProgress.value = ''
  uploading.value = false
}

const submitMeeting = async () => {
  try {
    const payload = { ...createForm.value }
    if (!payload.host_agent_id) delete payload.host_agent_id
    const { data } = await meetingApi.create(payload)
    await loadMeetings()
    creatingMeeting.value = false
    viewMeeting(data.id)
  } catch (e) { alert('创建失败: ' + (e.response?.data?.detail || e.message)) }
}

const viewMeeting = async (id) => {
  viewingMeeting.value = id
  try {
    const { data } = await meetingApi.detail(id)
    meetingDetail.value = data
    const { data: msgs } = await meetingApi.messages(id)
    meetingMessages.value = msgs
    const { data: conc } = await meetingApi.conclusion(id)
    meetingConclusion.value = conc
    const { data: todos } = await meetingApi.todos(id)
    meetingTodos.value = todos
  } catch (e) { console.error(e) }
  scrollToBottom()
}

const startMeeting = async () => {
  if (!viewingMeeting.value) return
  try {
    await meetingApi.start(viewingMeeting.value)
    meetingDetail.value.status = 'running'
    connectSSE(viewingMeeting.value)
  } catch (e) { alert('启动失败: ' + (e.response?.data?.detail || e.message)) }
}

const connectSSE = (meetingId) => {
  if (eventSource) eventSource.close()
  isStreaming.value = true
  streamingStatus.value = '会议启动中...'

  eventSource = new EventSource(`/api/meetings/${meetingId}/stream`)

  eventSource.onmessage = (e) => {
    const data = JSON.parse(e.data)
    handleSSEEvent(data)
  }

  eventSource.onerror = () => {
    isStreaming.value = false
    eventSource.close()
    eventSource = null
  }
}

const handleSSEEvent = (data) => {
  switch (data.type) {
    case 'start':
      streamingStatus.value = `会议开始，共 ${data.rounds} 轮`
      break
    case 'round_start':
      streamingStatus.value = `第 ${data.round} 轮：${data.topic}`
      break
    case 'agent_thinking':
      streamingStatus.value = `${data.agent} 正在分析...`
      break
    case 'agent_message':
      meetingMessages.value.push({
        tempId: Date.now() + Math.random(), round_number: data.round,
        sender_type: 'agent', sender_agent_id: data.agent_id,
        sender_name: data.agent, content: data.content,
        message_type: 'analysis', id: data.message_id,
      })
      streamingStatus.value = ''
      scrollToBottom()
      break
    case 'host_thinking':
      streamingStatus.value = `${data.agent}（主持人）正在汇总...`
      break
    case 'host_message':
      meetingMessages.value.push({
        tempId: Date.now() + Math.random(), round_number: data.round,
        sender_type: 'host', sender_agent_id: null,
        sender_name: data.agent, content: data.content,
        message_type: data.message_type, id: data.message_id,
      })
      streamingStatus.value = data.conflict ? '发现分歧，将进行下一轮讨论' : ''
      scrollToBottom()
      break
    case 'conclusion':
      meetingConclusion.value = { summary: data.content, key_decisions: [], disagreements: [] }
      streamingStatus.value = '正在生成待办事项...'
      break
    case 'todos':
      meetingTodos.value = data.items.map((t, i) => ({ ...t, id: i }))
      break
    case 'complete':
      isStreaming.value = false
      streamingStatus.value = ''
      meetingDetail.value.status = 'completed'
      if (eventSource) { eventSource.close(); eventSource = null }
      break
    case 'error':
      isStreaming.value = false
      streamingStatus.value = '❌ ' + data.error
      meetingDetail.value.status = 'failed'
      if (eventSource) { eventSource.close(); eventSource = null }
      break
  }
  scrollToBottom()
}

const cancelMeeting = async () => {
  if (!viewingMeeting.value) return
  try {
    await meetingApi.cancel(viewingMeeting.value)
    meetingDetail.value.status = 'cancelled'
    if (eventSource) { eventSource.close(); eventSource = null }
    isStreaming.value = false
  } catch (e) { console.error(e) }
}

const leaveMeeting = () => {
  if (eventSource) { eventSource.close(); eventSource = null }
  isStreaming.value = false
  viewingMeeting.value = null
  meetingDetail.value = null
  meetingMessages.value = []
  meetingConclusion.value = null
  meetingTodos.value = []
  loadMeetings()
}

const scrollToBottom = () => {
  nextTick(() => { if (detailMessages.value) detailMessages.value.scrollTop = detailMessages.value.scrollHeight })
}

const statusText = (s) => ({ preparing: '准备中', running: '进行中', completed: '已完成', failed: '失败', cancelled: '已取消' }[s] || s)
const purposeText = (p) => ({ decision: '🎯 做决策', solution: '💡 制定方案', risk_assessment: '⚠️ 风险评估', problem_solving: '🔧 解决问题', analysis: '📊 分析情况' }[p] || p)
const msgTypeText = (t) => ({ analysis: '分析', summary: '汇总', question: '追问', response: '回应', conclusion: '结论', system: '系统' }[t] || t)

const formatMsg = (c) => {
  if (!c) return ''
  return c.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>').replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/`(.*?)`/g, '<code>$1</code>')
}

const formatTime = (t) => {
  if (!t) return ''
  const d = new Date(t)
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

onMounted(() => { loadAgents(); loadMeetings() })
onUnmounted(() => { if (eventSource) eventSource.close() })

watch(() => createForm.value.participant_agent_ids, (ids) => {
  if (createForm.value.host_agent_id && !ids.includes(createForm.value.host_agent_id)) {
    createForm.value.host_agent_id = ''
  }
})
</script>

<style scoped>
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; gap: 16px; }
.page-header h1 { font-size: 24px; font-weight: 700; margin-bottom: 4px; }
.page-header h2 { font-size: 18px; font-weight: 600; margin: 0; }
.subtitle { font-size: 14px; color: var(--text2); }

.meeting-list { display: flex; flex-direction: column; gap: 12px; }
.meeting-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 16px 20px; cursor: pointer; transition: all 0.15s;
}
.meeting-card:hover { border-color: var(--primary); box-shadow: var(--shadow); }
.meeting-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.meeting-title { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
.meeting-topic { font-size: 13px; color: var(--text2); margin-bottom: 8px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.meeting-meta { display: flex; gap: 16px; font-size: 12px; color: var(--text3); }
.meeting-time { font-size: 12px; color: var(--text3); }

.status-badge { padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }
.status-preparing { background: #FEF3C7; color: #92400E; }
.status-running { background: #DBEAFE; color: #1E40AF; }
.status-completed { background: var(--success-bg); color: var(--success); }
.status-failed { background: var(--danger-bg); color: var(--danger); }
.status-cancelled { background: var(--surface2); color: var(--text3); }

/* Create */
.create-form { max-width: 700px; }
.form-group { margin-bottom: 20px; }
.form-group label { display: block; font-size: 14px; font-weight: 600; margin-bottom: 8px; }
.form-group textarea, .form-group input, .form-group select {
  width: 100%; padding: 12px 16px; background: var(--surface2); border: 1px solid var(--border);
  border-radius: var(--radius-sm); font-size: 14px; color: var(--text);
}
.form-group textarea:focus, .form-group input:focus, .form-group select:focus { outline: none; border-color: var(--primary); }

.purpose-options { display: flex; flex-wrap: wrap; gap: 8px; }
.purpose-btn {
  padding: 8px 16px; background: var(--surface2); border: 1px solid var(--border);
  border-radius: var(--radius-sm); font-size: 13px; cursor: pointer; transition: all 0.15s;
}
.purpose-btn:hover { border-color: var(--primary); }
.purpose-btn.active { background: var(--primary); color: var(--primary-text); border-color: var(--primary); }

.agent-checkboxes { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.agent-checkbox {
  display: flex; align-items: center; gap: 10px; padding: 10px 12px;
  background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius-sm);
  cursor: pointer; transition: all 0.15s;
}
.agent-checkbox:hover { border-color: var(--primary); }
.agent-checkbox input { accent-color: var(--primary); }
.agent-check-avatar { font-size: 18px; }
.agent-check-avatar img { width: 24px; height: 24px; border-radius: 50%; object-fit: cover; }
.agent-check-name { font-size: 13px; font-weight: 500; }
.agent-check-role { font-size: 11px; color: var(--text3); }

.btn-lg { padding: 14px 32px; font-size: 15px; }

/* Detail */
.detail-participants { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
.participant-chip {
  display: flex; align-items: center; gap: 6px; padding: 6px 12px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 20px;
  font-size: 13px;
}
.participant-chip.host { border-color: #F59E0B; background: #FFFBEB; }
.host-badge { font-size: 10px; background: #F59E0B; color: #fff; padding: 1px 6px; border-radius: 8px; }

.detail-messages {
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 16px; min-height: 300px; max-height: 500px; overflow-y: auto;
  display: flex; flex-direction: column; gap: 12px; margin-bottom: 16px;
}

.msg-item { padding: 12px 16px; border-radius: var(--radius-sm); }
.msg-agent { background: #F0F9FF; border-left: 3px solid #3B82F6; }
.msg-host { background: #FFFBEB; border-left: 3px solid #F59E0B; }
.msg-system { background: var(--surface2); text-align: center; font-size: 13px; color: var(--text3); display: flex; align-items: center; justify-content: center; gap: 8px; }
.msg-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 12px; }
.msg-avatar { font-size: 16px; }
.msg-sender { font-weight: 600; color: var(--text); }
.msg-type-tag { padding: 1px 6px; background: var(--surface2); border-radius: 4px; font-size: 10px; color: var(--text3); }
.msg-round { color: var(--text3); font-size: 11px; }
.host-tag { font-size: 10px; background: #F59E0B; color: #fff; padding: 1px 6px; border-radius: 8px; }
.msg-content { font-size: 14px; line-height: 1.7; }

.typing-indicator { display: flex; gap: 4px; }
.typing-indicator span { width: 5px; height: 5px; background: var(--text3); border-radius: 50%; animation: bounce 1.4s infinite ease-in-out; }
.typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
.typing-indicator span:nth-child(2) { animation-delay: -0.16s; }
@keyframes bounce { 0%, 80%, 100% { transform: scale(0); } 40% { transform: scale(1); } }
.typing-text { font-size: 13px; }

.detail-conclusion, .detail-todos { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; margin-bottom: 16px; }
.detail-conclusion h3, .detail-todos h3 { font-size: 15px; font-weight: 600; margin-bottom: 12px; }
.conclusion-content { font-size: 14px; line-height: 1.7; }

.todo-item { display: flex; align-items: flex-start; gap: 12px; padding: 12px; background: var(--surface2); border-radius: var(--radius-sm); margin-bottom: 8px; }
.todo-priority { font-size: 16px; flex-shrink: 0; }
.todo-info { flex: 1; }
.todo-title { font-size: 14px; font-weight: 500; }
.todo-desc { font-size: 12px; color: var(--text3); margin-top: 4px; }
.todo-meta { display: flex; gap: 12px; font-size: 12px; color: var(--text3); white-space: nowrap; }

.empty-state { text-align: center; padding: 80px 20px; color: var(--text3); }
.empty-icon { font-size: 48px; margin-bottom: 16px; }
/* Upload */
.upload-zone {
  border: 2px dashed var(--border);
  border-radius: var(--radius-sm);
  padding: 24px;
  text-align: center;
  cursor: pointer;
  transition: all 0.15s;
}
.upload-zone:hover { border-color: var(--primary); background: var(--surface2); }
.upload-placeholder { display: flex; flex-direction: column; align-items: center; gap: 6px; color: var(--text2); font-size: 14px; }
.upload-icon { font-size: 24px; }
.upload-hint { font-size: 12px; color: var(--text3); }
.upload-loading { display: flex; align-items: center; gap: 8px; justify-content: center; color: var(--text2); font-size: 14px; }
.spinner { width: 16px; height: 16px; border: 2px solid var(--border); border-top-color: var(--primary); border-radius: 50%; animation: spin 0.6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.attachment-list { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; }
.attachment-item { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: var(--surface2); border-radius: var(--radius-sm); font-size: 13px; }
.attachment-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.attachment-size { color: var(--text3); font-size: 12px; white-space: nowrap; }
.attachment-remove { background: none; border: none; color: var(--text3); cursor: pointer; font-size: 14px; padding: 2px 6px; border-radius: 4px; }
.attachment-remove:hover { background: var(--danger-bg); color: var(--danger); }

.empty-hint { text-align: center; color: var(--text3); font-size: 13px; padding: 20px; }

.btn { display: inline-flex; align-items: center; gap: 6px; padding: 10px 20px; border: none; border-radius: var(--radius-sm); font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.15s; }
.btn-primary { background: var(--primary); color: var(--primary-text); }
.btn-primary:hover { background: var(--primary-hover); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-ghost { background: transparent; color: var(--text2); border: 1px solid var(--border); }
.btn-ghost:hover { background: var(--surface2); }
.btn-danger { background: var(--danger-bg); color: var(--danger); border: 1px solid rgba(185,28,28,0.2); }
.btn-sm { padding: 6px 14px; font-size: 13px; }
</style>

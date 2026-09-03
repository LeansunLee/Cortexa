<template>
  <div class="chat-layout">
    <!-- Left Sidebar -->
    <div class="chat-sidebar">
      <div class="sidebar-header">
        <h3>对话</h3>
        <button class="btn btn-primary btn-sm" @click="showNewChat = true">+ 新建</button>
      </div>

      <!-- New Chat Modal -->
      <div v-if="showNewChat" class="new-chat-form">
        <div class="form-group">
          <label>选择智能体</label>
          <select v-model="newChatAgentId" class="form-select">
            <option value="">无智能体（通用对话）</option>
            <option v-for="a in agents" :key="a.id" :value="a.id">{{ a.avatar && a.avatar.startsWith('/') ? '🤖' : (a.avatar || '🤖') }} {{ a.name }}</option>
          </select>
        </div>
        <div class="form-group">
          <label>对话标题（可选）</label>
          <input v-model="newChatTitle" placeholder="例如：需求讨论" class="form-input" @keydown.enter="createChat" />
        </div>
        <div class="new-chat-actions">
          <button class="btn btn-ghost btn-sm" @click="showNewChat = false">取消</button>
          <button class="btn btn-primary btn-sm" @click="createChat">创建</button>
        </div>
      </div>

      <!-- Conversation List -->
      <div class="conv-list" v-else>
        <div v-if="conversations.length === 0" class="conv-empty">暂无对话</div>
        <div v-for="conv in conversations" :key="conv.id"
          :class="['conv-item', { active: currentConvId === conv.id }]"
          @click="selectConversation(conv.id)">
          <div class="conv-avatar">{{ conv.agent_name ? '🤖' : '💬' }}</div>
          <div class="conv-info">
            <div class="conv-title">{{ conv.title || conv.agent_name || '新对话' }}</div>
            <div class="conv-meta">{{ conv.agent_name ? conv.agent_name + ' · ' : '' }}{{ formatTime(conv.created_at) }}</div>
          </div>
          <button class="conv-delete" @click.stop="deleteConversation(conv.id)" title="删除">×</button>
        </div>
      </div>
    </div>

    <!-- Main Chat Area -->
    <div class="chat-main">
      <!-- No conversation selected -->
      <div v-if="!currentConvId" class="chat-empty">
        <div class="empty-icon">💬</div>
        <p>选择一个对话或创建新对话</p>
      </div>

      <!-- Conversation active -->
      <template v-else>
        <div class="chat-header">
          <div class="chat-header-info">
            <span class="chat-agent-name" v-if="currentConvAgent">
              {{ currentConvAgent.avatar && currentConvAgent.avatar.startsWith('/') ? '' : (currentConvAgent.avatar || '🤖') }}
              <img v-if="currentConvAgent.avatar && currentConvAgent.avatar.startsWith('/')" :src="currentConvAgent.avatar" class="chat-agent-avatar" />
              {{ currentConvAgent.name }}
            </span>
            <span class="chat-conv-title" v-if="currentConvTitle">{{ currentConvTitle }}</span>
          </div>
        </div>

        <div class="chat-messages" ref="messagesContainer">
          <div v-if="messages.length === 0" class="chat-welcome">
            <div class="welcome-avatar" v-if="currentConvAgent">
              <img v-if="currentConvAgent.avatar && currentConvAgent.avatar.startsWith('/')" :src="currentConvAgent.avatar" />
              <span v-else>{{ currentConvAgent.avatar || '🤖' }}</span>
            </div>
            <h3>{{ currentConvAgent ? currentConvAgent.name : '通用对话' }}</h3>
            <p>{{ currentConvAgent?.description || '开始输入消息来对话' }}</p>
          </div>
          <div v-for="(msg, i) in messages" :key="i" :class="['message', 'message-' + msg.role]">
            <div class="message-avatar" v-if="msg.role === 'assistant'">
              <img v-if="currentConvAgent?.avatar && currentConvAgent.avatar.startsWith('/')" :src="currentConvAgent.avatar" />
              <span v-else>{{ currentConvAgent?.avatar || '🤖' }}</span>
            </div>
            <div class="message-body">
              <div class="message-content" v-html="formatMessage(msg.content)"></div>
            </div>
          </div>
          <div v-if="sending" class="message message-assistant">
            <div class="message-avatar"><span>🤖</span></div>
            <div class="message-body">
              <div class="typing-indicator"><span></span><span></span><span></span></div>
            </div>
          </div>
        </div>

        <div class="chat-input-area">
          <div class="chat-input-row">
            <textarea v-model="input" class="chat-input" placeholder="输入消息..."
              @keydown.enter.exact.prevent="sendMessage" rows="1" :disabled="sending"></textarea>
            <button class="chat-send" @click="sendMessage" :disabled="sending || !input.trim()">
              {{ sending ? '...' : '发送' }}
            </button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { conversationApi, agentApi } from '../api'

const agents = ref([])
const conversations = ref([])
const currentConvId = ref(null)
const messages = ref([])
const input = ref('')
const sending = ref(false)
const showNewChat = ref(false)
const newChatAgentId = ref('')
const newChatTitle = ref('')
const messagesContainer = ref(null)

const currentConv = computed(() => conversations.value.find(c => c.id === currentConvId.value))
const currentConvAgent = computed(() => {
  if (!currentConv.value?.agent_id) return null
  return agents.value.find(a => a.id === currentConv.value.agent_id)
})
const currentConvTitle = computed(() => currentConv.value?.title || '')

const currentWorkspace = () => localStorage.getItem('currentWorkspace')

const loadAgents = async () => {
  try {
    const { data } = await agentApi.list(currentWorkspace())
    agents.value = data
  } catch (e) { console.error(e) }
}

const loadConversations = async () => {
  try {
    const { data } = await conversationApi.list()
    conversations.value = data
  } catch (e) { console.error(e) }
}

const selectConversation = async (convId) => {
  currentConvId.value = convId
  messages.value = []
  try {
    const { data } = await conversationApi.messages(convId)
    messages.value = data
    scrollToBottom()
  } catch (e) { console.error(e) }
}

const createChat = async () => {
  try {
    const payload = {}
    if (newChatAgentId.value) payload.agent_id = newChatAgentId.value
    if (newChatTitle.value.trim()) payload.title = newChatTitle.value.trim()
    const { data } = await conversationApi.create(payload)
    await loadConversations()
    currentConvId.value = data.id
    messages.value = []
    showNewChat.value = false
    newChatAgentId.value = ''
    newChatTitle.value = ''
  } catch (e) {
    alert('创建失败: ' + (e.response?.data?.detail || e.message))
  }
}

const deleteConversation = async (convId) => {
  if (!confirm('确定删除此对话？')) return
  try {
    await conversationApi.delete(convId)
    if (currentConvId.value === convId) {
      currentConvId.value = null
      messages.value = []
    }
    await loadConversations()
  } catch (e) { console.error(e) }
}

const sendMessage = async () => {
  const text = input.value.trim()
  if (!text || sending.value || !currentConvId.value) return

  messages.value.push({ role: 'user', content: text })
  input.value = ''
  sending.value = true
  scrollToBottom()

  try {
    await conversationApi.sendMessage(currentConvId.value, { content: text })
    // Reload messages to get the assistant reply
    const { data } = await conversationApi.messages(currentConvId.value)
    messages.value = data
  } catch (e) {
    messages.value.push({ role: 'assistant', content: '❌ 发送失败: ' + (e.response?.data?.detail || e.message) })
  } finally {
    sending.value = false
    scrollToBottom()
  }
}

const scrollToBottom = () => {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

const formatMessage = (content) => {
  if (!content) return ''
  return content
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/`(.*?)`/g, '<code>$1</code>')
}

const formatTime = (t) => {
  if (!t) return ''
  const d = new Date(t)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

// Listen for workspace changes
onMounted(() => {
  loadAgents()
  loadConversations()
  window.addEventListener('workspace-changed', () => {
    currentConvId.value = null
    messages.value = []
    loadAgents()
    loadConversations()
  })
})
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: calc(100vh - 140px);
  gap: 0;
  margin: -32px;
}

/* Sidebar */
.chat-sidebar {
  width: 280px;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sidebar-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 16px 12px; border-bottom: 1px solid var(--border);
}
.sidebar-header h3 { font-size: 15px; font-weight: 600; margin: 0; }

.conv-list { flex: 1; overflow-y: auto; padding: 8px; }
.conv-empty { text-align: center; color: var(--text3); font-size: 13px; padding: 40px 16px; }

.conv-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: var(--radius-sm);
  cursor: pointer; transition: all 0.15s; position: relative;
}
.conv-item:hover { background: var(--surface2); }
.conv-item.active { background: var(--primary); color: var(--primary-text); }
.conv-item.active .conv-meta { color: rgba(255,255,255,0.7); }
.conv-item.active .conv-delete { color: rgba(255,255,255,0.7); }

.conv-avatar { font-size: 20px; flex-shrink: 0; }
.conv-info { flex: 1; min-width: 0; }
.conv-title { font-size: 13px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conv-meta { font-size: 11px; color: var(--text3); margin-top: 2px; }
.conv-delete {
  background: none; border: none; color: var(--text3); cursor: pointer;
  font-size: 16px; padding: 2px 6px; border-radius: 4px; opacity: 0;
  transition: opacity 0.15s;
}
.conv-item:hover .conv-delete { opacity: 1; }
.conv-delete:hover { color: var(--danger); }

/* New Chat Form */
.new-chat-form { padding: 16px; border-bottom: 1px solid var(--border); }
.new-chat-form .form-group { margin-bottom: 12px; }
.new-chat-form label { display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; color: var(--text2); }
.form-select, .form-input {
  width: 100%; padding: 8px 12px; background: var(--surface2); border: 1px solid var(--border);
  border-radius: var(--radius-sm); font-size: 13px; color: var(--text);
}
.form-select:focus, .form-input:focus { outline: none; border-color: var(--primary); }
.new-chat-actions { display: flex; gap: 8px; justify-content: flex-end; }

/* Main Chat */
.chat-main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.chat-empty {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; color: var(--text3);
}
.empty-icon { font-size: 56px; margin-bottom: 16px; }

.chat-header {
  padding: 12px 20px; border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.chat-header-info { display: flex; align-items: center; gap: 10px; }
.chat-agent-name { font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 6px; }
.chat-agent-avatar { width: 24px; height: 24px; border-radius: 50%; object-fit: cover; }
.chat-conv-title { font-size: 13px; color: var(--text3); }

.chat-messages {
  flex: 1; overflow-y: auto; padding: 20px;
  display: flex; flex-direction: column; gap: 16px;
}
.chat-welcome {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; color: var(--text3);
}
.chat-welcome h3 { font-size: 18px; color: var(--text); margin-top: 12px; }
.chat-welcome p { font-size: 14px; margin-top: 4px; }
.welcome-avatar { font-size: 48px; }

.message { display: flex; gap: 10px; max-width: 75%; }
.message-user { align-self: flex-end; flex-direction: row-reverse; }
.message-assistant { align-self: flex-start; }

.message-avatar {
  width: 32px; height: 32px; border-radius: 50%; background: var(--surface2);
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; flex-shrink: 0;
}
.message-avatar img { width: 100%; height: 100%; border-radius: 50%; object-fit: cover; }

.message-body {
  padding: 10px 14px; border-radius: var(--radius); font-size: 14px; line-height: 1.6;
}
.message-user .message-body { background: var(--primary); color: var(--primary-text); }
.message-assistant .message-body { background: var(--surface); border: 1px solid var(--border); }

.typing-indicator { display: flex; gap: 4px; padding: 4px 0; }
.typing-indicator span {
  width: 6px; height: 6px; background: var(--text3); border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out;
}
.typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
.typing-indicator span:nth-child(2) { animation-delay: -0.16s; }
@keyframes bounce { 0%, 80%, 100% { transform: scale(0); } 40% { transform: scale(1); } }

.chat-input-area { padding: 12px 20px; border-top: 1px solid var(--border); background: var(--surface); }
.chat-input-row { display: flex; gap: 10px; align-items: flex-end; }
.chat-input {
  flex: 1; padding: 12px 16px; background: var(--surface2); border: 1px solid var(--border);
  border-radius: var(--radius-sm); font-size: 14px; color: var(--text);
  resize: none; min-height: 42px; max-height: 120px;
}
.chat-input:focus { outline: none; border-color: var(--primary); }
.chat-send {
  padding: 12px 24px; background: var(--primary); color: var(--primary-text);
  border: none; border-radius: var(--radius-sm); font-size: 14px; font-weight: 600;
  cursor: pointer; height: 42px; transition: all 0.15s;
}
.chat-send:hover { background: var(--primary-hover); }
.chat-send:disabled { opacity: 0.5; cursor: not-allowed; }

.btn { display: inline-flex; align-items: center; gap: 4px; padding: 6px 14px; border: none; border-radius: var(--radius-sm); font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.15s; }
.btn-primary { background: var(--primary); color: var(--primary-text); }
.btn-primary:hover { background: var(--primary-hover); }
.btn-ghost { background: transparent; color: var(--text2); border: 1px solid var(--border); }
.btn-ghost:hover { background: var(--surface2); }
.btn-sm { padding: 5px 12px; font-size: 12px; }
</style>

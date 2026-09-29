<template>
  <div class="chat-page">
    <div class="chat-layout">
    <!-- Left Sidebar -->
    <div class="chat-sidebar">
      <div class="sidebar-header">
        <h2>历史对话</h2>
        <button class="btn btn-primary btn-sm sidebar-new-chat" @click="openNewChat"><AppIcon name="Plus" :size="14" />新建对话</button>
      </div>
      <div class="sidebar-search">
        <Search :size="14" />
        <input v-model="searchQuery" placeholder="搜索对话..." class="search-input" />
      </div>

      <!-- New Chat Modal -->
      <div v-if="showNewChat" class="new-chat-form">
        <h3>选择智能体</h3>
        <p v-if="agentsLoading" class="new-chat-hint">正在加载可用 Agent…</p>
        <p v-else-if="agentsError" class="new-chat-hint" role="alert">{{ agentsError }} <button type="button" @click="loadAgents">重试</button></p>
        <p v-else-if="!agents.length" class="new-chat-hint">暂无可用 Agent</p>
        <div v-else class="new-chat-agent-list" role="radiogroup" aria-label="选择智能体">
          <label v-for="agent in agents" :key="agent.id" class="new-chat-agent" :class="{ selected: newChatAgentId === agent.id }">
            <input v-model="newChatAgentId" type="radio" name="new-chat-agent" :value="agent.id" />
            <span class="new-chat-agent-avatar" aria-hidden="true"><AgentAvatar :avatar="agent.avatar || ''" /></span>
            <span class="new-chat-agent-name">{{ agent.name }}</span>
            <Check v-if="newChatAgentId === agent.id" :size="16" class="new-chat-agent-check" aria-hidden="true" />
          </label>
        </div>
        <div class="new-chat-actions">
          <button class="btn btn-ghost btn-sm" @click="closeNewChat">取消</button>
          <button class="btn btn-primary btn-sm" :disabled="!newChatAgentId || creatingChat" @click="createChat">{{ creatingChat ? '创建中…' : '创建' }}</button>
        </div>
      </div>

      <!-- Conversation List -->
      <div class="conv-list" v-else>
        <div v-if="conversationLoadError" class="conv-empty" role="alert">{{ conversationLoadError }} <button class="btn-cancel" @click="loadConversations">重试</button></div>
        <div v-else-if="conversations.length === 0" class="conv-empty">暂无对话</div>
        <div v-else-if="groupedConversations.length === 0" class="conv-empty">没有匹配的对话</div>
        <section v-for="group in groupedConversations" :key="group.key" class="conv-group">
          <button class="conv-group-heading" type="button" :aria-expanded="!isGroupCollapsed(group.key)" :aria-controls="`conv-group-${group.key}`" @click="toggleAgentGroup(group.key)">
            <ChevronDown :size="14" :class="['conv-group-chevron', { collapsed: isGroupCollapsed(group.key) }]" />
            <span class="conv-group-avatar" aria-hidden="true">
              <AgentAvatar v-if="group.avatar && group.avatar.startsWith('/')" :avatar="group.avatar" />
              <Bot v-else :size="15" />
            </span>
            <span class="conv-group-name" :title="group.name">{{ group.name }}</span>
            <span class="conv-group-count">{{ group.conversations.length }}</span>
          </button>
          <div :id="`conv-group-${group.key}`" v-show="!isGroupCollapsed(group.key)">
            <div v-for="conv in group.conversations" :key="conv.id"
              :class="['conv-item', { active: currentConvId === conv.id }]"
              @click="selectConversation(conv.id)">
              <div class="conv-info">
                <div class="conv-title-row" v-if="editingConvId !== conv.id || renameTarget !== 'sidebar'">
                  <span class="conv-status" aria-hidden="true"><Loader v-if="sessions[conv.id] && (sessions[conv.id].sending || sessions[conv.id].streaming)" :size="13" class="conv-spinner" /></span>
                  <button class="conv-title-text" type="button" :class="{ unread: sessions[conv.id]?.unread }" :aria-current="currentConvId === conv.id ? 'true' : undefined" :title="conv.title || conv.agent_name || '新对话'" @click.stop="selectConversation(conv.id)">{{ conv.title || conv.agent_name || '新对话' }}</button>
                </div>
                <input v-else class="conv-rename-input" v-model="renameTitle"
                  @click.stop @blur="saveRename(conv.id)" @keydown.enter="saveRename(conv.id)"
                  @keydown.escape="cancelRename" autofocus />
              </div>
              <button class="conv-more" type="button" :aria-label="`${conv.title || '新对话'}的更多操作`" aria-haspopup="menu" :aria-expanded="openConvMenuId === conv.id" @click.stop="toggleConversationMenu($event, conv.id)"><MoreHorizontal :size="17" /></button>
            </div>
          </div>
        </section>
      </div>
      <Teleport to="body">
        <div v-if="openConvMenuId" ref="conversationMenuRef" class="conv-action-menu" role="menu" :style="conversationMenuStyle" @click.stop>
          <button type="button" role="menuitem" @click="renameFromMenu"><Pencil :size="14" />重命名</button>
          <button type="button" role="menuitem" class="conv-action-danger" @click="deleteFromMenu"><Trash2 :size="14" />删除</button>
        </div>
      </Teleport>
    </div>

    <!-- Main Chat Area -->
    <div class="chat-main">
      <!-- No conversation selected -->
      <div v-if="!currentConvId" class="chat-empty">
        <div class="empty-state">
          <div class="empty-icon-wrap">
            <MessageSquare :size="32" />
          </div>
          <h3>选择一个对话</h3>
          <p>或创建新对话开始与智能体交互</p>
        </div>
      </div>

      <!-- Conversation active -->
      <template v-else>
        <div class="chat-header">
          <div class="chat-header-info">
            <div class="chat-agent-badge" v-if="currentConvAgent">
              <AgentAvatar v-if="currentConvAgent.avatar && currentConvAgent.avatar.startsWith('/')" :avatar="currentConvAgent.avatar" class="chat-agent-avatar" />
              <span v-else class="chat-agent-emoji"><AppIcon name="Bot" :size="20" /></span>
            </div>
            <div class="chat-header-text">
              <input v-if="editingConvId === currentConvId && renameTarget === 'header'" ref="headerRenameInput" v-model="renameTitle" class="chat-title-input" aria-label="对话标题" maxlength="200" @blur="saveRename(currentConvId)" @keydown.enter.prevent="saveRename(currentConvId)" @keydown.esc.stop="cancelRename" />
              <button v-else type="button" class="chat-conv-title" :title="`点击修改对话标题：${currentConvTitle}`" @click="startRename(currentConv, 'header')">{{ currentConvTitle }}</button>
              <span class="chat-agent-name">{{ currentConv?.agent_name || currentConvAgent?.name || '通用对话' }}</span>
              <span v-if="renameError" class="chat-rename-error" role="alert">{{ renameError }}</span>
            </div>
          </div>
          <button v-if="debugEnabled" :class="['debug-toggle', { active: showDebugPanel }]" type="button" @click="showDebugPanel = !showDebugPanel" :aria-pressed="showDebugPanel">
            <Bug :size="15" />
            <span>调试</span>
            <span v-if="debugEventCount" class="debug-count">{{ debugEventCount }}</span>
          </button>
        </div>

        <div class="chat-messages" ref="messagesContainer" @scroll="handleMessageScroll">
          <!-- Welcome -->
          <div v-if="messages.length === 0" class="chat-welcome">
            <div class="welcome-avatar" v-if="currentConvAgent">
              <AgentAvatar v-if="currentConvAgent.avatar && currentConvAgent.avatar.startsWith('/')" :avatar="currentConvAgent.avatar" />
              <span v-else><AppIcon name="Bot" :size="20" /></span>
            </div>
            <h3>{{ currentConvAgent ? currentConvAgent.name : '通用对话' }}</h3>
            <p>{{ currentConvAgent?.description || '开始输入消息来对话' }}</p>
          </div>

          <!-- Messages -->
          <template v-for="(msg, i) in messages" :key="msg.id || i">
            <!-- User Message -->
            <div v-if="msg.role === 'user'" v-show="!isCollaborationOnlyMessage(msg)" class="msg-row msg-row-user">
              <div class="msg-bubble-user">
                <div class="msg-content-user">{{ msg.content }}</div>
                <div v-if="msg.attachments?.length" class="msg-attachments">
                  <div v-for="(att, ai) in msg.attachments" :key="ai" class="msg-attachment-item">
                    <img v-if="att.type === 'image'" :src="att.url" class="msg-attachment-img" />
                    <div v-else class="msg-attachment-file">
                      <FileText :size="16" />
                      <span>{{ att.filename }}</span>
                      <span class="att-size">{{ formatFileSize(att.size) }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Assistant Message -->
            <div v-else :id="msg?.id ? `message-${msg.id}` : undefined" class="msg-row msg-row-assistant">
              <div class="msg-col-assistant">
                <details v-if="(msg._steps || msg.metadata_json?.steps)?.length" class="completed-process">
                  <summary>处理过程 · {{ (msg._steps || msg.metadata_json.steps).length }} 个步骤</summary>
                  <div v-for="(step, index) in (msg._steps || msg.metadata_json.steps)" :key="index" :class="['status-step', 'outcome-' + stepOutcome(step, index, msg._steps || msg.metadata_json.steps, false)]">
                    <span class="status-icon">
                      <AlertCircle v-if="stepOutcome(step, index, msg._steps || msg.metadata_json.steps, false) === 'error'" :size="14" aria-label="失败" />
                      <CheckCircle v-else :size="14" aria-label="完成" />
                    </span>
                    {{ cleanStatusText(step.message) }}
                  </div>
                </details>
                <!-- Collaboration Card (completed) -->
                <AgentCollaborationCard
                  v-if="msg._collabResults && msg._collabResults.length > 0"
                  :collabs="msg._collabResults"
                  :source-name="currentConvAgent?.name || ''"
                  :source-avatar="currentConvAgent?.avatar || 'Bot'"
                />
                <!-- Collaboration Card from metadata -->
                <AgentCollaborationCard
                  v-else-if="msg.metadata_json?.collaborations && msg.metadata_json.collaborations.length > 0"
                  :collabs="msg.metadata_json.collaborations"
                  :source-name="currentConvAgent?.name || ''"
                  :source-avatar="currentConvAgent?.avatar || 'Bot'"
                />

                <div class="msg-content-assistant" v-html="formatMessage(msg.content)"></div>
                <div v-if="msg.metadata_json?.stopped" class="preview-hint">已停止生成</div>

                <!-- Sources -->
                <div v-if="msg.metadata_json?.sources?.length" class="msg-sources">
                  <button class="sources-btn" @click="toggleSources(msg)">
                    <BookOpen :size="13" />
                    <span>参考 {{ msg.metadata_json.sources.length }} 个来源</span>
                    <ChevronDown :size="13" :class="['sources-chevron', { open: msg._sourcesExpanded }]" />
                  </button>
                  <div v-if="msg._sourcesExpanded" class="sources-panel">
                    <div v-for="(src, j) in msg.metadata_json.sources" :key="j" class="source-chip" @click="showSources(msg, j)">
                      <span v-if="src.type === 'knowledge_base'" class="source-chip-icon"><BookOpen :size="12" /></span>
                      <span v-else-if="src.type === 'data_source'" class="source-chip-icon"><Database :size="12" /></span>
                      <span v-else class="source-chip-icon"><Link :size="12" /></span>
                      <span class="source-chip-name">{{ src.name }}</span>
                    </div>
                  </div>
                </div>

                <WorkCandidates v-if="msg.id && msg.role === 'assistant'" :key="msg.id" :conversation-id="activeTabId" :message="msg" :auto-extract="i === messages.length - 1 && !sending && !streaming" />
                <!-- Actions (hover) -->
                <div class="msg-actions">
                  <span class="action-time" v-if="msg.created_at">{{ formatMessageTime(msg.created_at) }}</span>
                  <span class="usage-badge" :title="usageTitle(msg.metadata_json?.stats)"><span class="meta-sep" aria-hidden="true">·</span>{{ usageLabel(msg.metadata_json?.stats) }}</span>
                  <span class="action-meta" v-if="msg.metadata_json?.stats">
                    <template v-if="msg.metadata_json.stats.duration_ms"><span class="meta-sep">·</span>{{ formatDuration(msg.metadata_json.stats.duration_ms) }}</template>
                    <template v-if="msg.metadata_json.stats.model"><span class="meta-sep">·</span>{{ msg.metadata_json.stats.model }}</template>
                  </span>
                  <button class="action-btn" @click="copyMessage(msg.content, i)" title="复制">
                    <Check v-if="copiedIdx === i" :size="14" class="copy-ok" />
                    <Copy v-else :size="14" />
                  </button>
                  <button v-if="i === messages.length - 1 && msg.role === 'assistant' && !sending && !streaming" class="action-btn" @click="regenerateMessage(i)" title="重新生成">
                    <RefreshCw :size="14" />
                  </button>

                </div>
              </div>
            </div>
          </template>

          <!-- Collaboration Card (streaming) -->
          <div v-if="(curSession?.collabPending?.length > 0 || curSession?.collabResults?.length > 0) && streaming" class="msg-row msg-row-assistant">
            <div class="msg-col-assistant">
              <AgentCollaborationCard
                :collabs="curSession?.collabResults || []"
                :pending-collabs="curSession?.collabPending || []"
                :running="true"
                :source-name="currentConvAgent?.name || ''"
                :source-avatar="currentConvAgent?.avatar || 'Bot'"
              />
            </div>
          </div>

          <!-- Agent Status Panel -->
          <div v-if="(sending || streaming) && statusSteps.length > 0" class="msg-row msg-row-assistant">
            <div class="msg-col-assistant">
              <details class="agent-status-panel" :open="!streamContent">
                <summary>{{ statusSteps.at(-1)?.message || '处理过程' }} · 展开详情</summary>
                <div v-for="(step, idx) in statusSteps" :key="idx" :class="['status-step', 'outcome-' + stepOutcome(step, idx, statusSteps), { 'is-working': stepOutcome(step, idx, statusSteps) === 'running' }]">
                  <span class="status-icon">
                    <Loader v-if="stepOutcome(step, idx, statusSteps) === 'running'" :size="14" class="runtime-spinner" aria-label="进行中" />
                    <AlertCircle v-else-if="stepOutcome(step, idx, statusSteps) === 'error'" :size="14" aria-label="失败" />
                    <CheckCircle v-else :size="14" aria-label="完成" />
                  </span>
                  <span class="status-text">{{ cleanStatusText(step.message) }}</span>
                  <span v-if="step.detail" class="status-detail">{{ step.detail }}</span>
                </div>
              </details>
            </div>
          </div>
          <!-- Fallback thinking indicator (before first status) -->
          <div v-if="sending && statusSteps.length === 0 && !streamContent" class="msg-row msg-row-assistant">
            <div class="msg-col-assistant">
              <div class="thinking-indicator">
                <span class="thinking-dot"></span>
                <span class="thinking-dot"></span>
                <span class="thinking-dot"></span>
                <span class="thinking-label">思考中</span>
              </div>
            </div>
          </div>

          <!-- Streaming -->
          <div v-if="streaming && streamContent" class="msg-row msg-row-assistant">
            <div class="msg-col-assistant">              <div class="msg-content-assistant" v-html="formatMessage(streamContent)"></div>
              <span class="stream-cursor"></span>
            </div>
          </div>

          <!-- Error state -->
          <div v-if="streamError" class="msg-error-bar">
            <div class="msg-error-text">
              <AlertCircle :size="14" />
              <span>{{ streamError }}</span>
            </div>
            <button v-if="curSession?.unavailable" class="btn-retry-sm" @click="recoverConversation" :disabled="sending">新建对话继续</button>
            <button v-else class="btn-retry-sm" @click="retryMessage">
              <RefreshCw :size="12" /> 重试
            </button>
          </div>
        </div>

        <button v-if="hasNewContent" class="new-content-button" @click="scrollToBottom(true)">有新内容 ↓</button>

        <section v-if="curSession?.goal?.reason === 'collaboration_approval_required'" class="goal-panel" aria-label="协作授权">
          <div class="goal-approval">
            <p>请选择允许参与本次任务的智能体。</p>
            <label v-for="candidate in curSession.goalCandidates" :key="candidate.id" class="goal-candidate">
              <input type="checkbox" v-model="curSession.goalSelection" :value="candidate.id" :disabled="curSession.approvalBusy" />
              <span><strong>{{ candidate.name }}</strong><small>{{ candidate.description }}</small></span>
            </label>
            <p v-if="!curSession.goalCandidates.length">候选已不可用，可以拒绝并继续。</p>
            <button type="button" class="btn btn-primary btn-sm" :disabled="curSession.approvalBusy || sending || streaming" @click="approveGoal">{{ curSession.approvalBusy ? '正在保存…' : curSession.goalSelection.length ? '允许所选并继续' : '全部拒绝并继续' }}</button>
          </div>
        </section>
        <!-- Input Area -->
        <div class="chat-input-area" @dragover="handleDragOver" @dragleave="handleDragLeave" @drop="handleDrop">
          <!-- Drag overlay -->
          <div v-if="isDragging" class="chat-drop-overlay">
            <Paperclip :size="24" />
            <span>松开鼠标上传文件</span>
          </div>

          <!-- Pending file previews -->
          <div v-if="pendingFiles.length > 0" class="chat-attachments-preview">
            <div v-for="(entry, idx) in pendingFiles" :key="idx" class="attachment-preview-item">
              <img v-if="entry.preview" :src="entry.preview" class="attachment-thumb" />
              <div v-else class="attachment-file-icon">
                <FileText :size="20" />
              </div>
              <div class="attachment-info">
                <span class="attachment-name">{{ entry.file.name }}</span>
                <span class="attachment-size">{{ formatFileSize(entry.file.size) }}</span>
                <span v-if="entry.uploading" class="attachment-status">上传中...</span>
                <span v-else-if="entry.error" class="attachment-status error">{{ entry.error }}</span>
              </div>
              <button class="attachment-remove" @click="removePendingFile(idx)"><X :size="14" /></button>
            </div>
          </div>

          <p v-if="curSession?.draftError" class="msg-error-bar">{{ curSession.draftError }}</p>
          <div class="chat-input-wrap">
            <div v-if="currentConvAgent?.agent_type !== 'proxy'" class="chat-collaboration-mode">
              <label>协作方式
                <SearchSelect aria-label="协作方式" :searchable="false" :model-value="curSession?.collaborationMode || 'EXPLICIT_ONLY'"
                  :options="(curSession?.allowedCollaborationModes || ['EXPLICIT_ONLY']).map(mode => ({ value: mode, label: collaborationModeLabels[mode] }))"
                  :disabled="!curSession?.goalEnabled || curSession?.modeSaving || sending || streaming || curSession?.approvalBusy || Boolean(curSession?.pendingGoalRequest)"
                  @change="saveCollaborationMode" />
              </label>
              <span>{{ curSession?.modeSaving ? '保存中…' : pendingFiles.length ? '含附件的消息仅使用用户明确 @ 的协作' : collaborationModeHints[curSession?.collaborationMode || 'EXPLICIT_ONLY'] }}</span>
            </div>
            <CollaborationComposer :autonomous="curSession?.goalEnabled && !pendingFiles.length" ref="collaborationComposerRef" @finish="chatInputRef?.focus()" :key="currentConvId" :drafts="curSession?.collaborationDrafts || []" :input="input" :conversation-id="currentConvId" :disabled="sending || streaming" @update="updateDraft" @remove="removeDraft" @move="moveDraft" />
            <div class="chat-input-row">
            <button class="chat-attach-btn" @click="fileInput?.click()" title="上传文件">
              <Paperclip :size="18" />
            </button>
            <input ref="fileInput" type="file" multiple accept="image/*,.pdf,.doc,.docx,.txt,.md,.csv,.json,.xlsx,.xls,.pptx,.ppt,.zip,.rar" style="display:none" @change="handleFileSelect" />
            <textarea ref="chatInputRef" v-model="input" class="chat-input" :placeholder="currentConvAgent?.agent_type === 'proxy' ? '输入发送给外部智能体的消息' : '给智能体发送消息；@ 可邀请其他智能体'"
              @input="onTextInput" @keydown.enter.exact.prevent="handleEnterKeydown" @keydown.escape="closeMentionPopover" @paste="handlePaste" rows="1" :disabled="sending"></textarea>
            <button v-if="sending || streaming" class="stop-generation" @click="stopGeneration" :disabled="!controllers.has(currentConvId)"><span class="runtime-bars" aria-hidden="true"><i></i><i></i><i></i></span>停止生成</button>
            <button v-else class="chat-send" :title="curSession?.collaborationDrafts?.length ? '发送并开始协作' : '发送'" aria-label="发送消息并执行已配置的协作任务" @click="sendMessage" :disabled="sending || streaming || curSession?.modeSaving || (!input.trim() && pendingFiles.length === 0)">
              <span v-if="sending || streaming" class="send-loading"></span>
              <Send v-else :size="16" />
            </button>
          </div>
          </div>
          <div class="chat-input-hint">Enter 发送，Shift+Enter 换行 · 支持拖入文件或粘贴图片</div>
        </div>
      </template>
    </div>

    <ConversationDebugPanel
      v-if="debugEnabled && showDebugPanel && currentConvId"
      :key="currentConvId"
      :rounds="debugRounds"
      @close="showDebugPanel = false"
    />

    <!-- @Agent Mention Popover -->
    <AgentMentionPopover
      :visible="showMentionPopover"
      :query="mentionQuery"
      :position="mentionPosition"
      :exclude-agent-id="currentConvAgent?.id || ''"
      @select="handleMentionSelect"
      @close="closeMentionPopover"
      @state-update="handleMentionStateUpdate"
    />

    <DocumentPreview v-if="previewSource" :key="previewSource.document_id" :kb-id="previewSource.id" :doc-id="previewSource.document_id" :name="previewSource.name" @close="previewSource = null" />

    <!-- Source Modal -->
    <div v-if="showSourceModal" class="source-modal" @click.self="showSourceModal = false">
      <div class="source-modal-box">
        <div class="source-modal-header">
          <h3>参考来源</h3>
          <button class="modal-close" @click="showSourceModal = false">&times;</button>
        </div>
        <div class="source-modal-split">
          <div class="source-modal-list">
            <div v-for="(src, i) in selectedSources" :key="i"
              :class="['source-list-item', { active: selectedSourceIdx === i }]"
              @click="selectSource(i)">
              <span v-if="src.type === 'knowledge_base'" class="source-list-icon"><BookOpen :size="14" /></span>
              <span v-else-if="src.type === 'data_source'" class="source-list-icon"><Database :size="14" /></span>
              <span v-else class="source-list-icon"><Link :size="14" /></span>
              <div class="source-list-info">
                <div class="source-list-name">{{ src.name }}</div>
                <div v-if="src.capability" class="source-list-cap">{{ src.capability }}</div>
              </div>
            </div>
          </div>
          <div class="source-modal-preview">
            <div v-if="selectedSourceIdx !== null && selectedSources[selectedSourceIdx]" class="preview-content">
              <div class="preview-title">{{ selectedSources[selectedSourceIdx].name }}</div>
              <div class="preview-type">{{ selectedSources[selectedSourceIdx].type === 'web' ? '网页搜索结果' : selectedSources[selectedSourceIdx].type === 'knowledge_base' ? '知识库文档' : '数据源' }}</div>
              <div v-if="selectedSources[selectedSourceIdx].description" class="preview-desc">{{ selectedSources[selectedSourceIdx].description }}</div>
              <div v-if="selectedSources[selectedSourceIdx].type === 'knowledge_base' && selectedSources[selectedSourceIdx].doc_count" class="preview-meta"><AppIcon name="FileText" /> 包含 {{ selectedSources[selectedSourceIdx].doc_count }} 份文档</div>
              <div v-if="selectedSources[selectedSourceIdx].capability" class="preview-cap"><AppIcon name="Wrench" /> 查询能力: {{ selectedSources[selectedSourceIdx].capability }}</div>
              <button v-if="selectedSources[selectedSourceIdx].document_id" class="source-open" @click="previewSource = selectedSources[selectedSourceIdx]; showSourceModal = false">查看原文件</button>
              <a v-if="/^https?:\/\//i.test(selectedSources[selectedSourceIdx].url || '')" :href="selectedSources[selectedSourceIdx].url" target="_blank" rel="noopener noreferrer" class="source-open">打开网页来源</a>
              <div class="preview-hint">{{ selectedSources[selectedSourceIdx].url ? '以上为搜索引擎返回的摘要；请打开网页核对完整内容。' : selectedSources[selectedSourceIdx].document_id ? '以上为本次提供给模型的参考片段；原文件页码以预览为准。' : '历史来源未记录具体文件，无法定位原文。' }}</div>
            </div>
            <div v-else class="preview-empty">← 选择一个来源查看详情</div>
          </div>
        </div>
      </div>
    </div>
  </div>
  </div>
</template>

<script setup>
import AgentAvatar from '../components/AgentAvatar.vue'
import { highlightKeyContent } from '../utils/chatHighlights'
import { inlineFormat } from '../utils/messageFormatting'
import { Bot, MessageSquare, Send, Copy, Link, RefreshCw, Pencil, MoreHorizontal, Trash2, Clock, Cpu, Search, BookOpen, Database, ChevronDown, AlertCircle, Check, Brain, CheckCircle, FileText, Loader, Paperclip, Image, X, Bug } from 'lucide-vue-next'
import DocumentPreview from '../components/knowledge/DocumentPreview.vue'
import AgentMentionPopover from '../components/AgentMentionPopover.vue'
import AgentCollaborationCard from '../components/AgentCollaborationCard.vue'
import CollaborationComposer from '../components/CollaborationComposer.vue'
import ConversationDebugPanel from '../components/ConversationDebugPanel.vue'
import { restoreRejectedSend, filterAvailableConversations, sendErrorMessage } from '../utils/chatRecovery.js'
import { syncDrafts, draftPayload, moveDraftOrder } from '../utils/collaborationDrafts.js'
import { stepOutcome, appendStatusStep } from '../utils/statusSteps'
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import WorkCandidates from '../components/WorkCandidates.vue'
import { useRoute } from 'vue-router'
const route = useRoute()
import { conversationApi, usableAgentApi, chatUploadApi, collaborationApi, debugPreferenceApi, goalApi } from '../api'

const isCollaborationOnlyMessage = (msg) =>
  Boolean(msg.metadata_json?.collaboration_drafts?.length) &&
  !msg.attachments?.length &&
  !(msg.content || '').replace(/@([^\s@]+)/g, '').trim()

const agents = ref([])
const agentsLoading = ref(false)
const agentsError = ref('')
let agentsLoadVersion = 0
const conversations = ref([])
const searchQuery = ref('')

const filteredConversations = computed(() => {
  if (!searchQuery.value.trim()) return conversations.value
  const q = searchQuery.value.toLowerCase()
  return conversations.value.filter(c =>
    (c.title || '').toLowerCase().includes(q) ||
    (c.agent_name || '').toLowerCase().includes(q)
  )
})
const collapsedAgentGroups = ref(new Set())
const groupedConversations = computed(() => {
  const groups = new Map()
  const agentsById = new Map(agents.value.map(agent => [String(agent.id), agent]))
  for (const conv of filteredConversations.value) {
    const key = String(conv.agent_id || 'general')
    const agent = agentsById.get(key)
    if (!groups.has(key)) groups.set(key, {
      key,
      name: conv.agent_name || agent?.name || '通用对话',
      avatar: conv.agent_avatar || agent?.avatar || '',
      conversations: [],
    })
    groups.get(key).conversations.push(conv)
  }
  return [...groups.values()]
})
const isGroupCollapsed = key => !searchQuery.value.trim() && collapsedAgentGroups.value.has(key)
const toggleAgentGroup = key => {
  if (searchQuery.value.trim()) return
  const next = new Set(collapsedAgentGroups.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsedAgentGroups.value = next
}
const openConvMenuId = ref(null)
const conversationMenuRef = ref(null)
const conversationMenuStyle = ref({})
let conversationMenuTrigger = null
const closeConversationMenu = (restoreFocus = false) => {
  openConvMenuId.value = null
  if (restoreFocus) conversationMenuTrigger?.focus()
  conversationMenuTrigger = null
}
const toggleConversationMenu = async (event, convId) => {
  if (openConvMenuId.value === convId) { closeConversationMenu(); return }
  conversationMenuTrigger = event.currentTarget
  const rect = conversationMenuTrigger.getBoundingClientRect()
  conversationMenuStyle.value = {
    top: `${Math.min(rect.bottom + 4, window.innerHeight - 96)}px`,
    left: `${Math.max(8, Math.min(rect.right - 144, window.innerWidth - 152))}px`,
  }
  openConvMenuId.value = convId
  await nextTick()
  conversationMenuRef.value?.querySelector('button')?.focus()
}
const renameFromMenu = () => {
  const conv = conversations.value.find(item => item.id === openConvMenuId.value)
  closeConversationMenu()
  if (conv) startRename(conv)
}
const deleteFromMenu = () => {
  const convId = openConvMenuId.value
  closeConversationMenu()
  if (convId) deleteConversation(convId)
}
const onConversationMenuKeydown = event => {
  if (event.key === 'Escape' && openConvMenuId.value) { event.preventDefault(); closeConversationMenu(true) }
}
const onConversationMenuOutsideClick = event => {
  if (openConvMenuId.value && !conversationMenuRef.value?.contains(event.target) && !conversationMenuTrigger?.contains(event.target)) closeConversationMenu()
}
const onConversationMenuScroll = () => closeConversationMenu()

// Multi-session state
const openTabs = ref([])  // ordered list of convIds that are open as tabs
const activeTabId = ref(null)  // currently visible tab
const sessions = ref({})  // { [convId]: { messages: [], sending: false, streaming: false, streamContent: '', streamError: '', unread: false, input: '', statusSteps: [], lastUserMessage: '' } }
const showNewChat = ref(false)
const newChatAgentId = ref('')
const creatingChat = ref(false)
const messagesContainer = ref(null)
const debugEnabled = ref(false)
const showDebugPanel = ref(false)
const handleDebugConfigChanged = event => {
  debugEnabled.value = Boolean(event.detail?.enabled)
  if (!debugEnabled.value) showDebugPanel.value = false
}

// File upload state
const pendingFiles = ref([])  // [{file, preview, uploading, progress, uploaded}]
const isDragging = ref(false)
const fileInput = ref(null)
const chatInputRef = ref(null)

// @Agent Mention state
const showMentionPopover = ref(false)
const mentionQuery = ref('')
const mentionPosition = ref({ bottom: '120px', left: '200px' })
const activeIndexRef = ref(0)
const filteredAgentsRef = ref([])

// Current session helpers — delegate to active session
const currentConvId = computed(() => activeTabId.value)
const currentConv = computed(() => conversations.value.find(c => c.id === activeTabId.value))
const currentConvAgent = computed(() => {
  const agentId = currentConv.value?.agent_id || sessions.value[activeTabId.value]?.agentId
  return agents.value.find(a => a.id === agentId) || null
})
const currentConvTitle = computed(() => currentConv.value?.title || currentConv.value?.agent_name || '新对话')

const curSession = computed(() => sessions.value[activeTabId.value] || null)
const messages = computed(() => curSession.value?.messages || [])
const sending = computed(() => curSession.value?.sending || false)
const streaming = computed(() => curSession.value?.streaming || false)
const streamContent = computed(() => curSession.value?.streamContent || '')
const streamError = computed(() => curSession.value?.streamError || '')
const statusSteps = computed(() => curSession.value?.statusSteps || [])
const debugRounds = computed(() => {
  const rounds = []
  let prompt = ''
  for (const message of messages.value) {
    if (message.role === 'user') {
      prompt = message.content || '（仅附件或协作任务）'
      continue
    }
    const entries = message.metadata_json?.debug_trace
    if (Array.isArray(entries) && entries.length) {
      rounds.push({
        id: message.id || `history-${rounds.length}`,
        label: `第 ${rounds.length + 1} 轮 · ${shortDebugLabel(prompt)}`,
        createdAt: message.created_at,
        entries,
        isLive: false,
      })
    }
  }
  const session = curSession.value
  if (session?.liveDebug?.length && (session.sending || session.streaming)) {
    rounds.push({
      id: `live-${activeTabId.value}`,
      label: `第 ${rounds.length + 1} 轮 · ${shortDebugLabel(session.liveDebugPrompt || session.lastUserMessage)}`,
      createdAt: new Date().toISOString(),
      entries: session.liveDebug,
      isLive: true,
    })
  }
  return rounds
})
const debugEventCount = computed(() => debugRounds.value.reduce((sum, round) => sum + round.entries.length, 0))
const shortDebugLabel = value => {
  const text = (value || '未命名轮次').replace(/\s+/g, ' ').trim()
  return text.length > 24 ? text.slice(0, 24) + '…' : text
}
const input = computed({
  get: () => curSession.value?.input || '',
  set: (v) => { if (curSession.value) curSession.value.input = v }
})


const getConv = (convId) => conversations.value.find(c => c.id === convId)
const isTabLoading = (convId) => {
  const s = sessions.value[convId]
  return s && (s.sending || s.streaming)
}

const getOrCreateSession = (convId) => {
  if (!sessions.value[convId]) {
    sessions.value[convId] = {
      agentId: getConv(convId)?.agent_id, unavailable: false,
      messages: [], sending: false, streaming: false,
      streamContent: '', streamError: '', unread: false,
      goalEnabled: false, goalMode: false, goalLoaded: false, goal: null, goalCandidates: [], goalSelection: [], approvalBusy: false, pendingGoalRequest: null,
      collaborationDrafts: [], lastDrafts: null, draftError: '',
      collaborationMode: 'EXPLICIT_ONLY', allowedCollaborationModes: ['EXPLICIT_ONLY'], modeSaving: false,
      input: '', statusSteps: [], lastUserMessage: '',
      collabPending: [],  // in-progress collaborations
      collabResults: [],  // completed collaborations for current streaming message
      liveDebug: [], liveDebugPrompt: '',
    }
  }
  return sessions.value[convId]
}

const collaborationComposerRef = ref(null)
const collaborationAgents = ref([])
let agentLoad = 0
watch(currentConvId, async () => {
  const version = ++agentLoad
  collaborationAgents.value = []
  if (!currentConvId.value) return
  try {
    const { data } = await collaborationApi.listAgents(currentConvAgent.value?.id)
    if (version === agentLoad) collaborationAgents.value = data
  } catch { if (version === agentLoad && curSession.value) curSession.value.draftError = '协作 Agent 列表加载失败，请切换对话重试。' }
}, { immediate: true })
watch([input, collaborationAgents], () => {
  const session = curSession.value
  if (!session || session.sending || session.streaming || !collaborationAgents.value.length) return
  if (currentConvAgent.value?.agent_type === 'proxy') { session.collaborationDrafts = []; return }
  const previous = session.collaborationDrafts || []
  session.collaborationDrafts = syncDrafts(input.value, previous, collaborationAgents.value)
  const added = session.collaborationDrafts.find(d => !previous.some(old => old.agent_id === d.agent_id))
  if (added && !session.goalMode) nextTick(() => { if (curSession.value === session) collaborationComposerRef.value?.focusTask(added.agent_id) })
})
const updateDraft = (id, changes) => {
  const session = curSession.value
  session.collaborationDrafts = session.collaborationDrafts.map(d => d.agent_id === id ? {...d, ...changes} : d)
  session.draftError = ''
}
const moveDraft = (id, direction) => {
  try {
    curSession.value.collaborationDrafts = moveDraftOrder(curSession.value.collaborationDrafts, id, direction)
    curSession.value.draftError = ''
  } catch (error) { curSession.value.draftError = error.message }
}
const removeDraft = (draft) => {
  input.value = input.value.replace(/@([^\s@]+)/g, (match, name) => name === draft.name ? '' : match)
  curSession.value.collaborationDrafts = curSession.value.collaborationDrafts.filter(d => d.agent_id !== draft.agent_id)
}

// ── Sync textarea when switching conversations ──
watch(input, (newVal) => {
  const ta = chatInputRef.value
  if (ta && ta.value !== newVal) {
    ta.value = newVal || ''
  }
})

// ── @Agent Mention Handlers ──
// Simple @input handler that syncs to session and detects @mentions
const onTextInput = (e) => {
  if (currentConvAgent.value?.agent_type === 'proxy') { showMentionPopover.value = false; return }
  // v-model already syncs input to session; just detect @mentions
  const val = e.target.value
  const cursorPos = e.target.selectionStart || val.length
  const textBefore = val.substring(0, cursorPos)
  const lastAtIndex = textBefore.lastIndexOf('@')

  if (lastAtIndex >= 0) {
    const textAfterAt = textBefore.substring(lastAtIndex + 1)
    if (!textAfterAt.includes(' ')) {
      mentionQuery.value = textAfterAt
      showMentionPopover.value = true
      const rect = e.target.getBoundingClientRect()
      mentionPosition.value = {
        bottom: (window.innerHeight - rect.top + 8) + 'px',
        left: Math.max(16, Math.min(rect.left, window.innerWidth - 340)) + 'px',
      }
      return
    }
  }
  showMentionPopover.value = false
}

const handleMentionSelect = async (agent) => {
  const session = curSession.value
  if (!session) return
  if (!collaborationAgents.value.some(a => a.id === agent.id)) collaborationAgents.value.push(agent)
  const text = input.value || ''
  const cursor = chatInputRef.value?.selectionStart ?? text.length
  const lastAt = text.lastIndexOf('@', cursor - 1)
  if (lastAt >= 0) {
    const tokenEnd = text.slice(lastAt).search(/\s/)
    const end = tokenEnd < 0 ? text.length : lastAt + tokenEnd
    input.value = text.slice(0, lastAt) + '@' + agent.name + ' ' + text.slice(end).trimStart()
  } else {
    input.value = text + ' @' + agent.name + ' '
  }
  // Register an independent, initially empty task before the input watcher runs.
  if (!session.collaborationDrafts.some(d => d.agent_id === agent.id)) {
    const draft = syncDrafts('@' + agent.name, [], [agent])[0]
    session.collaborationDrafts.push({...draft, task: '', dirty: true})
  }
  showMentionPopover.value = false
  mentionQuery.value = ''
  await nextTick()
  if (curSession.value === session && !session.goalMode) await collaborationComposerRef.value?.focusTask(agent.id)
}

const closeMentionPopover = () => {
  showMentionPopover.value = false
  mentionQuery.value = ''
}

const handleMentionStateUpdate = (state) => {
  filteredAgentsRef.value = state.filteredAgents || []
  activeIndexRef.value = state.activeIndex || 0
}

const handleEnterKeydown = (e) => {
  if (e.isComposing) return
  if (showMentionPopover.value) {
    e.preventDefault()
    e.stopPropagation()
    const filtered = filteredAgentsRef.value
    if (filtered && filtered.length > 0) {
      const idx = Math.min(activeIndexRef.value || 0, filtered.length - 1)
      handleMentionSelect(filtered[idx])
    }
    return
  }
  sendMessage()
}

// ── File Upload Handlers ──
const handleFileSelect = (e) => {
  const files = Array.from(e.target.files || [])
  addPendingFiles(files)
  if (fileInput.value) fileInput.value.value = ''
}

const addPendingFiles = (files) => {
  for (const file of files) {
    if (file.size > 20 * 1024 * 1024) {
      alert(`文件 ${file.name} 超过 20MB 限制`)
      continue
    }
    const isImage = file.type.startsWith('image/')
    const entry = { file, preview: null, uploading: false, uploaded: null, error: null }
    if (isImage) {
      const reader = new FileReader()
      reader.onload = (e) => { entry.preview = e.target.result }
      reader.readAsDataURL(file)
    }
    pendingFiles.value.push(entry)
  }
}

const removePendingFile = (idx) => {
  pendingFiles.value.splice(idx, 1)
}

const uploadPendingFiles = async (convId) => {
  const results = []
  for (const entry of pendingFiles.value) {
    if (entry.uploaded) { results.push(entry.uploaded); continue }
    entry.uploading = true
    entry.error = null
    try {
      const { data } = await chatUploadApi.uploadFile(convId, entry.file)
      entry.uploaded = data
      results.push(data)
    } catch (e) {
      entry.error = e.response?.data?.detail || e.message || '上传失败'
      console.error('File upload failed:', e)
    } finally {
      entry.uploading = false
    }
  }
  return results
}

// Drag and drop
const handleDragOver = (e) => { e.preventDefault(); isDragging.value = true }
const handleDragLeave = (e) => { e.preventDefault(); isDragging.value = false }
const handleDrop = (e) => {
  e.preventDefault()
  isDragging.value = false
  const files = Array.from(e.dataTransfer.files)
  addPendingFiles(files)
}

// Paste image from clipboard
const handlePaste = (e) => {
  const items = Array.from(e.clipboardData?.items || [])
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault()
      const file = item.getAsFile()
      if (file) addPendingFiles([file])
    }
  }
}

const formatFileSize = (bytes) => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

const currentWorkspace = () => localStorage.getItem('currentWorkspace')

const loadAgents = async () => {
  const version = ++agentsLoadVersion
  agentsLoading.value = true
  agentsError.value = ''
  try {
    const { data } = await usableAgentApi.list(currentWorkspace())
    if (version === agentsLoadVersion) agents.value = data
  } catch (e) {
    if (version === agentsLoadVersion) agentsError.value = '可用 Agent 加载失败。'
    console.error(e)
  } finally {
    if (version === agentsLoadVersion) agentsLoading.value = false
  }
}

const openNewChat = () => {
  newChatAgentId.value = ''
  showNewChat.value = true
  loadAgents()
}
const closeNewChat = () => {
  showNewChat.value = false
  newChatAgentId.value = ''
}

const loadDebugConfig = async () => {
  try {
    const { data } = await debugPreferenceApi.get()
    debugEnabled.value = Boolean(data.allowed && data.enabled)
    if (!debugEnabled.value) showDebugPanel.value = false
  } catch (error) {
    console.error('加载对话调试配置失败', error)
  }
}

const removedConversations = new Set()
let conversationLoadVersion = 0
let sendSequence = 0
const conversationLoadError = ref('')
const loadConversations = async () => {
  const version = ++conversationLoadVersion
  conversationLoadError.value = ''
  try {
    const { data } = await conversationApi.list()
    if (version === conversationLoadVersion) conversations.value = filterAvailableConversations(data, removedConversations)
  } catch (e) {
    if (version === conversationLoadVersion) conversationLoadError.value = '对话列表加载失败，请重试'
    console.error(e)
  }
}

const refreshGoal = async (convId, session) => {
  if (!session.goal?.goal_id) return
  const { data } = await goalApi.get(convId, session.goal.goal_id)
  session.goal = data
  session.goalCandidates = []
  session.goalSelection = []
  if (data.reason === 'collaboration_approval_required') {
    session.goalCandidates = (await goalApi.candidates(convId, data.goal_id)).data
  }
}
const loadGoalSession = async (convId, session) => {
  try {
    const { data } = await goalApi.options(convId)
    session.goalEnabled = data.enabled
    session.collaborationMode = data.collaboration_mode || 'EXPLICIT_ONLY'
    session.allowedCollaborationModes = data.allowed_collaboration_modes || ['EXPLICIT_ONLY']
    if (!session.goalLoaded) session.goalMode = false
    session.goalLoaded = true
    const prior = session.messages.at(-1)
    if (!session.goal) session.goal = prior?.metadata_json?.goal_id ? { goal_id: prior.metadata_json.goal_id } : null
    await refreshGoal(convId, session)
  } catch (error) { session.streamError = '任务状态加载失败，请重试：' + (error.response?.data?.detail || error.message) }
}
const collaborationModeLabels = { EXPLICIT_ONLY: '不主动', ASK_BEFORE_COLLABORATION: '询问', AUTONOMOUS: '主动' }
const collaborationModeHints = {
  EXPLICIT_ONLY: '仅用户主动 @ 的 Agent 可以协作',
  ASK_BEFORE_COLLABORATION: '需要其他 Agent 协作时，先询问你',
  AUTONOMOUS: '由 Agent 自行决策是否协作',
}
const saveCollaborationMode = async (selected) => {
  const convId = activeTabId.value
  const session = curSession.value
  if (session.modeSaving || session.sending || session.streaming) return
  session.modeSaving = true
  session.draftError = ''
  try {
    const { data } = await goalApi.saveCollaborationMode(convId, selected)
    session.collaborationMode = data.collaboration_mode
    session.allowedCollaborationModes = data.allowed_collaboration_modes
  } catch (error) {
    session.draftError = '协作方式保存失败：' + (error.response?.data?.detail || error.message)
    await loadGoalSession(convId, session)
  } finally { session.modeSaving = false }
}
const approveGoal = async () => {
  const convId = activeTabId.value
  const session = curSession.value
  if (session.approvalBusy) return
  session.approvalBusy = true
  try {
    const approved = session.goalSelection
    const { data } = await goalApi.authorize(convId, session.goal.goal_id, {
      revision: session.goal.revision, approved_agents: approved,
      denied_agents: (session.goal.pending_agents || []).filter(id => !approved.includes(id)),
    })
    session.goal = data
    session.goalCandidates = []
    if (activeTabId.value === convId) {
      session.input = '继续执行目标'
      await sendMessage()
    }
  } catch (error) {
    session.streamError = '协作选择未完成：' + (error.response?.data?.detail || error.message)
    try { await refreshGoal(convId, session) } catch {}
  } finally { session.approvalBusy = false }
}

const selectConversation = async (convId) => {
  if (removedConversations.has(convId)) return
  // If already open as tab, just switch to it
  if (openTabs.value.includes(convId)) {
    activeTabId.value = convId
    const session = sessions.value[convId]
    session.unread = false
    if (!session.sending && !session.streaming) {
      try {
        const { data } = await conversationApi.messages(convId)
        if (!removedConversations.has(convId)) session.messages = data
        await loadGoalSession(convId, session)
      } catch (error) {
        session.streamError = '对话刷新失败，请重试：' + (error.response?.data?.detail || error.message)
      }
    }
    scrollToBottom()
    return
  }
  // Open new tab
  const session = getOrCreateSession(convId)
  session.messages = []
  session.unread = false
  openTabs.value.push(convId)
  activeTabId.value = convId
  try {
    const { data } = await conversationApi.messages(convId)
    if (!removedConversations.has(convId)) session.messages = data
    await loadGoalSession(convId, session)
    scrollToBottom()
  } catch (e) {
    if (e.response?.status === 404) {
      markConversationUnavailable(convId, session)
    } else { session.streamError = '对话加载失败，请重试'; }
  }
}

const markConversationUnavailable = (convId, session) => {
  removedConversations.add(convId)
  conversations.value = conversations.value.filter(c => c.id !== convId)
  session.unavailable = true
  session.streamError = sendErrorMessage(404)
}

const closeTab = (convId) => {
  const idx = openTabs.value.indexOf(convId)
  openTabs.value = openTabs.value.filter(id => id !== convId)
  delete sessions.value[convId]
  if (activeTabId.value === convId) {
    activeTabId.value = openTabs.value[Math.min(idx, openTabs.value.length - 1)] || null
  }
}

const switchTab = (convId) => {
  activeTabId.value = convId
  if (sessions.value[convId]) sessions.value[convId].unread = false
  scrollToBottom()
}

const createChat = async () => {
  if (creatingChat.value || !agents.value.some(agent => agent.id === newChatAgentId.value)) return
  creatingChat.value = true
  try {
    const { data } = await conversationApi.create({ agent_id: newChatAgentId.value })
    await loadConversations()
    closeNewChat()
    // Auto-open new conversation as tab
    await selectConversation(data.id)
  } catch (e) {
    alert('创建失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    creatingChat.value = false
  }
}

const deleteConversation = async (convId) => {
  if (!confirm('确定删除此对话？')) return
  try {
    await conversationApi.delete(convId)
  } catch (e) {
    if (e.response?.status !== 404) { window.alert('删除失败，请重试'); return }
  }
  removedConversations.add(convId)
  conversationLoadVersion++
  conversations.value = conversations.value.filter(c => c.id !== convId)
  controllers.get(convId)?.abort()
  closeTab(convId)
  await loadConversations()
}

const previewSource = ref(null)
const controllers = new Map()
const followBottom = ref(true)
const hasNewContent = ref(false)
const stopGeneration = () => controllers.get(activeTabId.value)?.abort()
const showSourceModal = ref(false)
const selectedSources = ref([])
const selectedSourceIdx = ref(null)

const showSources = (msg, index = 0) => {
  selectedSources.value = msg.metadata_json?.sources || []
  selectedSourceIdx.value = index
  showSourceModal.value = true
}

const selectSource = (idx) => { selectedSourceIdx.value = idx }

const toggleSources = (msg) => { msg._sourcesExpanded = !msg._sourcesExpanded }


const sendMessage = async () => {
  const convId = activeTabId.value
  if (!convId) return
  const session = getOrCreateSession(convId)
  const text = session.input.trim()
  if (session.unavailable) { session.streamError = sendErrorMessage(404); return }
  if ((!text && pendingFiles.value.length === 0) || session.sending || session.streaming || session.modeSaving) return

  let goalMode = false
  if (session.goalEnabled && text && !pendingFiles.value.length) {
    session.sending = true
    try {
      const { data } = await goalApi.route(convId, {
        content: text,
        participant_ids: (session.collaborationDrafts || []).map(d => d.agent_id),
        has_attachments: false,
      })
      goalMode = Boolean(data.use_goal)
    } catch (error) {
      session.streamError = '消息发送前检查失败，请重试：' + (error.response?.data?.detail || error.message)
      session.sending = false
      return
    }
    session.sending = false
  }
  const newTopic = /^(?:另一个|另外|新问题|新任务|重新开始)/.test(text)
  const continuing = session.goalEnabled && !pendingFiles.value.length && session.goal?.status === 'WAITING' && !newTopic
  if (continuing) goalMode = true
  session.goalMode = goalMode
  if (session.goal?.status === 'WAITING' && newTopic) {
    session.goal = null
    session.goalCandidates = []
  }
  if (goalMode && session.goal?.reason === 'collaboration_approval_required') { session.draftError = '请先选择本次允许协作的 Agent。'; return }
  if (goalMode && ['COMPLETE', 'BLOCKED', 'FAILED'].includes(session.goal?.status)) {
    session.goal = null
    session.goalCandidates = []
    session.pendingGoalRequest = null
  }
  if (goalMode && session.goal?.status === 'RUNNING' && !session.goal.recovery_allowed) {
    await refreshGoal(convId, session)
    if (session.goal?.status === 'RUNNING' && !session.goal.recovery_allowed) {
      session.streamError = '上一项任务仍在进行，请稍后再试。'
      return
    }
  }
  const drafts = session.collaborationDrafts || []
  const mentioned = [...text.matchAll(/@([^\s@]+)/g)].map(m => m[1])
  if (currentConvAgent.value?.agent_type !== 'proxy' && mentioned.some(name => !drafts.some(d => d.name === name))) {
    session.draftError = '请从 @ 候选列表选择协作 Agent，确认每个 Agent 都有任务卡。'; return
  }
  if (drafts.length > (goalMode ? 5 : 3)) { session.draftError = `每轮最多邀请 ${goalMode ? 5 : 3} 个 Agent`; return }
  if (!goalMode && drafts.some((d, i) => d.depends_on.some(id => !drafts.slice(0,i).some(prior => prior.agent_id === id)))) {
    session.draftError = '请修正已移除的协作依赖。'; return
  }
  const emptyDraft = !goalMode && drafts.find(d => !d.task.trim())
  if (emptyDraft) {
    session.draftError = `请在 ${emptyDraft.name} 的卡片中填写任务，主输入框内容只用于当前 Agent。`
    await collaborationComposerRef.value?.focusTask(emptyDraft.agent_id)
    return
  }
  let goalParticipants = []
  if (goalMode) {
    try {
      goalParticipants = drafts.map(d => {
        const participant = { agent_id: d.agent_id, ...(d.task?.trim() ? { task: d.task.trim() } : {}) }
        if (d.proxyInputsRaw?.trim()) {
          const params = JSON.parse(d.proxyInputsRaw)
          if (!params || typeof params !== 'object' || Array.isArray(params)) throw new Error(`${d.name} 的显式参数必须是 JSON 对象`)
          participant.inputs = params
        }
        return participant
      })
    } catch (error) { session.draftError = '代理参数无效：' + error.message; return }
  }
  const collaborationDrafts = goalMode ? undefined : draftPayload(drafts, text)
  session.draftError = ''

  const submittedFiles = [...pendingFiles.value]
  // Upload pending files first
  let attachments = []
  if (pendingFiles.value.length > 0) {
    session.sending = true
    attachments = await uploadPendingFiles(convId)
    // Filter out failed uploads
    attachments = attachments.filter(a => a)
    pendingFiles.value = []
  }

  const displayText = text || (attachments.length > 0 ? '请查看我上传的附件' : '')
  if (!displayText && attachments.length === 0) return

  let endpoint = `/api/conversations/${convId}/messages/stream`
  let body = { content: displayText, collaboration_drafts: collaborationDrafts, attachments: attachments.length ? attachments : undefined }
  if (goalMode) {
    if (session.goal?.status === 'WAITING' || session.goal?.recovery_allowed) {
      endpoint = `/api/conversations/${convId}/goals/${session.goal.goal_id}/resume`
      body = { content: displayText, revision: session.goal.revision, participants: goalParticipants }
    } else {
      const participants = goalParticipants
      const signature = JSON.stringify([displayText, participants])
      if (session.pendingGoalRequest && session.pendingGoalRequest.signature !== signature) {
        session.streamError = '上次目标是否接收尚未确认，请重试原请求，或刷新页面读取已保存的目标。'
        return
      }
      session.pendingGoalRequest ||= { signature, key: globalThis.crypto?.randomUUID?.() || `goal-${Date.now()}-${Math.random().toString(36).slice(2)}` }
      endpoint = `/api/conversations/${convId}/goals/stream`
      body = { content: displayText, idempotency_key: session.pendingGoalRequest.key, participants }
    }
  }
  const attempt = {id: ++sendSequence, text: displayText, drafts: JSON.parse(JSON.stringify(drafts))}
  session.messages.push({ _attemptId: attempt.id, role: 'user', content: displayText, metadata_json: {collaboration_drafts: collaborationDrafts}, attachments: attachments.length > 0 ? attachments : undefined })
  session.lastUserMessage = displayText
  session.lastDrafts = JSON.parse(JSON.stringify(drafts))
  session.sending = true
  session.input = ''
  session.collaborationDrafts = []
  session.streamContent = ''
  session.streamError = ''
  session.statusSteps = []
  session.liveDebug = []
  session.liveDebugPrompt = displayText
  scrollToBottom(true)
  const controller = new AbortController()
  controllers.set(convId, controller)
  let completed = false
  let rejected = false

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'Cortexa', 'X-Workspace-Id': currentWorkspace() },
      body: JSON.stringify(body)
    })
    if (!response.ok) {
      rejected = true
      let detail
      try { detail = (await response.json()).detail } catch {}
      if (response.status === 404) markConversationUnavailable(convId, session)
      throw new Error(sendErrorMessage(response.status, detail))
    }

    if (goalMode && !response.headers.get('content-type')?.includes('text/event-stream')) {
      session.goal = await response.json()
      session.pendingGoalRequest = null
      session.messages = (await conversationApi.messages(convId)).data
      await refreshGoal(convId, session)
      completed = true
      return
    }

    // Keep sending=true during status phase; switch to streaming on 'start' event
    session.streaming = true

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const event = JSON.parse(line.slice(6))
          if (event.type === 'goal_status') {
            session.goal = { ...(session.goal || {}), ...event }
          } else if (event.type === 'user_message') {
            if (event.conversation_title) {
              const conversation = conversations.value.find(item => item.id === convId)
              if (conversation) conversation.title = event.conversation_title
            }
            const optimistic = session.messages.find(m => m._attemptId === attempt.id)
            if (optimistic) optimistic.id = event.id
            if (goalMode) {
              session.goal = { goal_id: event.goal_id }
              if (optimistic) optimistic.metadata_json = { goal_id: event.goal_id }
            }
          } else if (event.type === 'start') {
            session.sending = false
            session.streamContent = ''
            session.statusSteps = []
            session.collabPending = []
            session.collabResults = []
          } else if (event.type === 'status') {
            const rawMsg = cleanStatusText(event.message)
            appendStatusStep(session.statusSteps, event, rawMsg)
          } else if (event.type === 'debug') {
            if (event.entry) session.liveDebug.push(event.entry)
          } else if (event.type === 'collab_status') {
            // Handle collaboration status events
            if (event.status === 'started') {
              session.collabPending.push({
                order: session.collabResults.length + session.collabPending.length,
                agent_name: event.target_agent_name,
                agent_avatar: event.target_agent_avatar,
                task: event.task,
                status: 'pending',
              })
            } else if (event.status === 'completed') {
              // Move from pending to results
              const idx = session.collabPending.findIndex(c => c.agent_name === event.target_agent_name)
              const pending = idx >= 0 ? session.collabPending[idx] : null
              if (idx >= 0) session.collabPending.splice(idx, 1)
              session.collabResults.push({
                order: pending?.order ?? session.collabResults.length,
                task: event.task || pending?.task,
                input_snapshot: event.input_snapshot,
                background: event.background,
                agent_name: event.target_agent_name,
                agent_avatar: event.target_agent_avatar,
                status: event.collab_status,
                summary: event.summary,
                result: event.result,
                duration_ms: event.duration_ms,
              })
            } else if (event.status === 'agent_not_found') {
              // Show notification for agent not found
              session.statusSteps.push({
                status: 'collab_error',
                message: event.message,
                icon: 'error',
              })
            }
          } else if (event.type === 'token') {
            session.streamContent += event.content
            scrollToBottom()
          } else if (event.type === 'tool_call') {
            session.streamContent += `\n\n正在查询「${event.tool}」...\n`
            scrollToBottom()
          } else if (event.type === 'tool_result') {
            // Remove the "querying" line and append result preview
            session.streamContent = session.streamContent.replace(/\n\n正在查询「[^」]*」\.\.\.\n$/, '')
            scrollToBottom()
          } else if (event.type === 'assistant_message') {
            // Collaboration: target agent response becomes the final answer
            session.streamContent = event.content || ''
            scrollToBottom()
          } else if (event.type === 'done') {
            completed = true
            session.sending = goalMode
            session.streaming = goalMode
            const meta = {}
            if (goalMode) {
              session.goal = { ...(session.goal || {}), ...event }
              session.pendingGoalRequest = null
              meta.goal_id = event.goal_id
              meta.goal_status = event.status
            }
            if (event.sources?.length) meta.sources = event.sources
            if (event.stats) meta.stats = event.stats
            if (event.collaborations?.length) meta.collaborations = event.collaborations
            if (event.debug_trace?.length) meta.debug_trace = event.debug_trace
            else if (session.liveDebug.length) meta.debug_trace = [...session.liveDebug]
            session.messages.push({
              id: event.id,
              role: 'assistant',
              content: event.content || session.streamContent || '（无回复）',
              _steps: [...session.statusSteps],
              metadata_json: Object.keys(meta).length ? meta : null,
              created_at: new Date().toISOString(),
              _collabResults: session.collabResults.length > 0 ? [...session.collabResults] : null,
            })
            session.collabResults = []
            session.collabPending = []
            // Mark unread if this tab is not active
            if (convId !== activeTabId.value) {
              session.unread = true
            }
            session.streamContent = ''
          } else if (event.type === 'error') {
            session.sending = false
            session.statusSteps = []
            session.streamError = event.error
          }
        } catch (e) { /* skip */ }
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError') session.streamError = rejected ? e.message : '发送失败: ' + e.message
  } finally {
    if (controllers.get(convId) !== controller) return
    controllers.delete(convId)
    if (!completed && session.streamContent) {
      session.messages.push({ role: 'assistant', content: session.streamContent, _steps: [...session.statusSteps], metadata_json: { stopped: controller.signal.aborted } })
    }
    if (!completed && !controller.signal.aborted && !session.streamError) session.streamError = '连接中断，请重试'
    if (rejected) {
      if (goalMode) session.pendingGoalRequest = null
      restoreRejectedSend(session, attempt)
      if (activeTabId.value === convId && !pendingFiles.value.length) pendingFiles.value = submittedFiles
    }
    if (goalMode && session.goal?.goal_id) {
      try {
        await refreshGoal(convId, session)
        // Reconcile partial saves and identical retries without replaying actions.
        session.messages = (await conversationApi.messages(convId)).data
        session.pendingGoalRequest = null
      } catch { session.streamError ||= '目标状态读取失败，请刷新状态后继续。' }
    }
    session.sending = false
    session.streaming = false
    session.streamContent = ''
    session.statusSteps = []
    session.collabPending = []
    if (completed) {
      session.liveDebug = []
      session.liveDebugPrompt = ''
    }
    scrollToBottom()
  }
}

const recoverConversation = async () => {
  const oldId = activeTabId.value
  const oldSession = curSession.value
  if (!oldSession?.unavailable || oldSession.sending) return
  const text = oldSession.input || oldSession.lastUserMessage || ''
  const drafts = JSON.parse(JSON.stringify(oldSession.collaborationDrafts || oldSession.lastDrafts || []))
  oldSession.sending = true
  try {
    const {data} = await conversationApi.create({agent_id:oldSession.agentId})
    await loadConversations()
    await selectConversation(data.id)
    const session = getOrCreateSession(data.id)
    session.agentId = oldSession.agentId
    session.input = text
    await nextTick()
    session.collaborationDrafts = drafts
    closeTab(oldId)
  } catch (error) { oldSession.streamError = '新建对话失败：' + (error.response?.data?.detail || error.message) }
  finally { oldSession.sending = false }
}

const retryMessage = async () => {
  const session = curSession.value
  if (!session || !session.lastUserMessage || !activeTabId.value) return
  session.streamError = ''
  if (session.goalMode && session.goal?.goal_id) {
    try { await refreshGoal(activeTabId.value, session) } catch { session.streamError = '目标状态刷新失败'; return }
    if ((session.goal.status !== 'WAITING' && !session.goal.retryable) || session.goal.reason === 'collaboration_approval_required') return
  }
  if (!session.input.trim()) {
    session.input = session.lastUserMessage
    await nextTick()
    session.collaborationDrafts = JSON.parse(JSON.stringify(session.lastDrafts || []))
  }
  session.lastUserMessage = ''
  await sendMessage()
}

const editingConvId = ref(null)
const renameTitle = ref('')
const renameTarget = ref(null)
const renameError = ref('')
const renameSaving = ref(false)
const headerRenameInput = ref(null)

const startRename = (conv, target = 'sidebar') => {
  if (!conv) return
  editingConvId.value = conv.id
  renameTarget.value = target
  renameTitle.value = conv.title || ''
  renameError.value = ''
  nextTick(() => {
    const input = target === 'header' ? headerRenameInput.value : document.querySelector('.conv-rename-input')
    input?.focus()
    input?.select()
  })
}

const cancelRename = () => {
  editingConvId.value = null
  renameTarget.value = null
  renameError.value = ''
}
const saveRename = async (convId) => {
  if (editingConvId.value !== convId || renameSaving.value) return
  const title = renameTitle.value.trim()
  if (!title || title === conversations.value.find(conv => conv.id === convId)?.title) { cancelRename(); return }
  renameSaving.value = true
  try {
    await conversationApi.update(convId, { title })
    const idx = conversations.value.findIndex(c => c.id === convId)
    if (idx >= 0) conversations.value[idx].title = title
    if (editingConvId.value === convId) cancelRename()
  } catch (e) {
    if (editingConvId.value === convId) renameError.value = '重命名失败，请重试'
    console.error(e)
  } finally {
    renameSaving.value = false
  }
}
watch(currentConvId, () => {
  if (renameTarget.value === 'header' && editingConvId.value !== currentConvId.value) cancelRename()
})

const regenerateMessage = async (msgIdx) => {
  const session = curSession.value
  if (!session || !activeTabId.value || session.sending || session.streaming) return
  const lastMsg = session.messages[msgIdx]
  if (lastMsg && lastMsg.role === 'assistant') {
    session.messages.splice(msgIdx, 1)
  }
  session.sending = true
  try {
    const { data } = await conversationApi.regenerate(activeTabId.value)
    session.messages.push(data)
  } catch (e) {
    session.messages.push({ role: 'assistant', content: '重新生成失败: ' + (e.response?.data?.detail || e.message) })
  } finally {
    session.sending = false
    scrollToBottom()
  }
}

const copiedIdx = ref(null)
const copyMessage = async (content, idx) => {
  if (!content) return
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(content)
    } else {
      const ta = document.createElement('textarea')
      ta.value = content
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    copiedIdx.value = idx
    setTimeout(() => { copiedIdx.value = null }, 1500)
  } catch (e) {
    console.error('Copy failed:', e)
  }
}

const handleMessageScroll = () => {
  const container = messagesContainer.value
  if (!container) return
  followBottom.value = container.scrollHeight - container.scrollTop - container.clientHeight < 80
  if (followBottom.value) hasNewContent.value = false
}
const scrollToBottom = (force = false) => {
  if (force) followBottom.value = true
  if (!followBottom.value) { hasNewContent.value = true; return }
  nextTick(() => {
    if (messagesContainer.value) messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    hasNewContent.value = false
  })
}
watch(activeTabId, () => scrollToBottom(true))

const cleanStatusText = (value = '') => value.replace(/^[\p{Extended_Pictographic}\uFE0F\u200D✓✗●⏱\s]+/u, '').trim()
const usageLabel = (stats) => {
  if (stats?.token_count == null) return '词元用量未返回'
  const count = Number(stats.token_count).toLocaleString('zh-CN')
  if (stats.usage_source !== 'provider') return count + ' 词元 · 历史统计'
  return count + ' 词元' + (stats.usage_complete ? '' : ' · 部分统计')
}
const usageTitle = (stats) => stats?.usage_source === 'provider' && stats.token_count != null
  ? '回复及工具调用：输入 ' + (stats.input_tokens || 0) + ' 词元，输出 ' + (stats.output_tokens || 0) + ' 词元。' + (stats.usage_complete ? '' : '部分模型调用未返回用量。')
  : '历史记录或外部服务未提供可核实的词元用量；不将文字长度或流式片段数作为实际消耗。'
const formatDuration = (ms) => {
  if (!ms) return ''
  if (ms < 1000) return ms + 'ms'
  return (ms / 1000).toFixed(1) + 's'
}

const formatMessage = (content) => {
  if (!content) return ''

  // Work on RAW content for block detection (before HTML escaping)
  const allLines = content.split('\n')
  const merged = []
  let i = 0
  while (i < allLines.length) {
    const l = allLines[i]
    const trimmed = l.trim()

    if (!trimmed) { i++; continue }

    // Collect consecutive blockquote lines (including bare >)
    if (trimmed.startsWith('>')) {
      const bqLines = []
      while (i < allLines.length) {
        const cl = allLines[i].trim()
        if (cl.startsWith('>')) {
          bqLines.push(cl.replace(/^>\s?/, ''))
          i++
        } else if (cl === '' || cl === '>') {
          // Check if next line is also >
          if (i + 1 < allLines.length && allLines[i + 1].trim().startsWith('>')) {
            bqLines.push('')
            i++
          } else {
            i++
            break
          }
        } else {
          break
        }
      }
      merged.push({ type: 'bq', lines: bqLines })
      continue
    }

    // Collect a non-bq block
    const blockLines = []
    while (i < allLines.length) {
      const cl = allLines[i].trim()
      if (cl === '' || cl.startsWith('>')) break
      blockLines.push(allLines[i])
      i++
    }
    if (blockLines.length > 0) merged.push({ type: 'block', lines: blockLines })
  }

  // Render each merged block
  const rendered = merged.map(block => {
    if (block.type === 'bq') return renderBlockquote(block.lines)
    return renderBlock(block.lines)
  })
  return highlightKeyContent(rendered.join(''))
}

const renderBlockquote = (lines) => {
  const inner = lines.map(l => {
    if (l === '') return '</p><p>'
    // Escape HTML first, then apply inline formatting
    let safe = l.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    safe = safe
      .replace(/\*\*(.*?)\*\*/g, '<strong class="hl">$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`(.+?)`/g, '<code>$1</code>')
    if (/^\s*[-*]\s/.test(l)) {
      let itemText = l.replace(/^\s*[-*]\s/, '')
      itemText = itemText.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      itemText = itemText
        .replace(/\*\*(.*?)\*\*/g, '<strong class="hl">$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.+?)`/g, '<code>$1</code>')
      return '<li>' + itemText + '</li>'
    }
    return '<p>' + safe + '</p>'
  }).join('')
  const cleaned = inner.replace(/<\/p><p>/g, '')
  return '<blockquote>' + cleaned + '</blockquote>'
}

const renderBlock = (lines) => {
  const isPipeTable = lines.length >= 2 && lines[0].trim().startsWith('|') && lines.some(l => /^\|?\s*[-:]+/.test(l.trim()))
  if (isPipeTable) return renderTable(lines)

  let html = ''
  let i = 0
  while (i < lines.length) {
    const trimmed = lines[i].trim()
    if (!trimmed) { i++; continue }
    if (/^---+$/.test(trimmed)) { html += '<hr />'; i++; continue }
    const headingMatch = trimmed.match(/^(#{1,5})\s+(.+)/)
    if (headingMatch) {
      const level = headingMatch[1].length + 1
      const tag = 'h' + Math.min(level, 6)
      html += '<' + tag + '>' + inlineFormat(headingMatch[2]) + '</' + tag + '>'
      i++; continue
    }
    if (/^\s*[-*]\s/.test(trimmed)) {
      const items = []
      while (i < lines.length && /^\s*[-*]\s/.test(lines[i].trim())) {
        items.push('<li>' + inlineFormat(lines[i].trim().replace(/^\s*[-*]\s/, '')) + '</li>')
        i++
      }
      html += '<ul>' + items.join('') + '</ul>'
      continue
    }
    if (/^\s*\d+[.)]\s/.test(trimmed)) {
      const items = []
      while (i < lines.length && /^\s*\d+[.)]\s/.test(lines[i].trim())) {
        items.push('<li>' + inlineFormat(lines[i].trim().replace(/^\s*\d+[.)]\s/, '')) + '</li>')
        i++
      }
      html += '<ol>' + items.join('') + '</ol>'
      continue
    }
    html += '<p>' + inlineFormat(trimmed) + '</p>'
    i++
  }
  return html
}

const renderTable = (lines) => {
  const parseRow = (line) => {
    const cells = line.split('|').map(c => c.trim())
    if (cells[0] === '') cells.shift()
    if (cells[cells.length - 1] === '') cells.pop()
    return cells
  }

  // Parse separator line to detect column alignment from Markdown spec
  let separatorCells = []
  for (const line of lines) {
    if (/^\|?\s*[-:]+/.test(line.trim())) {
      separatorCells = parseRow(line)
      break
    }
  }

  const dataLines = []
  for (const line of lines) {
    if (/^\|?\s*[-:]+/.test(line.trim())) continue
    if (line.trim().startsWith('|')) dataLines.push(parseRow(line))
  }
  if (dataLines.length === 0) return ''

  const header = dataLines[0]
  const rows = dataLines.slice(1)
  const colCount = header.length

  // Detect column types from data
  const colTypes = []
  for (let c = 0; c < colCount; c++) {
    const values = rows.map(r => (r[c] || '').trim())
    const nonEmpty = values.filter(v => v.length > 0)
    if (nonEmpty.length === 0) { colTypes.push('text'); continue }

    // Check separator for explicit right-align (:---:)
    const sep = (separatorCells[c] || '').trim()
    const sepRight = sep.startsWith(':') && sep.endsWith('-')
    const sepCenter = sep.startsWith(':') && sep.endsWith(':')

    if (sepCenter) { colTypes.push('center'); continue }
    if (sepRight) { colTypes.push('number'); continue }

    // Heuristic: check if values look numeric
    const allNumeric = nonEmpty.every(v => {
      const cleaned = v.replace(/[,，\s\u00a0%‰¥$€£]/g, '')
      return /^-?\d+(\.\d+)?$/.test(cleaned)
    })
    if (allNumeric) { colTypes.push('number'); continue }

    // Check if it's a rank column (1, 2, 3... or #1, #2...)
    const allRank = nonEmpty.every(v => {
      const cleaned = v.replace(/[#＃第\s]/g, '')
      return /^\d+$/.test(cleaned) && parseInt(cleaned) <= 100
    })
    if (allRank && nonEmpty.length >= 2) { colTypes.push('center'); continue }

    colTypes.push('text')
  }

  // Compute column width class
  const colWidths = []
  for (let c = 0; c < colCount; c++) {
    const headerLen = (header[c] || '').length
    const maxDataLen = Math.max(...rows.map(r => (r[c] || '').length))
    const contentLen = Math.max(headerLen, maxDataLen)
    if (colTypes[c] === 'center' && contentLen <= 6) colWidths.push('col-rank')
    else if (colTypes[c] === 'number') colWidths.push('col-num')
    else if (contentLen > 12) colWidths.push('col-wide')
    else colWidths.push('col-text')
  }

  // Build HTML
  let html = '<div class="tbl-wrap"><table class="tbl"><thead><tr>'
  header.forEach((h, i) => {
    html += '<th class="' + colWidths[i] + ' ' + colTypes[i] + '">' + inlineFormat(h) + '</th>'
  })
  html += '</tr></thead><tbody>'
  rows.forEach(row => {
    html += '<tr>'
    row.forEach((cell, i) => {
      html += '<td class="' + colWidths[i] + ' ' + colTypes[i] + '">' + inlineFormat(cell) + '</td>'
    })
    html += '</tr>'
  })
  html += '</tbody></table></div>'
  return html
}

const formatMessageTime = (t) => {
  if (!t) return ''
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' +
    pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds())
}

onMounted(async () => {
  window.addEventListener('conversation-debug-config', handleDebugConfigChanged)
  document.addEventListener('keydown', onConversationMenuKeydown)
  document.addEventListener('click', onConversationMenuOutsideClick)
  window.addEventListener('scroll', onConversationMenuScroll, true)
  await Promise.all([loadAgents(), loadConversations(), loadDebugConfig()])
  const target = route.query.conversation
  if (target && conversations.value.some(c => c.id === target)) {
    await selectConversation(target)
    await nextTick()
    if (route.query.message) document.getElementById(`message-${route.query.message}`)?.scrollIntoView({block:'center'})
  }
})
onBeforeUnmount(() => {
  window.removeEventListener('conversation-debug-config', handleDebugConfigChanged)
  document.removeEventListener('keydown', onConversationMenuKeydown)
  document.removeEventListener('click', onConversationMenuOutsideClick)
  window.removeEventListener('scroll', onConversationMenuScroll, true)
  for (const controller of controllers.values()) controller.abort()
  controllers.clear()
})

</script>

<style scoped>
/* Sidebar activity */
.conv-spinner { color: var(--primary); animation: spin 1s linear infinite; flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg); } }


/* ===== Layout ===== */
.chat-page {
  display: flex;
  flex-direction: column;
  height: var(--page-viewport-height);
  min-height: 0;
  min-width: 0;
}
.chat-page > :deep(.app-page-heading) { flex-shrink: 0; }
.chat-layout {
  display: flex;
  position: relative;
  flex: 1;
  min-height: 0;
  min-width: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

/* ===== Sidebar ===== */
.chat-sidebar {
  width: 232px;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sidebar-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 16px 12px;
}
.sidebar-header h2 { font-size: 15px; font-weight: 600; margin: 0; color: var(--text); }
.sidebar-search {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 10px; margin: 0 12px 8px;
  background: var(--surface2); border-radius: 8px;
  color: var(--text3); border: 1px solid transparent;
}
.sidebar-search:focus-within { border-color: var(--primary); background: var(--surface); }
.search-input {
  flex: 1; border: none; background: transparent; font-size: 13px;
  color: var(--text); outline: none;
}
.search-input::placeholder { color: var(--text3); }

.conv-list { min-height: 0; flex: 1; overflow-y: auto; padding: 4px 8px; }
.conv-empty { text-align: center; color: var(--text3); font-size: 13px; padding: 40px 16px; }
.conv-group { margin: 4px 0 10px; }
.conv-group-heading {
  display: flex; align-items: center; gap: 6px; width: 100%; padding: 7px 9px;
  border: 0; border-radius: 8px; background: transparent; color: var(--text2);
  font-size: 12px; font-weight: 600; text-align: left; cursor: pointer;
}
.conv-group-heading:hover { background: var(--surface2); color: var(--text); }
.conv-group-heading:focus-visible, .conv-title-text:focus-visible, .conv-more:focus-visible, .conv-action-menu button:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.conv-group-chevron { flex-shrink: 0; transition: transform .15s; }
.conv-group-chevron.collapsed { transform: rotate(-90deg); }
.conv-group-avatar { display: flex; align-items: center; justify-content: center; flex-shrink: 0; width: 24px; height: 24px; border-radius: 7px; overflow: hidden; background: var(--surface2); color: var(--text2); }
.conv-group-avatar :deep(img), .conv-group-avatar :deep(.agent-avatar-inline) { width: 100%; height: 100%; object-fit: cover; }
.conv-group-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conv-group-count { min-width: 20px; padding: 1px 5px; border-radius: 99px; background: var(--surface2); color: var(--text2); text-align: center; font-variant-numeric: tabular-nums; }

.conv-item {
  display: flex; align-items: center; gap: 6px;
  min-height: 32px; padding: 2px 8px; border: 0; border-radius: 0;
  cursor: pointer; transition: all 0.12s; position: relative;
}
.conv-item:hover .conv-title-text { color: var(--primary); }
.conv-item.active .conv-title-text { color: var(--primary); font-weight: 600; }
.conv-info { flex: 1; min-width: 0; }
.conv-title-row { display: grid; grid-template-columns: 16px minmax(0, 1fr); align-items: center; gap: 6px; min-width: 0; }
.conv-status { display: flex; align-items: center; justify-content: center; width: 16px; }
.conv-title-text { flex: 1; min-width: 0; padding: 0; border: 0; background: transparent; color: var(--text); font-size: 13px; font-weight: 500; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; }
.conv-title-text.unread { font-weight: 650; }
.conv-more { display: flex; align-items: center; justify-content: center; flex-shrink: 0; width: 28px; height: 28px; border: 1px solid transparent; border-radius: 7px; background: transparent; color: var(--text2); cursor: pointer; }
.conv-more:hover, .conv-more[aria-expanded="true"] { background: var(--surface); border-color: var(--border); color: var(--text); }
@media (hover: hover) and (pointer: fine) {
  .conv-more { opacity: 0; pointer-events: none; }
  .conv-item:hover .conv-more, .conv-item:focus-within .conv-more, .conv-more[aria-expanded="true"] { opacity: 1; pointer-events: auto; }
}
.conv-action-menu { position: fixed; z-index: 2000; width: 144px; padding: 4px; border: 1px solid var(--border); border-radius: 10px; background: var(--glass-menu-background, var(--surface)); -webkit-backdrop-filter: var(--glass-menu-backdrop, blur(20px)); backdrop-filter: var(--glass-menu-backdrop, blur(20px)); box-shadow: var(--shadow-md); }
.conv-action-menu button { display: flex; align-items: center; gap: 8px; width: 100%; min-height: 34px; padding: 7px 9px; border: 0; border-radius: 7px; background: transparent; color: var(--text); font-size: 13px; text-align: left; cursor: pointer; }
.conv-action-menu button:hover { background: var(--surface2); }
.conv-action-menu .conv-action-danger { color: var(--danger); }

/* New Chat Form */
.new-chat-form { flex:1; min-height:0; padding:12px; overflow-y:auto; }
.new-chat-form h3 { margin:0 0 10px; font-size:13px; font-weight:600; color:var(--text2); }
.new-chat-hint { margin:10px 0; color:var(--text3); font-size:12px; line-height:1.5; }
.new-chat-hint button { padding:0; border:0; background:transparent; color:var(--primary); font:inherit; cursor:pointer; }
.new-chat-agent-list { display:grid; gap:6px; }
.new-chat-agent { position:relative; display:flex; align-items:center; gap:9px; min-height:44px; padding:7px 9px; border:1px solid var(--border); border-radius:10px; background:var(--surface); color:var(--text); cursor:pointer; }
.new-chat-agent:hover { border-color:color-mix(in srgb,var(--primary) 55%,var(--border)); background:var(--surface2); }
.new-chat-agent.selected { border-color:var(--primary); background:var(--primary-light); }
.new-chat-agent:focus-within { outline:2px solid var(--primary); outline-offset:2px; }
.new-chat-agent input { position:absolute; width:1px; height:1px; opacity:0; }
.new-chat-agent-avatar { display:grid; place-items:center; flex-shrink:0; width:30px; height:30px; border-radius:8px; overflow:hidden; background:var(--surface2); color:var(--text2); }
.new-chat-agent-avatar :deep(img), .new-chat-agent-avatar :deep(.agent-avatar-inline) { width:100%; height:100%; object-fit:cover; }
.new-chat-agent-name { min-width:0; flex:1; font-size:13px; font-weight:500; line-height:20px; overflow-wrap:anywhere; }
.new-chat-agent-check { flex-shrink:0; color:var(--primary); }
.new-chat-actions { display:flex; gap:8px; justify-content:flex-end; margin-top:12px; }
.new-chat-actions .btn:disabled { opacity:.5; cursor:not-allowed; }
.btn-cancel {
  padding: 6px 14px; background: transparent; color: var(--text2); border: 1px solid var(--border);
  border-radius: 8px; font-size: 13px; cursor: pointer;
}
.btn-cancel:hover { background: var(--surface2); }
.btn-create {
  padding: 6px 14px; background: var(--primary); color: #fff; border: none;
  border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer;
}
.btn-create:hover { background: var(--primary-hover); }

.conv-rename-input {
  width: 100%; padding: 2px 6px; border: 1px solid var(--primary);
  border-radius: 6px; font-size: 13px; background: var(--surface);
  color: var(--text); outline: none;
}

/* ===== Main Chat ===== */
.chat-main { min-width: 0; min-height: 0; flex: 1; display: flex; flex-direction: column; overflow: hidden; }

.chat-empty {
  flex: 1; display: flex; align-items: center; justify-content: center;
}
.empty-state { text-align: center; color: var(--text3); }
.empty-icon-wrap {
  width: 64px; height: 64px; border-radius: 16px; background: var(--surface2);
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 16px; color: var(--text3);
}
.empty-state h3 { font-size: 16px; color: var(--text2); margin: 0 0 4px; font-weight: 600; }
.empty-state p { font-size: 13px; margin: 0; }

/* Header */
.chat-header {
  padding: 12px 24px; border-bottom: 1px solid var(--border);
  background: var(--surface);
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
}
.chat-header-info { min-width: 0; display: flex; align-items: center; gap: 10px; }
.chat-agent-badge {
  width: 32px; height: 32px; border-radius: 10px; background: var(--surface2);
  display: flex; align-items: center; justify-content: center; overflow: hidden;
}
.chat-agent-badge img { width: 100%; height: 100%; object-fit: cover; }
.chat-agent-emoji { font-size: 18px; }
.chat-header-text { display:flex; flex-direction:column; }
.chat-conv-title { min-width:0; max-width:100%; padding:0; border:0; background:transparent; color:var(--text); font:inherit; font-size:14px; font-weight:600; text-align:left; cursor:text; }
.chat-conv-title:hover { color:var(--primary); }
.chat-conv-title:focus-visible { outline:2px solid var(--primary); outline-offset:3px; border-radius:3px; }
.chat-title-input { width:min(460px,100%); min-width:120px; padding:3px 6px; border:1px solid var(--primary); border-radius:6px; background:var(--surface); color:var(--text); font:inherit; font-size:14px; font-weight:600; outline:none; }
.chat-rename-error { margin-top:3px; color:var(--danger); font-size:11px; }
.chat-agent-name { font-size: 12px; color: var(--text3); }
.debug-toggle {
  display: inline-flex; align-items: center; gap: 6px; flex-shrink: 0;
  min-height: 32px; padding: 5px 9px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--surface2); color: var(--text2); font-size: 12px; cursor: pointer;
}
.debug-toggle:hover, .debug-toggle.active { border-color: var(--primary); color: var(--primary); background: var(--primary-light); }
.debug-count { min-width: 18px; padding: 1px 5px; border-radius: 999px; background: var(--surface); color: inherit; font-size: 10px; text-align: center; }

/* Messages Container */
.chat-messages {
  min-height: 0;
  flex: 1; overflow-y: auto; padding: 24px 0;
  display: flex; flex-direction: column;
}

/* Welcome */
.chat-welcome {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; color: var(--text3);
}
.chat-welcome h3 { font-size: 18px; color: var(--text); margin: 12px 0 4px; font-weight: 600; }
.chat-welcome p { font-size: 14px; margin: 0; }
.welcome-avatar {
  width: 64px; height: 64px; border-radius: 16px; background: var(--surface2);
  display: flex; align-items: center; justify-content: center; font-size: 36px;
  overflow: hidden;
}
.welcome-avatar img { width: 100%; height: 100%; object-fit: cover; }

/* ===== User Message ===== */
.msg-row { display: flex; padding: 0 24px; }
.msg-row-user { justify-content: flex-end; margin-bottom: 20px; }
.msg-bubble-user {
  max-width: 70%; padding: 12px 16px;
  background: var(--surface2); border-radius: 14px 14px 4px 14px;
  font-size: 14px; line-height: 1.7; color: var(--text);
  word-break: break-word;
}

/* ===== Assistant Message ===== */
.msg-row-assistant { align-self: flex-start; margin-bottom: 28px; padding-left: 24px; padding-right: 24px; }
.msg-col-assistant { flex: 1; min-width: 0; max-width: 850px; }

.msg-content-assistant {
  font-size: 14px; line-height: 1.8; color: var(--text);
  word-break: break-word;
}
.msg-content-assistant :deep(strong) { font-weight: 600; }
.msg-content-assistant :deep(img) { max-width: 100%; max-height: 400px; border-radius: 8px; display: block; }

.msg-content-assistant :deep(code) {
  background: var(--surface2); padding: 1px 5px; border-radius: 4px;
  font-size: 13px; font-family: 'SF Mono', Menlo, monospace; color: var(--text);
}

/* ===== Sources ===== */
.msg-sources { margin-top: 8px; }
.sources-btn {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 10px; background: transparent; border: 1px solid var(--border);
  border-radius: 8px; font-size: 12px; color: var(--text2);
  cursor: pointer; transition: all 0.15s;
}
.sources-btn:hover { background: var(--surface2); border-color: var(--border); }
.sources-chevron { transition: transform 0.2s; }
.sources-chevron.open { transform: rotate(180deg); }
.sources-panel {
  display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px;
}
.source-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 10px; background: var(--surface2); border-radius: 6px;
  font-size: 12px; color: var(--text2); cursor: pointer;
  transition: all 0.15s; border: 1px solid transparent;
}
.source-chip:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-light); }
.source-chip-icon { flex-shrink: 0; }
.source-chip-name { font-weight: 500; }

/* ===== Stats ===== */
.action-meta {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11px; color: var(--text3); white-space: nowrap;
}
.meta-sep { opacity: 0.5; }

/* ===== Actions ===== */
.msg-actions {
  display: flex; gap: 2px; margin-top: 6px;
  opacity: 0; transition: opacity 0.15s;
}
.msg-row-assistant:hover .msg-actions { opacity: 1; }
.action-time {
  font-size: 11px; color: var(--text3); margin-right: 4px; white-space: nowrap;
  line-height: 28px;
}
.action-btn {
  display: flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; padding: 0;
  background: transparent; border: none; border-radius: 6px;
  color: var(--text3); cursor: pointer; transition: all 0.12s;
}
.action-btn:hover { background: var(--surface2); color: var(--text2); }
.copy-ok { color: var(--success); }

/* ===== Thinking Indicator ===== */
.thinking-indicator {
  display: flex; align-items: center; gap: 6px; padding: 4px 0;
}
.thinking-dot {
  width: 6px; height: 6px; background: var(--border); border-radius: 50%;
  animation: think-bounce 1.4s infinite ease-in-out;
}
.thinking-dot:nth-child(1) { animation-delay: -0.32s; }
.thinking-dot:nth-child(2) { animation-delay: -0.16s; }
.thinking-dot:nth-child(3) { animation-delay: 0s; }
.thinking-label { font-size: 12px; color: var(--text3); margin-left: 2px; }
@keyframes think-bounce { 0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; } 40% { transform: scale(1); opacity: 1; } }

/* ===== Agent Status Panel ===== */
.agent-status-panel {
  display: flex; flex-direction: column; gap: 4px;
  padding: 12px 16px; background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); margin-bottom: 8px; min-width: 280px;
  animation: status-fade-in 0.2s ease-out;
}
@keyframes status-fade-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
.status-step {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: var(--text2); line-height: 1.4;
  animation: status-step-in 0.25s ease-out;
}
@keyframes status-step-in { from { opacity: 0; transform: translateX(-8px); } to { opacity: 1; transform: translateX(0); } }
.status-icon { flex-shrink: 0; display: inline-flex; align-items: center; }
.status-icon svg { color: var(--primary); }
.status-done .status-icon svg { color: var(--text3); }
.status-text { flex: 1; }
.status-detail {
  font-size: 11px; color: var(--text3); background: var(--surface2);
  padding: 1px 6px; border-radius: 3px; white-space: nowrap;
  max-width: 180px; overflow: hidden; text-overflow: ellipsis;
}
.status-thinking .status-text { color: var(--primary); }
.status-thinking .status-icon { animation: pulse 1.2s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.status-done .status-text { color: var(--text3); }
.status-done .status-icon svg { color: #86EFAC; }

/* ===== Stream Cursor ===== */
.stream-cursor::after {
  content: '▍';
  animation: blink 0.8s infinite;
  color: var(--primary);
  font-weight: bold;
}
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

/* ===== Error Bar ===== */
.msg-error-bar {
  display: flex; align-items: center; justify-content: space-between;
  margin: 8px 24px; padding: 10px 14px;
  background: var(--danger-bg); border: 1px solid color-mix(in srgb,var(--danger) 35%,var(--border)); border-radius: 10px;
  font-size: 13px; color: var(--danger);
}
.msg-error-text { display: flex; align-items: center; gap: 6px; }
.btn-retry-sm {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 10px; background: #DC2626; color: #fff; border: none;
  border-radius: 6px; font-size: 12px; cursor: pointer; font-weight: 500;
}
.btn-retry-sm:hover { background: #B91C1C; }

/* ===== Input Area ===== */
.chat-input-area {
  padding: 12px 24px 24px; background: var(--surface);
  border-top: 1px solid var(--border);
}
.chat-input-wrap {
  display: flex; flex-direction: column; gap: 0; align-items: stretch;
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: 12px; padding: 4px 4px 4px 12px;
  transition: border-color 0.15s;
}
.chat-input-row { display:flex; align-items:flex-end; gap:4px; min-width:0; }
.chat-input-wrap:focus-within { border-color: var(--primary); background: var(--surface); }
.chat-input {
  flex: 1; border: none; background: transparent; font-size: 14px;
  color: var(--text); resize: none; min-height: 38px; max-height: 120px;
  padding: 8px 0; outline: none; line-height: 1.5;
}
.chat-input::placeholder { color: var(--text3); }
.chat-send {
  width: 36px; height: 36px; display: flex; align-items: center; justify-content: center;
  background: var(--primary); color: #fff; border: none; border-radius: 10px;
  cursor: pointer; transition: all 0.15s; flex-shrink: 0;
}
.chat-send:hover { background: var(--primary-hover); }
.chat-send:disabled { opacity: 0.4; cursor: not-allowed; }
.chat-input-hint {
  font-size: 11px; color: var(--text3); text-align: center; margin-top: 6px;
}
.send-loading {
  width: 16px; height: 16px;
  border: 2px solid rgba(255,255,255,0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  display: inline-block;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ===== Source Modal ===== */
.source-modal {
  position: fixed; inset: 0;
  background: var(--overlay);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.source-modal-box {
  background: var(--surface); border-radius: 12px;
  max-width: 90vw; max-height: 70vh;
  overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.12);
  width: 680px;
}
.source-modal-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 20px; border-bottom: 1px solid var(--border);
}
.source-modal-header h3 { margin: 0; font-size: 15px; font-weight: 600; color: var(--text); }
.modal-close {
  background: none; border: none; font-size: 20px;
  cursor: pointer; color: var(--text3); padding: 4px 8px; border-radius: 6px;
}
.modal-close:hover { background: var(--surface2); color: var(--text); }
.source-modal-split { display: flex; height: 400px; }
.source-modal-list {
  width: 220px; border-right: 1px solid var(--border);
  overflow-y: auto; flex-shrink: 0;
}
.source-list-item {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 16px; cursor: pointer;
  transition: background 0.12s; border-left: 3px solid transparent;
}
.source-list-item:hover { background: var(--surface2); }
.source-list-item.active { background: var(--primary-light); border-left-color: var(--primary); }
.source-list-icon { color: var(--primary); flex-shrink: 0; }
.source-list-info { flex: 1; min-width: 0; }
.source-list-name { font-size: 13px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text); }
.source-list-cap { font-size: 11px; color: var(--text3); margin-top: 2px; }
.source-modal-preview {
  flex: 1; padding: 20px; overflow-y: auto;
}
.preview-title { font-size: 15px; font-weight: 600; margin-bottom: 8px; color: var(--text); }
.preview-type { font-size: 12px; color: var(--text3); margin-bottom: 6px; }
.preview-desc { font-size: 13px; color: var(--text2); margin-bottom: 8px; line-height: 1.5; }
.preview-meta { font-size: 12px; color: var(--text2); margin-bottom: 6px; }
.preview-cap {
  font-size: 12px; color: var(--text2); padding: 6px 10px; background: var(--surface2);
  border-radius: 6px; margin-bottom: 8px; display: inline-block;
}
.preview-hint { font-size: 12px; color: var(--text3); font-style: italic; }
.preview-empty { color: var(--text3); font-size: 13px; text-align: center; padding-top: 40px; }

/* ===== Shared Buttons ===== */
.btn { display: inline-flex; align-items: center; gap: 4px; padding: 6px 14px; border: none; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.15s; }
.btn-primary { background: var(--primary); color: #fff; }
.btn-primary:hover { background: var(--primary-hover); }
.btn-ghost { background: transparent; color: var(--text2); border: 1px solid var(--border); }
.btn-ghost:hover { background: var(--surface2); }
.btn-sm { padding: 5px 12px; font-size: 12px; }

/* Scrollbar — thin across all browsers */
.chat-messages, .conv-list { scrollbar-width: thin; scrollbar-color: var(--border) transparent; }
.chat-messages::-webkit-scrollbar, .conv-list::-webkit-scrollbar { width: 5px; }
.chat-messages::-webkit-scrollbar-track, .conv-list::-webkit-scrollbar-track { background: transparent; }
.chat-messages::-webkit-scrollbar-thumb, .conv-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
.chat-messages::-webkit-scrollbar-thumb:hover, .conv-list::-webkit-scrollbar-thumb:hover { background: #A1A1AA; }

/* Markdown Tables */
.msg-content-assistant :deep(.tbl-wrap) {
  overflow-x: auto; margin: 12px 0; max-width: 100%;
  border: 1px solid var(--border); border-radius: 8px;
}
.msg-content-assistant :deep(.tbl) {
  width: 100%; border-collapse: separate; border-spacing: 0;
  font-size: 13px; line-height: 1.5;
}
.msg-content-assistant :deep(.tbl th),
.msg-content-assistant :deep(.tbl td) {
  border-right: 1px solid var(--border);
  padding: 12px 16px; white-space: nowrap;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
  text-align: left;
}
.msg-content-assistant :deep(.tbl th:last-child),
.msg-content-assistant :deep(.tbl td:last-child) { border-right: none; }
.msg-content-assistant :deep(.tbl th) {
  background: var(--surface2); font-weight: 600; color: var(--text); text-align: left;
  font-size: 13px; letter-spacing: 0.01em;
}
.msg-content-assistant :deep(.tbl td) { color: var(--text); }
.msg-content-assistant :deep(.tbl tbody tr:last-child td) { border-bottom: none; }
.msg-content-assistant :deep(.tbl tbody tr:hover) { background: var(--surface); }
.msg-content-assistant :deep(.tbl code) { background: transparent; padding: 0; color: var(--text); font-size: 13px; }
.msg-content-assistant :deep(.tbl .left) { text-align: left; }
.msg-content-assistant :deep(.tbl .right) { text-align: right; }
.msg-content-assistant :deep(.tbl .center) { text-align: center; }
.msg-content-assistant :deep(.tbl .col-rank) { width: 48px; min-width: 48px; max-width: 60px; }
.msg-content-assistant :deep(.tbl .col-num) { width: auto; min-width: 72px; }
.msg-content-assistant :deep(.tbl .col-text) { width: auto; min-width: 80px; }
.msg-content-assistant :deep(.tbl .col-wide) { width: auto; min-width: 120px; }
.msg-content-assistant :deep(.tbl td.col-wide) { white-space: normal; word-break: break-word; }

/* Highlight: subtle theme background for important bold text */
.msg-content-assistant :deep(.hl) {
  font-weight: 600;
  background: transparent;
  color: var(--text);
  padding: 0;
  border-radius: 0;
}

/* Markdown elements */
.msg-content-assistant :deep(p) { margin: 0 0 10px; }
.msg-content-assistant :deep(p:last-child) { margin-bottom: 0; }
.msg-content-assistant :deep(h2) {
  font-size: 20px; font-weight: 700; color: var(--text); margin: 16px 0 8px; line-height: 1.3;
}
.msg-content-assistant :deep(h3) {
  font-size: 17px; font-weight: 600; color: var(--text); margin: 14px 0 6px; line-height: 1.3;
}
.msg-content-assistant :deep(h4) {
  font-size: 15px; font-weight: 600; color: var(--text); margin: 12px 0 6px; line-height: 1.3;
}
.msg-content-assistant :deep(h5) {
  font-size: 14px; font-weight: 600; color: var(--text); margin: 10px 0 4px; line-height: 1.3;
}
.msg-content-assistant :deep(blockquote) {
  margin: 10px 0; padding: 12px 16px;
  border-left: 3px solid var(--border);
  background: var(--surface); border-radius: 0 8px 8px 0;
  color: var(--text2);
}
.msg-content-assistant :deep(blockquote p) { margin: 0 0 4px; }
.msg-content-assistant :deep(blockquote p:last-child) { margin-bottom: 0; }
.msg-content-assistant :deep(ul), .msg-content-assistant :deep(ol) {
  margin: 4px 0 8px; padding-left: 20px;
}
.msg-content-assistant :deep(li) { margin-bottom: 5px; }
.msg-content-assistant :deep(hr) {
  border: none; border-top: 1px solid var(--border); margin: 12px 0;
}


/* ===== File Upload ===== */
.chat-input-area { position: relative; }
.chat-drop-overlay {
  position: absolute; inset: 0; z-index: 20;
  background: rgba(124, 58, 237, 0.08); border: 2px dashed var(--primary);
  border-radius: 12px; display: flex; align-items: center; justify-content: center; gap: 8px;
  color: var(--primary); font-size: 14px; font-weight: 500; pointer-events: none;
}
.chat-attach-btn {
  display: flex; align-items: center; justify-content: center;
  width: 36px; height: 36px; border: none; background: none; color: var(--text3);
  cursor: pointer; border-radius: 8px; flex-shrink: 0; transition: all 0.15s;
}
.chat-attach-btn:hover { background: var(--surface2); color: var(--text2); }

.chat-attachments-preview {
  display: flex; flex-wrap: wrap; gap: 8px;
  padding: 10px 0 12px;
}
.attachment-preview-item {
  display: flex; align-items: center; gap: 10px;
  background: var(--surface2); border-radius: 10px; padding: 10px 14px;
  border: 1px solid var(--border); max-width: 320px;
}
.attachment-thumb {
  width: 40px; height: 40px; border-radius: 8px; object-fit: cover; flex-shrink: 0;
}
.attachment-file-icon {
  width: 40px; height: 40px; display: flex; align-items: center; justify-content: center;
  background: var(--primary-bg, #F3F0FF); border-radius: 8px; flex-shrink: 0; color: var(--primary);
}
.attachment-info {
  display: flex; flex-direction: column; min-width: 0; flex: 1; gap: 1px;
}
.attachment-name {
  font-size: 13px; color: var(--text); font-weight: 500;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.attachment-size { font-size: 11px; color: var(--text3); }
.attachment-status { font-size: 11px; color: var(--primary); }
.attachment-status.error { color: var(--danger); }
.attachment-remove {
  display: flex; align-items: center; justify-content: center;
  width: 24px; height: 24px; border: none; background: none; color: var(--text3);
  cursor: pointer; border-radius: 6px; flex-shrink: 0; transition: all 0.15s;
}
.attachment-remove:hover { background: var(--surface2); color: var(--text2); }

/* User message attachments */
.msg-attachments { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.msg-attachment-img {
  max-width: 200px; max-height: 150px; border-radius: 8px; object-fit: cover;
  border: 1px solid var(--border);
}
.msg-attachment-file {
  display: flex; align-items: center; gap: 6px;
  background: color-mix(in srgb,var(--surface) 72%,transparent); border: 1px solid var(--border); border-radius: 6px;
  padding: 4px 10px; font-size: 12px; color: var(--text2);
}
.att-size { color: var(--text3); font-size: 11px; }

.sidebar-header { gap: 8px; flex-wrap: wrap; }
.sidebar-new-chat { padding: 5px 8px; font-size: 12px; white-space: nowrap; flex-shrink: 0; }
</style>

<style scoped>
.stop-generation, .source-open, .new-content-button { border: 1px solid color-mix(in srgb,var(--primary) 24%,var(--border)); background: var(--primary-light); color: var(--primary); padding: 8px 14px; border-radius: 10px; cursor: pointer; }
.stop-generation:disabled { opacity: .5; cursor: wait; }
.new-content-button { align-self: center; margin: 0 0 8px; }
.agent-status-panel summary, .completed-process summary { cursor: pointer; font-size: 12px; color: var(--text2); padding: 6px 0; }
.completed-process { margin: 10px 0; font-size: 12px; line-height: 1.8; color: var(--text2); }
.preview-desc { white-space: pre-wrap; overflow-wrap: anywhere; }
.source-open { margin: 12px 0; }
.chat-header-text { min-width: 0; }
.chat-conv-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sidebar-header { gap: 8px; flex-wrap: wrap; }
.sidebar-new-chat { padding: 5px 8px; font-size: 12px; white-space: nowrap; flex-shrink: 0; }
</style>

<style scoped>
.chat-layout { background: var(--surface); }
.chat-sidebar { background: var(--surface); }
.sidebar-search { background: var(--surface); border-color: var(--border); }
.search-input { min-width: 0; width: 100%; }
.conv-item { margin-bottom: 0; }
.conv-item, .conv-item:hover, .conv-item.active { background: transparent; box-shadow: none; }
.conv-rename-input { margin-left: 22px; width: calc(100% - 22px); }
.chat-header { padding: 16px 28px; }
.chat-conv-title { font-size: 16px; letter-spacing: -.02em; }
.chat-agent-name { margin-top: 3px; color: var(--text3); }
.chat-messages { padding-top: 32px; padding-bottom: 32px; scrollbar-gutter: stable; }
.msg-row { width: 100%; max-width: 1000px; margin-left: auto; margin-right: auto; box-sizing: border-box; padding-left: 32px; padding-right: 32px; }
.msg-col-assistant { max-width: 100%; }
.msg-content-assistant { font-size: 13px; line-height: 1.75; color: var(--text); overflow-wrap: anywhere; word-break: normal; }
.msg-content-assistant :deep(p) { margin-bottom: 14px; }
.msg-content-assistant :deep(h2) { font-size: 17px; margin-top: 24px; }
.msg-content-assistant :deep(h3) { font-size: 15px; margin-top: 20px; }
.msg-content-assistant :deep(h4) { font-size: 14px; }
.msg-content-assistant :deep(.hl-key) { color: var(--primary); background: var(--primary-light, #f3eeff); border-radius: 3px; padding: 1px 3px; box-decoration-break: clone; -webkit-box-decoration-break: clone; }
.msg-content-assistant :deep(li) { margin-bottom: 8px; }
.msg-bubble-user { font-size: 13px; line-height: 1.75; background: var(--surface2); border: 1px solid var(--border); border-radius: 18px 18px 5px 18px; padding: 12px 18px; }
.msg-actions { flex-wrap: wrap; gap: 8px; opacity: 1; margin-top: 14px; }
.usage-badge { display: inline-flex; align-items: center; gap: 5px; color: var(--text3); font-size: 11px; font-variant-numeric: tabular-nums; }
.msg-actions .action-time, .msg-actions .usage-badge, .msg-actions .action-meta { color: var(--text3); }
.msg-actions .meta-sep { color: inherit; opacity: 1; }
.chat-input-area { border-top: 0; padding: 14px 28px 18px; }
.chat-input-wrap { border: 1px solid var(--border); background: var(--surface); border-radius: 16px; box-shadow: var(--shadow-md); }
.chat-input-wrap:focus-within { box-shadow: 0 0 0 3px var(--primary-light, #f4f4f5); }
.source-chip, .sources-btn { background: var(--surface2); }
.new-content-button, .stop-generation, .source-open { border-color: var(--border); background: var(--surface); }
@media(max-width: 760px) { .msg-row { padding-left: 18px; padding-right: 18px; } .chat-input-area { padding: 10px 16px; } .msg-bubble-user { max-width: 90%; } }
.sidebar-header { gap: 8px; flex-wrap: wrap; }
.sidebar-new-chat { padding: 5px 8px; font-size: 12px; white-space: nowrap; flex-shrink: 0; }
</style>

<style scoped>
.outcome-error .status-icon svg { color: var(--danger); }
.outcome-done .status-icon svg { color: var(--success); }
</style>

<style scoped>
@media (max-width: 760px) {
  .chat-layout { flex-direction:column; }
  .chat-sidebar { width:100%; max-height:200px; flex:0 0 auto; border-right:0; border-bottom:1px solid var(--border); }
  .chat-sidebar .conv-list { max-height:88px; }
  .chat-sidebar:has(.new-chat-form) { max-height:330px; overflow-y:auto; }
  .msg-row { padding-left:12px; padding-right:12px; }
}
</style>

<style scoped>
.chat-collaboration-mode { display:flex; align-items:center; flex-wrap:wrap; gap:8px 12px; color:var(--text2); font-size:12px; padding:4px 0 8px }
.chat-collaboration-mode label { display:flex; align-items:center; gap:8px; white-space:nowrap }
.chat-collaboration-mode .search-select { width:112px; flex-shrink:0 }
.chat-collaboration-mode span { overflow-wrap:anywhere }
.goal-mode-select { display:flex; align-items:center; gap:6px; color:var(--text2); font-size:12px; margin-left:auto }
.goal-mode-select select { background:var(--surface); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:6px }
.goal-panel { padding:10px 16px; border-top:1px solid var(--border); color:var(--text2); background:var(--surface); font-size:13px; max-height:35vh; overflow-y:auto; flex-shrink:0 }
.goal-panel > button { margin-left:8px }
.goal-approval p { margin:8px 0 }
.goal-candidate { display:flex; align-items:flex-start; gap:8px; padding:8px 0; color:var(--text) }
.goal-candidate small { display:block; color:var(--text2); overflow-wrap:anywhere }
@media(max-width:640px) { .goal-mode-select { flex-wrap:wrap; max-width:125px } }
</style>

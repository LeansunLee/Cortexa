<template>
  <div class="agents-page">
    <!-- Agent List -->
    <div v-if="!editingAgent">
      <div class="page-header">
        <div>
          <h1>智能体管理</h1>
          <p class="subtitle">创建和管理AI智能体</p>
        </div>
        <button class="btn btn-primary" @click="createNewAgent">+ 创建智能体</button>
      </div>

      <div class="agents-grid" v-if="agents.length > 0">
        <div v-for="agent in agents" :key="agent.id" class="agent-card" @click="editAgent(agent)">
          <div class="agent-header">
            <div class="agent-avatar">
              <img v-if="agent.avatar" :src="agent.avatar" alt="avatar" class="agent-avatar-img" />
              <span v-else>🤖</span>
            </div>
            <div class="agent-info">
              <div class="agent-name">{{ agent.name }}</div>
              <div class="agent-role">{{ agent.role || '未设置角色' }}</div>
            </div>
            <span :class="['status-badge', 'status-' + agent.status]">{{ statusText(agent.status) }}</span>
          </div>
          <p class="agent-desc">{{ agent.description || '暂无描述' }}</p>
          <div class="agent-meta">
            <span class="agent-type-badge" :class="'type-' + (agent.agent_type || 'llm')">{{ (agent.agent_type || 'llm') === 'proxy' ? '🔗 Proxy' : '🧠 LLM' }}</span>
            <span v-if="agent.model && agent.agent_type !== 'proxy'">🔧 {{ agent.model }}</span>
            <span v-if="agent.agent_type === 'proxy' && agent.proxy_config?.endpoint">🔗 {{ agent.proxy_config.endpoint.substring(0, 30) }}...</span>
            <span>v{{ agent.current_version }}</span>
          </div>
          <div class="agent-actions">
            <button class="btn btn-ghost btn-sm" @click.stop="testAgent(agent)">测试</button>
            <button class="btn btn-ghost btn-sm" @click.stop="chatWithAgent(agent)">对话</button>
            <button class="btn btn-danger btn-sm" @click.stop="deleteAgent(agent.id)">删除</button>
          </div>
        </div>
      </div>
      <div v-else class="empty-state">
        <div class="empty-icon">🤖</div>
        <p>暂无智能体，点击上方按钮创建</p>
      </div>
    </div>

    <!-- Agent Editor -->
    <div v-else class="agent-editor">
      <div class="editor-header">
        <button class="btn btn-ghost" @click="saveAndExit">← 返回</button>
        <div class="editor-title">
          <h2>{{ editingAgent.name || '新智能体' }}</h2>
          <span :class="['status-badge', 'status-' + editingAgent.status]">{{ statusText(editingAgent.status) }}</span>
        </div>
        <div class="editor-actions">
          <button class="btn btn-ghost" @click="saveAgent" :disabled="saving">
            {{ saving ? '保存中...' : '保存' }}
          </button>
          <button class="btn btn-primary" @click="publishAgent" :disabled="publishing">
            {{ publishing ? '发布中...' : '发布' }}
          </button>
        </div>
      </div>

      <div class="editor-layout">
        <!-- 左侧导航 -->
        <div class="editor-nav">
          <div v-for="section in sections" :key="section.id"
               :class="['nav-item', { active: currentSection === section.id }]"
               @click="currentSection = section.id">
            {{ section.icon }} {{ section.name }}
          </div>
        </div>

        <!-- 中间编辑区 -->
        <div class="editor-content">
          <!-- 基础信息 -->
          <div v-if="currentSection === 'basic'" class="section">
            <h3>基础信息</h3>
            <div class="form-group">
              <label>头像</label>
              <div class="avatar-upload-area">
                <div class="avatar-preview" @click="$refs.avatarInput.click()">
                  <img v-if="editingAgent.avatar" :src="editingAgent.avatar" alt="avatar" class="avatar-preview-img" />
                  <span v-else class="avatar-placeholder">📷 上传头像</span>
                </div>
                <input ref="avatarInput" type="file" accept="image/jpeg,image/png,image/gif,image/webp" style="display:none" @change="handleAvatarUpload" />
                <div class="avatar-hint">支持 JPG/PNG/GIF/WebP，最大 5MB</div>
              </div>
              <div class="preset-avatars">
                <span class="preset-label">预设头像：</span>
                <div class="preset-avatar-grid">
                  <div v-for="a in presetAvatars" :key="a.path" :class="['preset-avatar-item', { active: editingAgent.avatar === a.path }]"
                    @click="editingAgent.avatar = a.path" :title="a.label">
                    <img :src="a.path" :alt="a.label" />
                  </div>
                </div>
              </div>
            </div>

            <!-- Avatar Crop Modal -->
            <div v-if="showCropModal" class="crop-modal-overlay" @click.self="cancelCrop">
              <div class="crop-modal">
                <div class="crop-modal-header">
                  <h3>裁剪头像</h3>
                  <button class="btn btn-ghost btn-sm" @click="cancelCrop">✕</button>
                </div>
                <div class="crop-area">
                  <canvas ref="cropCanvas" width="400" height="400" @mousedown="onCropMouseDown"
                    @mousemove="onCropMouseMove" @mouseup="onCropMouseUp" @mouseleave="onCropMouseUp"></canvas>
                </div>
                <div class="crop-actions">
                  <div class="crop-zoom">
                    <button class="crop-zoom-btn" @click="cropZoom(-0.15)" title="缩小">−</button>
                    <span class="crop-zoom-label">{{ Math.round(cropState.zoom * 100) }}%</span>
                    <button class="crop-zoom-btn" @click="cropZoom(0.15)" title="放大">+</button>
                    <button class="crop-zoom-btn" @click="cropZoomReset" title="重置">↺</button>
                  </div>
                  <div class="crop-actions-right">
                    <button class="btn btn-ghost" @click="cancelCrop">取消</button>
                    <button class="btn btn-primary" @click="confirmCrop">确认裁剪</button>
                  </div>
                </div>
              </div>
            </div>
            <div class="form-group">
              <label>名称 *</label>
              <input v-model="editingAgent.name" placeholder="例如：资深产品经理" />
            </div>
            <div class="form-group">
              <label>智能体类型</label>
              <div class="agent-type-toggle">
                <button :class="['type-btn', { active: (editingAgent.agent_type || 'llm') === 'llm' }]"
                  @click="editingAgent.agent_type = 'llm'">
                  🧠 LLM 智能体
                </button>
                <button :class="['type-btn', { active: editingAgent.agent_type === 'proxy' }]"
                  @click="editingAgent.agent_type = 'proxy'">
                  🔗 Proxy 代理
                </button>
              </div>
              <div class="type-hint" v-if="editingAgent.agent_type === 'proxy'">
                Proxy 代理将请求转发至外部系统，不使用 LLM 推理。适用于已有外部 Agent API 的场景。
              </div>
            </div>
            <div class="form-group">
              <label>描述</label>
              <textarea v-model="editingAgent.description" rows="3" placeholder="智能体的功能描述"></textarea>
            </div>
            <div class="form-group">
              <label>标签</label>
              <input v-model="tagInput" placeholder="输入标签后按回车" @keydown.enter.prevent="addTag" />
              <div class="tags">
                <span v-for="(tag, i) in editingAgent.tags" :key="i" class="tag">
                  {{ tag }} <button @click="removeTag(i)">×</button>
                </span>
              </div>
            </div>
          </div>

          <!-- 人格 -->
          <div v-if="currentSection === 'personality'" class="section">
            <h3>人格特征</h3>
            <div class="form-group">
              <label>Personality</label>
              <textarea v-model="editingAgent.personality" rows="5" 
                placeholder="描述智能体的性格特征，例如：&#10;- 严谨认真&#10;- 理性分析&#10;- 主动沟通&#10;- 专业高效"></textarea>
              <div class="preset-chips">
                <span class="preset-label">快速添加：</span>
                <button v-for="p in personalityPresets" :key="p" class="preset-chip" @click="appendPersonality(p)">+ {{ p }}</button>
              </div>
            </div>
          </div>

          <!-- 职责 -->
          <div v-if="currentSection === 'role'" class="section">
            <h3>角色与职责</h3>
            <div class="form-group">
              <label>角色名称</label>
              <input v-model="editingAgent.role" placeholder="例如：产品经理" />
            </div>
            <div class="form-group">
              <label>职责描述</label>
              <textarea v-model="editingAgent.responsibilities" rows="5" 
                placeholder="描述智能体的主要职责"></textarea>
            </div>
            <div class="form-group">
              <label>预设角色（点击自动填入）</label>
              <div class="role-presets">
                <div v-for="rp in rolePresets" :key="rp.role" class="role-preset-card" @click="applyRolePreset(rp)">
                  <div class="role-preset-icon">{{ rp.icon }}</div>
                  <div class="role-preset-info">
                    <div class="role-preset-name">{{ rp.role }}</div>
                    <div class="role-preset-desc">{{ rp.desc }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 工作边界 -->
          <div v-if="currentSection === 'boundary'" class="section">
            <h3>工作边界</h3>
            <div class="form-group">
              <label>边界定义</label>
              <textarea v-model="editingAgent.boundaries" rows="5" 
                placeholder="明确智能体可以做什么，不可以做什么"></textarea>
            </div>
            <div class="form-group">
              <label>预设边界（点击自动填入）</label>
              <div class="preset-card-grid">
                <div v-for="bp in boundaryPresets" :key="bp.name" class="preset-card-item" @click="applyBoundaryPreset(bp)">
                  <div class="preset-card-icon">{{ bp.icon }}</div>
                  <div class="preset-card-info">
                    <div class="preset-card-name">{{ bp.name }}</div>
                    <div class="preset-card-desc">{{ bp.desc }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 工作方式 -->
          <div v-if="currentSection === 'behavior'" class="section">
            <h3>工作方式</h3>
            <div class="form-group">
              <label>Behavior</label>
              <textarea v-model="editingAgent.behavior" rows="5" 
                placeholder="描述智能体的工作流程和方式"></textarea>
            </div>
            <div class="form-group">
              <label>预设工作方式（点击自动填入）</label>
              <div class="preset-card-grid">
                <div v-for="bp in behaviorPresets" :key="bp.name" class="preset-card-item" @click="applyBehaviorPreset(bp)">
                  <div class="preset-card-icon">{{ bp.icon }}</div>
                  <div class="preset-card-info">
                    <div class="preset-card-name">{{ bp.name }}</div>
                    <div class="preset-card-desc">{{ bp.desc }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Proxy 配置 -->
          <div v-if="currentSection === 'proxy'" class="section">
            <h3>🔗 Proxy 代理配置</h3>
            <div v-if="editingAgent.agent_type !== 'proxy'" class="proxy-disabled-hint">
              当前智能体类型为 LLM，Proxy 配置仅在选择「Proxy 代理」类型时生效。
            </div>
            <div :class="{ 'proxy-disabled': editingAgent.agent_type !== 'proxy' }">
              <div class="form-group">
                <label>外部系统 Endpoint *</label>
                <input v-model="proxyCfg.endpoint" placeholder="https://api.example.com/v1/run" class="mono" />
              </div>
              <div class="form-row">
                <div class="form-group">
                  <label>请求方法</label>
                  <select v-model="proxyCfg.method">
                    <option value="POST">POST</option>
                    <option value="GET">GET</option>
                    <option value="PUT">PUT</option>
                  </select>
                </div>
                <div class="form-group">
                  <label>超时 (ms)</label>
                  <input type="number" v-model.number="proxyCfg.timeout_ms" min="1000" max="120000" step="1000" />
                </div>
              </div>
              <div class="form-group">
                <label>请求 Headers (JSON)</label>
                <div class="cm-editor-wrap">
                  <Codemirror v-model="proxyHeadersStr" :extensions="cmExtensions" :style="{ height: '100px' }" />
                </div>
              </div>
              <div class="form-row">
                <div class="form-group">
                  <label>重试次数</label>
                  <input type="number" v-model.number="proxyCfg.retry" min="0" max="5" />
                </div>
              </div>
              <div class="form-group">
                <label>请求字段映射 (JSON)</label>
                <div class="cm-editor-wrap">
                  <Codemirror v-model="proxyReqMappingStr" :extensions="cmExtensions" :style="{ height: '100px' }" />
                </div>
                <div class="field-mapping-hint">
                  将输入字段映射到外部系统参数。例如：{ "query": "$.question" } 表示将输入的 question 字段作为外部系统的 query 参数。
                  <br>以 $. 开头表示引用输入字段，否则为固定值。
                </div>
              </div>
              <div class="form-group">
                <label>响应字段映射 (JSON)</label>
                <div class="cm-editor-wrap">
                  <Codemirror v-model="proxyRespMappingStr" :extensions="cmExtensions" :style="{ height: '100px' }" />
                </div>
                <div class="field-mapping-hint">
                  将外部系统返回字段映射到输出。例如：{ "result": "$.data" } 表示将外部返回的 data 字段作为输出的 result。
                </div>
              </div>
            </div>
          </div>

          <!-- Schema -->
          <div v-if="currentSection === 'schema'" class="section">
            <h3>输入输出 Schema</h3>
            <div class="form-group">
              <label>Input Schema (JSON) <button class="btn-link" @click="formatInputSchema">🎨 格式化</button></label>
              <div class="cm-editor-wrap">
                <Codemirror v-model="inputSchemaStr" :extensions="cmExtensions" :style="{ height: '220px' }" />
              </div>
            </div>
            <div class="form-group">
              <label>Output Schema (JSON) <button class="btn-link" @click="formatOutputSchema">🎨 格式化</button></label>
              <div class="cm-editor-wrap">
                <Codemirror v-model="outputSchemaStr" :extensions="cmExtensions" :style="{ height: '220px' }" />
              </div>
            </div>
          </div>

          <!-- 模型 -->
          <div v-if="currentSection === 'model'" class="section">
            <h3>模型配置</h3>
            <div class="form-group">
              <label>选择模型</label>
              <div class="model-selector">
                <div v-if="workspaceDefaultModel" class="default-model-hint">
                  工作空间默认模型：{{ workspaceDefaultModel }}
                </div>
                <select v-model="editingAgent.model" class="model-select">
                  <option value="">使用工作空间默认模型</option>
                  <option v-for="provider in availableModels" :key="provider.name" :value="provider.name">
                    {{ provider.name }} — {{ provider.model }} ({{ provider.kind }})
                  </option>
                </select>
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label>Temperature</label>
                <input v-model.number="editingAgent.temperature" type="number" step="0.1" min="0" max="2" />
              </div>
              <div class="form-group">
                <label>Max Tokens</label>
                <input v-model.number="editingAgent.max_tokens" type="number" min="256" max="128000" />
              </div>
            </div>
            <div class="form-group">
              <label>System Prompt（可选，会自动从配置生成）</label>
              <textarea v-model="editingAgent.system_prompt" rows="5"></textarea>
            </div>
          </div>

          <!-- 知识库 -->
          <div v-if="currentSection === 'knowledge'" class="section">
            <h3>📚 知识库管理</h3>
            
            <!-- 空间知识库（只读，可绑定） -->
            <div class="kb-section">
              <h4>🌍 空间知识库 <span class="kb-hint">（同空间 Agent 共享）</span></h4>
              <div v-if="workspaceKBs.length === 0" class="empty-hint">暂无空间知识库，请到「知识库」页面创建</div>
              <div v-for="kb in workspaceKBs" :key="kb.id" class="kb-card kb-card-readonly">
                <div class="kb-card-header">
                  <div class="kb-card-info">
                    <div class="kb-card-name">📁 {{ kb.name }}</div>
                    <div class="kb-card-meta">{{ kb.doc_count || 0 }} 个文档</div>
                  </div>
                  <div class="kb-card-actions">
                    <label class="toggle-label">
                      <input type="checkbox" :checked="editingAgent.knowledge_base_ids?.includes(kb.id)"
                        @change="toggleWorkspaceKB(kb.id)" />
                      <span>使用</span>
                    </label>
                    <button class="btn btn-ghost btn-sm" @click="toggleKBExpand(kb.id)">
                      {{ expandedKB === kb.id ? '收起' : '展开' }}
                    </button>
                  </div>
                </div>
                <div v-if="expandedKB === kb.id" class="kb-docs">
                  <div v-if="!kbDocs[kb.id] || kbDocs[kb.id].length === 0" class="empty-hint">暂无文档</div>
                  <div v-for="doc in (kbDocs[kb.id] || [])" :key="doc.id" class="kb-doc-item">
                    <span class="kb-doc-name">📄 {{ doc.name || doc.filename || '未命名' }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Agent 独立知识库（可创建、管理） -->
            <div class="kb-section">
              <h4>🔒 独立知识库 <span class="kb-hint">（仅当前 Agent 独享）</span></h4>
              <div class="kb-create-row">
                <input v-model="newKbName" placeholder="输入知识库名称" @keydown.enter="createAgentKB" />
                <button class="btn btn-primary btn-sm" @click="createAgentKB" :disabled="!newKbName.trim()">创建</button>
              </div>
              <div v-if="agentKBs.length === 0" class="empty-hint">暂无独立知识库</div>
              <div v-for="kb in agentKBs" :key="kb.id" class="kb-card">
                <div class="kb-card-header">
                  <div class="kb-card-info">
                    <div class="kb-card-name">📁 {{ kb.name }}</div>
                    <div class="kb-card-meta">{{ kb.doc_count || 0 }} 个文档</div>
                  </div>
                  <div class="kb-card-actions">
                    <label class="btn btn-ghost btn-sm">
                      📤 上传文件
                      <input type="file" multiple style="display:none" @change="uploadAgentKBFile($event, kb.id)" />
                    </label>
                    <button class="btn btn-ghost btn-sm" @click="toggleKBExpand(kb.id)">
                      {{ expandedKB === kb.id ? '收起' : '展开' }}
                    </button>
                    <button class="btn btn-danger btn-sm" @click="deleteAgentKB(kb.id)">🗑️</button>
                  </div>
                </div>
                <div v-if="expandedKB === kb.id" class="kb-docs">
                  <div v-if="!kbDocs[kb.id] || kbDocs[kb.id].length === 0" class="empty-hint">暂无文档</div>
                  <div v-for="doc in (kbDocs[kb.id] || [])" :key="doc.id" class="kb-doc-item">
                    <span class="kb-doc-name">📄 {{ doc.name || doc.filename || '未命名' }}</span>
                    <button class="btn btn-ghost btn-xs" @click="deleteAgentKBDoc(kb.id, doc.id)">🗑️</button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 版本 -->
          <div v-if="currentSection === 'versions'" class="section">
            <h3>版本历史</h3>
            <button class="btn btn-primary btn-sm" @click="createVersion" style="margin-bottom: 16px">
              创建新版本
            </button>
            <div v-for="v in versions" :key="v.id" class="version-item">
              <div class="version-header">
                <span class="version-number">v{{ v.version_number }}</span>
                <span v-if="v.is_current" class="badge badge-active">当前</span>
                <span v-if="v.is_published" class="badge badge-published">已发布</span>
              </div>
              <div class="version-meta">
                {{ new Date(v.created_at).toLocaleString('zh-CN') }}
              </div>
              <div v-if="v.release_notes" class="version-notes">{{ v.release_notes }}</div>
            </div>
            <div v-if="versions.length === 0" class="empty-hint">暂无版本</div>
          </div>
        </div>

        <!-- 右侧测试面板 -->
        <div class="editor-test">
          <h3>🧪 测试 Agent</h3>
          
          <!-- Quick templates -->
          <div class="form-group">
            <label>快速模板</label>
            <div class="test-templates">
              <button v-for="t in testTemplates" :key="t.name" class="test-template-btn" @click="applyTestTemplate(t)">
                {{ t.icon }} {{ t.name }}
              </button>
            </div>
          </div>

          <!-- Agent info hint -->
          <div v-if="editingAgent.role || editingAgent.name" class="test-agent-hint">
            <div v-if="editingAgent.role">角色：{{ editingAgent.role }}</div>
            <div v-if="editingAgent.name">名称：{{ editingAgent.name }}</div>
          </div>

          <div class="form-group">
            <label>输入 (JSON) <button class="btn-link" @click="formatTestInput">🎨 格式化</button></label>
            <div class="cm-editor-wrap cm-test">
              <Codemirror v-model="testInput" :extensions="cmExtensions" :style="{ height: '200px' }" />
            </div>
            <div v-if="testInputError" class="test-json-error">⚠️ JSON 格式错误：{{ testInputError }}</div>
          </div>
          <button class="btn btn-primary" @click="runTest" :disabled="testing || !testInput.trim()" style="width: 100%">
            {{ testing ? '⏳ 测试中...' : '▶ 运行测试' }}
          </button>
          
          <div v-if="testResult" class="test-result">
            <h4>测试结果</h4>
            <div :class="['result-status', testResult.success ? 'success' : 'error']">
              {{ testResult.success ? '✓ 测试通过' : '✗ 测试失败' }}
            </div>
            <div v-if="testResult.output_data" class="cm-editor-wrap cm-result">
              <Codemirror :model-value="JSON.stringify(testResult.output_data, null, 2)" :extensions="cmReadOnlyExtensions" :style="{ height: '200px' }" />
            </div>
            <div v-if="testResult.error" class="error-msg">{{ testResult.error }}</div>
            <div v-if="testResult.duration_ms" class="duration">耗时: {{ testResult.duration_ms }}ms</div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="toast.show" :class="['toast', 'toast-' + toast.type]">{{ toast.message }}</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick, shallowRef } from 'vue'
import { Codemirror } from 'vue-codemirror'
import { json } from '@codemirror/lang-json'
import { oneDark } from '@codemirror/theme-one-dark'
import { agentApi, configApi } from '../api'
import axios from 'axios'

const agents = ref([])
const editingAgent = ref(null)
const versions = ref([])
const providers = ref({})
const currentSection = ref('basic')
const saving = ref(false)
const publishing = ref(false)
const testing = ref(false)
const testInput = ref('')
const testResult = ref(null)
const knowledgeBases = ref([])
const newKbName = ref('')
const currentKbForUpload = ref(null)
const kbDocs = ref({})
const tagInput = ref('')
const toast = ref({ show: false, message: '', type: 'success' })
const availableModels = ref([])
const workspaceDefaultModel = ref('')
const showCropModal = ref(false)
const cropCanvas = ref(null)
const cropImage = ref(null)
const cropState = ref({ mode: 'none', startMouseX: 0, startMouseY: 0, startImgX: 0, startImgY: 0, startRadius: 0, startZoom: 1, imgX: 0, imgY: 0, zoom: 1, radius: 150 })

const presetAvatars = [
  { path: '/static/avatars/ceo.svg', label: 'CEO' },
  { path: '/static/avatars/analyst.svg', label: '分析师' },
  { path: '/static/avatars/engineer.svg', label: '工程师' },
  { path: '/static/avatars/marketing.svg', label: '营销' },
  { path: '/static/avatars/finance.svg', label: '财务' },
  { path: '/static/avatars/designer.svg', label: '设计师' },
  { path: '/static/avatars/assistant.svg', label: '助理' },
  { path: '/static/avatars/sales.svg', label: '销售' },
]

const personalityPresets = [
  '严谨认真', '理性分析', '主动沟通', '专业高效', '耐心细致',
  '创新思维', '批判性思维', '同理心强', '结果导向', '善于总结',
  '幽默风趣', '客观中立', '风险意识', '学习能力强', '执行力强'
]

const rolePresets = [
  { role: '产品经理', icon: '📋', desc: '负责需求分析、产品规划、PRD撰写、优先级排序', responsibilities: '1. 需求收集与分析，输出PRD文档\n2. 产品路线图规划与版本管理\n3. 竞品分析与市场调研\n4. 跨团队沟通协调（设计、开发、测试）\n5. 用户反馈收集与数据分析\n6. 产品上线效果跟踪与迭代' },
  { role: '前端工程师', icon: '🎨', desc: '负责Web/移动端界面开发、组件封装、性能优化', responsibilities: '1. 根据设计稿完成页面开发与联调\n2. 前端组件库建设与维护\n3. 前端性能优化（首屏加载、渲染性能）\n4. 兼容性处理与响应式适配\n5. 前端工程化建设（构建、部署、监控）\n6. 技术方案设计与代码评审' },
  { role: '后端工程师', icon: '⚙️', desc: '负责服务端架构、API设计、数据库优化', responsibilities: '1. 服务端架构设计与API接口开发\n2. 数据库设计与SQL优化\n3. 系统性能优化与高并发处理\n4. 代码质量保障（单测、集成测试）\n5. 线上问题排查与日志分析\n6. 技术文档编写与知识沉淀' },
  { role: '测试工程师', icon: '🔍', desc: '负责测试计划、用例设计、自动化测试', responsibilities: '1. 测试计划制定与测试用例设计\n2. 功能测试、回归测试、兼容性测试\n3. 自动化测试框架搭建与脚本编写\n4. 性能测试、安全测试\n5. Bug跟踪与质量报告输出\n6. 测试流程优化与工具建设' },
  { role: '数据分析师', icon: '📊', desc: '负责数据采集、分析建模、业务洞察', responsibilities: '1. 数据需求梳理与指标体系建设\n2. 数据清洗、ETL与报表开发\n3. 业务数据分析与专题分析\n4. A/B测试设计与效果评估\n5. 数据可视化看板搭建\n6. 业务洞察与策略建议输出' },
  { role: 'UI设计师', icon: '🖌️', desc: '负责界面视觉设计、交互原型、设计规范', responsibilities: '1. 产品界面视觉设计（Web/App）\n2. 交互原型设计与用户体验优化\n3. 设计规范与组件库维护\n4. 运营活动页面与banner设计\n5. 设计走查与开发还原度验收\n6. 设计趋势研究与创新能力提升' },
  { role: '内容运营', icon: '✍️', desc: '负责内容策划、文案撰写、用户增长', responsibilities: '1. 内容策划与选题规划\n2. 文案撰写（产品文案、营销文案）\n3. 内容审核与质量把控\n4. 用户运营策略制定与执行\n5. 数据分析与内容效果优化\n6. 社群运营与用户互动' },
  { role: '项目经理', icon: '📅', desc: '负责项目计划、进度管控、风险管理', responsibilities: '1. 项目计划制定与WBS分解\n2. 进度跟踪与风险识别管理\n3. 资源协调与跨部门沟通\n4. 项目会议组织与纪要输出\n5. 项目复盘与经验总结\n6. 流程优化与工具引入' },
  { role: '渠道运营', icon: '🔗', desc: '负责渠道拓展、合作管理、流量增长', responsibilities: '1. 渠道拓展与合作伙伴开发\n2. 渠道合作协议谈判与签订\n3. 渠道数据分析与效果评估\n4. 渠道政策制定与优化\n5. 竞品渠道监测与情报收集\n6. 渠道活动策划与执行' },
  { role: '销售经理', icon: '💰', desc: '负责客户开发、商务谈判、业绩达成', responsibilities: '1. 客户开发与需求挖掘\n2. 商务谈判与合同签订\n3. 销售目标制定与分解\n4. 客户关系维护与续约管理\n5. 销售数据分析与预测\n6. 销售团队培训与赋能' },
  { role: '品牌策划', icon: '🏷️', desc: '负责品牌定位、传播策略、品牌资产管理', responsibilities: '1. 品牌定位与价值主张提炼\n2. 品牌传播策略制定与执行\n3. 品牌视觉规范管理\n4. 品牌活动策划与落地\n5. 品牌舆情监测与危机应对\n6. 品牌效果评估与策略迭代' },
  { role: '营销策划', icon: '📣', desc: '负责营销方案、活动策划、推广投放', responsibilities: '1. 营销方案策划与预算管理\n2. 线上线下活动策划与执行\n3. 广告投放策略与效果优化\n4. 用户增长策略制定与落地\n5. 营销数据分析与ROI评估\n6. 跨部门协作推动营销目标达成' },
  { role: '人力资源', icon: '👥', desc: '负责招聘、培训、绩效、员工关系', responsibilities: '1. 招聘需求分析与人才寻访\n2. 面试评估与录用决策\n3. 员工培训体系搭建与实施\n4. 绩效考核方案设计与执行\n5. 员工关系管理与文化活动\n6. 薪酬福利体系优化' },
  { role: '财务分析师', icon: '💹', desc: '负责财务分析、预算管理、风控合规', responsibilities: '1. 财务报表分析与经营洞察\n2. 年度预算编制与执行监控\n3. 成本分析与降本增效建议\n4. 投资项目财务评估\n5. 税务筹划与合规管理\n6. 财务风险识别与预警' },
  { role: '客服主管', icon: '🎧', desc: '负责客户服务、工单管理、满意度提升', responsibilities: '1. 客服团队日常管理与排班\n2. 服务流程优化与SOP制定\n3. 客户投诉处理与升级机制\n4. 客户满意度调研与改善\n5. 客服数据分析与报表输出\n6. 知识库建设与培训赋能' },
]

const inputSchemaExample = JSON.stringify({
  type: "object",
  properties: {
    requirement: { type: "string", description: "需求描述" },
    target_users: { type: "array", items: { type: "string" }, description: "目标用户群体" },
    priority: { type: "string", enum: ["high", "medium", "low"], description: "优先级" }
  },
  required: ["requirement"]
}, null, 2)

const outputSchemaExample = JSON.stringify({
  type: "object",
  properties: {
    summary: { type: "string", description: "分析摘要" },
    suggestions: { type: "array", items: { type: "string" }, description: "建议列表" },
    confidence: { type: "number", description: "置信度 0-1" }
  },
  required: ["summary", "suggestions"]
}, null, 2)

// CodeMirror setup
const cmExtensions = [json(), oneDark]
const cmReadOnlyExtensions = [json(), oneDark]

const formatInputSchema = () => {
  try { inputSchemaStr.value = JSON.stringify(JSON.parse(inputSchemaStr.value), null, 2) } catch {}
}
const formatOutputSchema = () => {
  try { outputSchemaStr.value = JSON.stringify(JSON.parse(outputSchemaStr.value), null, 2) } catch {}
}

// Proxy config
const proxyCfg = computed({
  get: () => editingAgent.value?.proxy_config || { endpoint: '', method: 'POST', headers: {}, timeout_ms: 30000, retry: 0, request_mapping: {}, response_mapping: {} },
  set: (v) => { if (editingAgent.value) editingAgent.value.proxy_config = v }
})

const proxyHeadersStr = computed({
  get: () => JSON.stringify(proxyCfg.value.headers || {}, null, 2),
  set: (val) => { try { proxyCfg.value.headers = JSON.parse(val) } catch {} }
})

const proxyReqMappingStr = computed({
  get: () => JSON.stringify(proxyCfg.value.request_mapping || {}, null, 2),
  set: (val) => { try { proxyCfg.value.request_mapping = JSON.parse(val) } catch {} }
})

const proxyRespMappingStr = computed({
  get: () => JSON.stringify(proxyCfg.value.response_mapping || {}, null, 2),
  set: (val) => { try { proxyCfg.value.response_mapping = JSON.parse(val) } catch {} }
})

const sections = [
  { id: 'basic', icon: '📋', name: '基础信息' },
  { id: 'personality', icon: '🎭', name: '人格' },
  { id: 'role', icon: '💼', name: '职责' },
  { id: 'boundary', icon: '🚧', name: '工作边界' },
  { id: 'behavior', icon: '⚙️', name: '工作方式' },
  { id: 'proxy', icon: '🔗', name: 'Proxy 配置' },
  { id: 'schema', icon: '📝', name: 'Schema' },
  { id: 'model', icon: '🤖', name: '模型' },
  { id: 'versions', icon: '📦', name: '版本' },
  { id: 'knowledge', icon: '📚', name: '知识库' },
]

const statusText = (status) => {
  const map = { draft: '草稿', active: '已发布', disabled: '已禁用', archived: '已归档' }
  return map[status] || status
}

const inputSchemaStr = computed({
  get: () => {
    const v = editingAgent.value?.input_schema
    if (v && Object.keys(v).length > 0) return JSON.stringify(v, null, 2)
    return inputSchemaExample
  },
  set: (val) => {
    try { editingAgent.value.input_schema = JSON.parse(val) } catch {}
  }
})

const outputSchemaStr = computed({
  get: () => {
    const v = editingAgent.value?.output_schema
    if (v && Object.keys(v).length > 0) return JSON.stringify(v, null, 2)
    return outputSchemaExample
  },
  set: (val) => {
    try { editingAgent.value.output_schema = JSON.parse(val) } catch {}
  }
})

const showToast = (message, type = 'success') => {
  toast.value = { show: true, message, type }
  setTimeout(() => { toast.value.show = false }, 3000)
}

const loadAvailableModels = async () => {
  try {
    const { data } = await agentApi.listModels()
    availableModels.value = data.providers || []
    workspaceDefaultModel.value = data.default_provider || ''
  } catch (e) {
    console.error('Failed to load models:', e)
  }
}



const appendPersonality = (trait) => {
  if (!editingAgent.value) return
  const current = editingAgent.value.personality || ''
  const line = '- ' + trait
  if (current.includes(trait)) return
  editingAgent.value.personality = current ? current + '\n' + line : line
}

const applyRolePreset = (rp) => {
  if (!editingAgent.value) return
  editingAgent.value.role = rp.role
  editingAgent.value.responsibilities = rp.responsibilities
  showToast('已填入「' + rp.role + '」预设内容')
}

// --- Boundary Presets ---
const boundaryPresets = [
  { icon: '🔒', name: '保守型', desc: '严格按指令执行，不主动扩展任务范围', value: '【工作边界 - 保守型】\n✅ 可以做：\n- 严格按用户指令完成指定任务\n- 在已有知识范围内回答问题\n- 提供客观事实和数据\n\n❌ 不可以做：\n- 不主动扩展任务范围\n- 不执行未经确认的高风险操作\n- 不访问或修改未授权的资源' },
  { icon: '⚖️', name: '标准型', desc: '职责范围内主动思考，超出范围需确认', value: '【工作边界 - 标准型】\n✅ 可以做：\n- 在职责范围内主动分析和提供建议\n- 识别潜在问题并预警\n- 推荐优化方案\n\n⚠️ 需要确认：\n- 超出当前任务范围的额外操作\n- 涉及资金、权限变更的操作\n- 对外发布或通知类操作\n\n❌ 不可以做：\n- 未经确认删除重要数据\n- 绕过审批流程' },
  { icon: '🚀', name: '激进型', desc: '主动发现问题并解决，大胆提供建议', value: '【工作边界 - 激进型】\n✅ 可以做：\n- 主动发现问题并提出解决方案\n- 大胆给出创新性建议\n- 跨领域关联分析\n- 持续追问直到问题根因明确\n\n⚠️ 需要确认：\n- 直接执行影响生产环境的操作\n- 替代他人做决策\n\n❌ 不可以做：\n- 违反法律法规的操作\n- 泄露敏感信息' },
  { icon: '🎯', name: '协作型', desc: '主动协调资源，推动跨角色协作', value: '【工作边界 - 协作型】\n✅ 可以做：\n- 主动识别需要协作的环节\n- 推荐合适的协作角色或工具\n- 整合多方输入给出综合方案\n- 跟踪协作进度并提醒\n\n⚠️ 需要确认：\n- 代替其他角色做决策\n- 调整他人工作优先级\n\n❌ 不可以做：\n- 未经沟通直接分配任务给他人' },
  { icon: '🛡️', name: '合规型', desc: '严格遵守流程规范，留痕可审计', value: '【工作边界 - 合规型】\n✅ 可以做：\n- 按标准流程执行每一步\n- 记录操作日志和决策依据\n- 对照规范逐项检查\n\n⚠️ 需要确认：\n- 任何流程外的变通操作\n\n❌ 不可以做：\n- 跳过审批或检查环节\n- 未记录直接修改数据\n- 违反数据安全规范' },
]

const applyBoundaryPreset = (bp) => {
  if (!editingAgent.value) return
  editingAgent.value.boundaries = bp.value
  showToast('已填入「' + bp.name + '」边界预设')
}

// --- Behavior Presets ---
const behaviorPresets = [
  { icon: '📋', name: '结构化输出', desc: '分步骤、分模块输出，注重逻辑层次', value: '【工作方式 - 结构化输出】\n1. 先理解问题，确认关键需求\n2. 拆解为子任务，按优先级排列\n3. 逐项分析并输出结论\n4. 汇总关键发现和行动建议\n5. 标注需要人工确认的事项' },
  { icon: '🔄', name: '迭代式', desc: '先出草稿，再逐步完善优化', value: '【工作方式 - 迭代式】\n1. 快速输出初版方案（80%完成度）\n2. 自我审查，找出不足和遗漏\n3. 补充细节，优化表达\n4. 再次检查一致性和完整性\n5. 输出最终版本并标注改动点' },
  { icon: '❓', name: '追问式', desc: '先提问澄清，再给出精准方案', value: '【工作方式 - 追问式】\n1. 分析输入，识别模糊或缺失信息\n2. 提出关键澄清问题（最多3个）\n3. 基于澄清结果调整理解\n4. 给出针对性方案\n5. 说明假设前提和适用范围' },
  { icon: '📊', name: '数据驱动', desc: '基于数据和证据做判断，量化分析', value: '【工作方式 - 数据驱动】\n1. 收集相关数据和事实\n2. 进行定量分析和对比\n3. 基于数据得出结论\n4. 用数据支撑每条建议\n5. 标注数据来源和置信度' },
  { icon: '🧠', name: '思维链', desc: '展示完整推理过程，逐步推导', value: '【工作方式 - 思维链】\n1. 明确问题本质和约束条件\n2. 列出可能的解决路径\n3. 评估每条路径的优劣\n4. 选择最优路径并推导\n5. 给出结论和备选方案' },
  { icon: '⚡', name: '敏捷响应', desc: '快速给出核心结论，细节按需补充', value: '【工作方式 - 敏捷响应】\n1. 直接给出核心结论或操作建议\n2. 简要说明理由（1-2句）\n3. 标注可深入展开的方向\n4. 根据反馈决定是否展开细节\n5. 保持回复简洁高效' },
  { icon: '🎯', name: '目标导向', desc: '围绕最终目标反推，聚焦可落地动作', value: '【工作方式 - 目标导向】\n1. 明确最终目标和成功标准\n2. 反推达成目标的关键路径\n3. 识别当前差距和障碍\n4. 给出具体可执行的下一步\n5. 量化预期效果和时间线' },
  { icon: '🔍', name: '根因分析', desc: '深入分析问题本质，不止于表面', value: '【工作方式 - 根因分析】\n1. 描述问题现象和影响范围\n2. 用5Why或鱼骨图追溯根因\n3. 区分症状和根本原因\n4. 针对根因设计解决方案\n5. 制定预防措施防止复发' },
]

const applyBehaviorPreset = (bp) => {
  if (!editingAgent.value) return
  editingAgent.value.behavior = bp.value
  showToast('已填入「' + bp.name + '」工作方式预设')
}

// --- Avatar Crop ---
const handleAvatarUpload = async (event) => {
  const file = event.target.files[0]
  if (!file || !editingAgent.value) return
  if (file.size > 5 * 1024 * 1024) { showToast('图片大小不能超过 5MB'); return }
  
  const reader = new FileReader()
  reader.onload = (e) => {
    const img = new Image()
    img.onload = () => {
      cropImage.value = img
      cropState.value = { mode: 'none', startMouseX: 0, startMouseY: 0, startImgX: 0, startImgY: 0, startRadius: 0, startZoom: 1, imgX: 0, imgY: 0, zoom: 1, radius: 150 }
      showCropModal.value = true
      nextTick(() => drawCropCanvas())
    }
    img.src = e.target.result
  }
  reader.readAsDataURL(file)
  event.target.value = ''
}

const drawCropCanvas = () => {
  const canvas = cropCanvas.value
  if (!canvas || !cropImage.value) return
  const ctx = canvas.getContext('2d')
  const img = cropImage.value
  const cs = cropState.value

  // Scale image so the shorter side fills the canvas, apply zoom
  const baseScale = Math.max(400 / img.width, 400 / img.height)
  const scale = baseScale * cs.zoom
  const sw = img.width * scale
  const sh = img.height * scale
  // Default centered position (accounts for panning offsets)
  const sx = (400 - sw) / 2 + cs.imgX
  const sy = (400 - sh) / 2 + cs.imgY

  ctx.clearRect(0, 0, 400, 400)

  // Draw image
  ctx.drawImage(img, sx, sy, sw, sh)

  // Dark overlay with circle cutout
  ctx.save()
  ctx.fillStyle = 'rgba(0,0,0,0.55)'
  ctx.fillRect(0, 0, 400, 400)
  ctx.globalCompositeOperation = 'destination-out'
  ctx.beginPath()
  ctx.arc(200, 200, cs.radius, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()

  // Circle border
  ctx.strokeStyle = 'rgba(255,255,255,0.9)'
  ctx.lineWidth = 2
  ctx.setLineDash([6, 3])
  ctx.beginPath()
  ctx.arc(200, 200, cs.radius, 0, Math.PI * 2)
  ctx.stroke()
  ctx.setLineDash([])

  // Resize handle on circle edge (bottom-right)
  const hx = 200 + cs.radius * Math.cos(Math.PI / 4)
  const hy = 200 + cs.radius * Math.sin(Math.PI / 4)
  ctx.fillStyle = '#fff'
  ctx.beginPath()
  ctx.arc(hx, hy, 6, 0, Math.PI * 2)
  ctx.fill()
  ctx.strokeStyle = 'var(--primary)'
  ctx.lineWidth = 2
  ctx.stroke()
}

const onCropMouseDown = (e) => {
  const canvas = cropCanvas.value
  if (!canvas) return
  const rect = canvas.getBoundingClientRect()
  const x = (e.clientX - rect.left) * (400 / rect.width)
  const y = (e.clientY - rect.top) * (400 / rect.height)
  const cs = cropState.value

  // Check if near resize handle (bottom-right of circle)
  const hx = 200 + cs.radius * Math.cos(Math.PI / 4)
  const hy = 200 + cs.radius * Math.sin(Math.PI / 4)
  if (Math.hypot(x - hx, y - hy) < 14) {
    cs.mode = 'resize'
    cs.startMouseX = x; cs.startMouseY = y
    cs.startRadius = cs.radius
  } else {
    // Pan mode: drag the image
    cs.mode = 'pan'
    cs.startMouseX = x; cs.startMouseY = y
    cs.startImgX = cs.imgX; cs.startImgY = cs.imgY
  }
}
const onCropMouseMove = (e) => {
  const cs = cropState.value
  if (cs.mode === 'none') return
  const canvas = cropCanvas.value
  if (!canvas) return
  const rect = canvas.getBoundingClientRect()
  const x = (e.clientX - rect.left) * (400 / rect.width)
  const y = (e.clientY - rect.top) * (400 / rect.height)

  if (cs.mode === 'resize') {
    const dist = Math.hypot(x - 200, y - 200)
    cs.radius = Math.max(40, Math.min(190, dist))
  } else if (cs.mode === 'pan') {
    cs.imgX = cs.startImgX + (x - cs.startMouseX)
    cs.imgY = cs.startImgY + (y - cs.startMouseY)
    // Clamp so image doesn't go too far
    const img = cropImage.value
    if (img) {
      const scale = Math.max(400 / img.width, 400 / img.height)
      const sw = img.width * scale / 2
      const sh = img.height * scale / 2
      const maxOff = Math.max(sw - 200, 0)
      const maxOffY = Math.max(sh - 200, 0)
      cs.imgX = Math.max(-maxOff, Math.min(maxOff, cs.imgX))
      cs.imgY = Math.max(-maxOffY, Math.min(maxOffY, cs.imgY))
    }
  }
  drawCropCanvas()
}
const onCropMouseUp = () => { cropState.value.mode = 'none' }

const cropZoom = (delta) => {
  const cs = cropState.value
  cs.zoom = Math.max(0.3, Math.min(5, cs.zoom + delta))
  drawCropCanvas()
}
const cropZoomReset = () => {
  cropState.value.zoom = 1
  cropState.value.imgX = 0
  cropState.value.imgY = 0
  drawCropCanvas()
}

const confirmCrop = async () => {
  const canvas = cropCanvas.value
  if (!canvas || !cropImage.value) return
  
  const tmp = document.createElement('canvas')
  tmp.width = 400; tmp.height = 400
  const ctx = tmp.getContext('2d')
  
  const img = cropImage.value
  const cs = cropState.value
  const baseScale = Math.max(400 / img.width, 400 / img.height)
  const scale = baseScale * cs.zoom
  const sw = img.width * scale
  const sh = img.height * scale
  const sx = (400 - sw) / 2 + cs.imgX
  const sy = (400 - sh) / 2 + cs.imgY
  
  ctx.beginPath()
  ctx.arc(200, 200, cs.radius, 0, Math.PI * 2)
  ctx.clip()
  ctx.drawImage(img, sx, sy, sw, sh)
  
  // Convert to blob and upload
  tmp.toBlob(async (blob) => {
    if (!blob) return
    const file = new File([blob], 'avatar.png', { type: 'image/png' })
    showCropModal.value = false
    try {
      if (editingAgent.value.id) {
        const { data } = await agentApi.uploadAvatar(editingAgent.value.id, file)
        editingAgent.value.avatar = data.avatar
      } else {
        editingAgent.value.avatar = URL.createObjectURL(blob)
      }
      showToast('头像上传成功')
    } catch (e) {
      showToast('头像上传失败: ' + (e.response?.data?.detail || e.message))
    }
  }, 'image/png')
}

const cancelCrop = () => { showCropModal.value = false; cropImage.value = null; cropState.value = { mode: 'none', startMouseX: 0, startMouseY: 0, startImgX: 0, startImgY: 0, startRadius: 0, startZoom: 1, imgX: 0, imgY: 0, zoom: 1, radius: 150 } }

const currentWorkspace = () => localStorage.getItem('currentWorkspace')

const loadAgents = async () => {
  try {
    const { data } = await agentApi.list(currentWorkspace())
    agents.value = data
  } catch (e) {
    console.error(e)
  }
}

const loadProviders = async () => {
  try {
    const { data } = await configApi.get()
    providers.value = data.providers || {}
  } catch (e) {
    console.error(e)
  }
}

const createNewAgent = async () => {
  const ws = currentWorkspace()
  if (!ws) { alert('请先选择工作空间'); return }
  try {
    const { data } = await agentApi.create(ws, { name: '新智能体', agent_type: 'llm' })
    editingAgent.value = { ...data }
    await loadAgents()
  } catch (e) {
    alert('创建失败: ' + (e.response?.data?.detail || e.message))
  }
}

const editAgent = (agent) => {
  editingAgent.value = { ...agent }
  currentSection.value = 'basic'
  loadVersions(agent.id)
  loadKnowledgeBases()
}

const saveAndExit = async () => {
  await saveAgent()
  editingAgent.value = null
  loadAgents()
}

const saveAgent = async () => {
  if (!editingAgent.value) return
  saving.value = true
  try {
    const { id, ...data } = editingAgent.value
    await agentApi.update(id, data)
    showToast('保存成功')
  } catch (e) {
    alert('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

const publishAgent = async () => {
  if (!editingAgent.value) return
  publishing.value = true
  try {
    // Auto-save before publish
    const { id, ...saveData } = editingAgent.value
    await agentApi.update(id, saveData)
    
    const { data } = await agentApi.publish(id)
    if (data.success) {
      editingAgent.value.status = 'active'
      showToast('发布成功 v' + data.version_number)
      loadVersions(id)
    } else {
      alert('发布失败:\n' + data.errors.join('\n'))
    }
  } catch (e) {
    alert('发布失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    publishing.value = false
  }
}

const loadVersions = async (agentId) => {
  try {
    const { data } = await agentApi.versions(agentId)
    versions.value = data
  } catch (e) {
    console.error(e)
  }
}

const createVersion = async () => {
  try {
    await agentApi.createVersion(editingAgent.value.id)
    await loadVersions(editingAgent.value.id)
    showToast('版本创建成功')
  } catch (e) {
    alert('创建失败: ' + (e.response?.data?.detail || e.message))
  }
}

const testInputError = ref('')

const testTemplates = [
  { icon: '💬', name: '通用问答', data: { question: '请介绍一下你自己', context: '' } },
  { icon: '📝', name: '内容生成', data: { topic: '人工智能发展趋势', style: '专业分析', length: '500字' } },
  { icon: '🔍', name: '需求分析', data: { requirement: '设计一个新能源汽车车主APP', target_users: ['25-35岁城市用户'], priority: 'high' } },
  { icon: '📊', name: '数据分析', data: { dataset: '月度销售数据', period: '2024年Q1', metrics: ['销售额', '转化率', '复购率'] } },
  { icon: '📋', name: '方案评审', data: { project: '微服务架构升级', proposal: '将单体应用拆分为订单、用户、支付三个核心服务', criteria: ['可行性', '成本', '风险'] } },
  { icon: '💡', name: '创意头脑风暴', data: { theme: '提升用户留存的创新方案', constraints: ['预算50万', '2周内可落地'], count: 5 } },
]

const testPlaceholder = computed(() => {
  const schema = editingAgent.value?.input_schema
  if (schema && schema.properties && Object.keys(schema.properties).length > 0) {
    const example = {}
    for (const [key, prop] of Object.entries(schema.properties)) {
      if (prop.type === 'string') example[key] = prop.description || key
      else if (prop.type === 'array') example[key] = [prop.description || 'item']
      else if (prop.type === 'number' || prop.type === 'integer') example[key] = 0
      else if (prop.type === 'boolean') example[key] = true
      else example[key] = null
    }
    return JSON.stringify(example, null, 2)
  }
  return '{\n  "question": "请帮我分析一下这个需求",\n  "context": "这是一个面向C端用户的社交产品"\n}'
})

const applyTestTemplate = (t) => {
  testInput.value = JSON.stringify(t.data, null, 2)
  testInputError.value = ''
}

const formatTestInput = () => {
  try {
    const parsed = JSON.parse(testInput.value)
    testInput.value = JSON.stringify(parsed, null, 2)
    testInputError.value = ''
  } catch (e) {
    testInputError.value = e.message
  }
}

// Watch testInput for JSON errors in real-time
watch(testInput, (val) => {
  if (!val.trim()) { testInputError.value = ''; return }
  try { JSON.parse(val); testInputError.value = '' }
  catch (e) { testInputError.value = e.message }
})

const runTest = async () => {
  if (!editingAgent.value || !testInput.value.trim()) return
  testing.value = true
  testResult.value = null
  testInputError.value = ''
  try {
    const input = JSON.parse(testInput.value)
    const { data } = await agentApi.test(editingAgent.value.id, { input_data: input })
    testResult.value = data
  } catch (e) {
    if (e instanceof SyntaxError) {
      testInputError.value = e.message
    } else {
      testResult.value = { success: false, error: e.response?.data?.detail || e.message }
    }
  } finally {
    testing.value = false
  }
}

const deleteAgent = async (id) => {
  if (!confirm('确定删除此智能体吗？')) return
  try {
    await agentApi.delete(id)
    await loadAgents()
    showToast('智能体已删除')
  } catch (e) {
    alert('删除失败')
  }
}

const testAgent = (agent) => {
  editAgent(agent)
  currentSection.value = 'basic'
}

const chatWithAgent = (agent) => {
  localStorage.setItem('chatAgentId', agent.id)
  window.location.href = '/chat'
}

const addTag = () => {
  if (tagInput.value && editingAgent.value) {
    editingAgent.value.tags = [...(editingAgent.value.tags || []), tagInput.value]
    tagInput.value = ''
  }
}

const removeTag = (i) => {
  editingAgent.value.tags.splice(i, 1)
}


const knowledgeApi = {
  list: (params = {}) => axios.get('/api/knowledge', { params }),
  create: (data) => axios.post('/api/knowledge', data),
  detail: (id) => axios.get(`/api/knowledge/${id}`),
  delete: (id) => axios.delete(`/api/knowledge/${id}`),
  addDoc: (kbId, data) => axios.post(`/api/knowledge/${kbId}/documents`, data),
  uploadFile: (kbId, file) => {
    const fd = new FormData()
    fd.append('file', file)
    return axios.post(`/api/knowledge/${kbId}/upload`, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
  deleteDoc: (kbId, docId) => axios.delete(`/api/knowledge/${kbId}/documents/${docId}`),
}

const workspaceKBs = ref([])
const agentKBs = ref([])
const expandedKB = ref(null)

const loadKnowledgeBases = async () => {
  if (!editingAgent.value) return
  try {
    // Load workspace KBs
    const { data: wsKBs } = await knowledgeApi.list({ scope: 'workspace' })
    workspaceKBs.value = wsKBs
    for (const kb of wsKBs) {
      try {
        const { data: detail } = await knowledgeApi.detail(kb.id)
        kb.doc_count = detail.documents ? detail.documents.length : 0
        kbDocs.value[kb.id] = detail.documents || []
      } catch { kb.doc_count = 0; kbDocs.value[kb.id] = [] }
    }
    // Load agent-specific KBs
    const { data: agKBs } = await knowledgeApi.list({ agent_id: editingAgent.value.id })
    agentKBs.value = agKBs
    for (const kb of agKBs) {
      try {
        const { data: detail } = await knowledgeApi.detail(kb.id)
        kb.doc_count = detail.documents ? detail.documents.length : 0
        kbDocs.value[kb.id] = detail.documents || []
      } catch { kb.doc_count = 0; kbDocs.value[kb.id] = [] }
    }
  } catch {}
}

const createAgentKB = async () => {
  if (!newKbName.value.trim() || !editingAgent.value) return
  try {
    await knowledgeApi.create({ name: newKbName.value.trim(), type: 'documents', agent_id: editingAgent.value.id })
    newKbName.value = ''
    await loadKnowledgeBases()
  } catch (e) { alert('创建失败: ' + (e.response?.data?.detail || e.message)) }
}

const toggleWorkspaceKB = (kbId) => {
  if (!editingAgent.value) return
  if (!editingAgent.value.knowledge_base_ids) editingAgent.value.knowledge_base_ids = []
  const idx = editingAgent.value.knowledge_base_ids.indexOf(kbId)
  if (idx >= 0) {
    editingAgent.value.knowledge_base_ids.splice(idx, 1)
  } else {
    editingAgent.value.knowledge_base_ids.push(kbId)
  }
}

const toggleKBExpand = async (kbId) => {
  if (expandedKB.value === kbId) { expandedKB.value = null; return }
  expandedKB.value = kbId
  if (!kbDocs.value[kbId]) {
    try {
      const { data: detail } = await knowledgeApi.detail(kbId)
      kbDocs.value[kbId] = detail.documents || []
    } catch { kbDocs.value[kbId] = [] }
  }
}

const uploadAgentKBFile = async (event, kbId) => {
  const files = event.target.files
  if (!files) return
  for (const file of files) {
    try {
      await knowledgeApi.uploadFile(kbId, file)
      const { data: detail } = await knowledgeApi.detail(kbId)
      kbDocs.value[kbId] = detail.documents || []
      const kb = agentKBs.value.find(k => k.id === kbId)
      if (kb) kb.doc_count = detail.documents ? detail.documents.length : 0
    } catch (e) { alert('上传失败: ' + (e.response?.data?.detail || e.message)) }
  }
  event.target.value = ''
}

const deleteAgentKB = async (kbId) => {
  if (!confirm('确定删除该独立知识库？')) return
  try {
    await knowledgeApi.delete(kbId)
    await loadKnowledgeBases()
  } catch (e) { alert('删除失败', 'error') }
}

const deleteAgentKBDoc = async (kbId, docId) => {
  try {
    await knowledgeApi.deleteDoc(kbId, docId)
    const { data: detail } = await knowledgeApi.detail(kbId)
    kbDocs.value[kbId] = detail.documents || []
    const kb = agentKBs.value.find(k => k.id === kbId)
    if (kb) kb.doc_count = detail.documents ? detail.documents.length : 0
  } catch (e) { alert('删除失败', 'error') }
}

const getKbName = (kbId) => {
  const all = [...workspaceKBs.value, ...agentKBs.value]
  const kb = all.find(k => k.id === kbId)
  return kb ? kb.name : '未知知识库'
}

const getKbDocs = (kbId) => kbDocs.value[kbId] || []


onMounted(() => {
  loadAgents()
  loadKnowledgeBases()
  loadProviders()
  loadAvailableModels()
  window.addEventListener('workspace-changed', loadAgents)
})
</script>

<style scoped>
.agents-page { padding: 0; }
.page-header {
  display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 32px;
}
.page-header h1 { font-size: 24px; font-weight: 700; margin-bottom: 4px; }
.subtitle { font-size: 14px; color: var(--text2); }

.agents-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px;
}
.agent-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 20px; cursor: pointer; transition: all 0.2s;
}
.agent-card:hover { border-color: var(--primary); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
.agent-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.agent-avatar { font-size: 32px; width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; background: var(--surface2); border-radius: var(--radius-sm); }
.agent-info { flex: 1; }
.agent-name { font-weight: 600; font-size: 15px; }
.agent-role { font-size: 13px; color: var(--accent); }
.agent-desc { font-size: 13px; color: var(--text2); margin-bottom: 12px; line-height: 1.5; }
.agent-meta { display: flex; gap: 12px; font-size: 12px; color: var(--text3); margin-bottom: 12px; }
.agent-actions { display: flex; gap: 8px; justify-content: flex-end; }
.status-badge { padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 500; }
.status-draft { background: var(--surface2); color: var(--text3); }
.status-active { background: var(--success-bg); color: var(--success); }
.status-disabled { background: var(--danger-bg); color: var(--danger); }

/* Editor */
.agent-editor { display: flex; flex-direction: column; height: calc(100vh - 120px); }
.editor-header {
  display: flex; align-items: center; justify-content: space-between;
  padding-bottom: 16px; border-bottom: 1px solid var(--border); margin-bottom: 16px;
}
.editor-title { display: flex; align-items: center; gap: 12px; }
.editor-title h2 { font-size: 18px; font-weight: 600; margin: 0; }
.editor-actions { display: flex; gap: 8px; }

.editor-layout { display: flex; flex: 1; gap: 24px; overflow: hidden; }
.editor-nav {
  width: 160px; flex-shrink: 0; background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 8px;
}
.editor-nav .nav-item {
  display: flex; align-items: center; gap: 8px; padding: 10px 12px;
  border-radius: var(--radius-sm); cursor: pointer; font-size: 14px; color: var(--text2);
  transition: all 0.15s;
}
.editor-nav .nav-item:hover { background: var(--surface2); color: var(--text); }
.editor-nav .nav-item.active { background: var(--primary); color: var(--primary-text); }

.editor-content {
  flex: 1; background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 32px; overflow-y: auto;
}
.section h3 { font-size: 16px; font-weight: 600; margin-bottom: 20px; }

.editor-test {
  width: 400px; flex-shrink: 0; background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 20px; overflow-y: auto;
}
.editor-test h3 { font-size: 14px; font-weight: 600; margin-bottom: 16px; }

.form-group { margin-bottom: 16px; }
.form-group label { display: block; font-size: 14px; font-weight: 600; margin-bottom: 8px; }
.form-group input, .form-group select, .form-group textarea {
  width: 100%; padding: 12px 16px; background: var(--surface2); border: 1px solid var(--border);
  border-radius: var(--radius-sm); color: var(--text); font-size: 14px;
}
.form-group input:focus, .form-group select:focus, .form-group textarea:focus {
  outline: none; border-color: var(--primary);
}
.form-group .mono { font-family: monospace; font-size: 13px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

.tags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.tag {
  display: flex; align-items: center; gap: 4px; padding: 4px 8px;
  background: var(--surface2); border-radius: 4px; font-size: 12px;
}
.tag button { background: none; border: none; color: var(--text3); cursor: pointer; }

.btn {
  display: inline-flex; align-items: center; gap: 6px; padding: 10px 20px;
  border: none; border-radius: var(--radius-sm); font-size: 14px; font-weight: 600;
  cursor: pointer; transition: all 0.2s;
}
.btn-primary { background: var(--primary); color: var(--primary-text); }
.btn-primary:hover { background: var(--primary-hover); }
.btn-ghost { background: transparent; color: var(--text2); border: 1px solid var(--border); }
.btn-ghost:hover { background: var(--surface2); }
.btn-danger { background: var(--danger-bg); color: var(--danger); border: 1px solid rgba(185,28,28,0.2); }
.btn-sm { padding: 6px 12px; font-size: 13px; }

.badge { padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 500; }
.badge-active { background: var(--success-bg); color: var(--success); }
.badge-published { background: #EEF2FF; color: #4F46E5; }

.version-item {
  padding: 12px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  margin-bottom: 8px;
}
.version-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.version-number { font-weight: 600; }
.version-meta { font-size: 12px; color: var(--text3); }
.version-notes { font-size: 13px; color: var(--text2); margin-top: 8px; }
.section-hint { font-size: 13px; color: var(--text3); margin-bottom: 16px; }
.kb-list { display: flex; flex-direction: column; gap: 6px; }
.kb-checkbox {
  display: flex; align-items: center; gap: 8px; padding: 10px 12px;
  background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius-sm);
  cursor: pointer; transition: all 0.15s; font-size: 13px;
}
.kb-checkbox:hover { border-color: var(--primary); }
.kb-checkbox input { accent-color: var(--primary); }
.kb-name { flex: 1; font-weight: 500; }
.kb-count { font-size: 12px; color: var(--text3); }
.kb-create { display: flex; gap: 8px; }
.kb-create input { flex: 1; padding: 8px 12px; background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius-sm); font-size: 13px; }
.kb-create input:focus { outline: none; border-color: var(--primary); }
.kb-doc-section { margin-top: 12px; padding: 12px; background: var(--surface2); border-radius: var(--radius-sm); }
.kb-doc-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-weight: 500; font-size: 13px; }
.kb-doc-list { display: flex; flex-direction: column; gap: 4px; }
.kb-doc-item { display: flex; align-items: center; gap: 8px; padding: 6px 8px; font-size: 12px; background: var(--surface); border-radius: 4px; }
.kb-doc-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.empty-hint { text-align: center; color: var(--text3); font-size: 13px; padding: 20px; }

.test-result { margin-top: 16px; }
.test-result h4 { font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.result-status { padding: 8px 12px; border-radius: var(--radius-sm); font-size: 13px; font-weight: 500; margin-bottom: 8px; }
.result-status.success { background: var(--success-bg); color: var(--success); }
.result-status.error { background: var(--danger-bg); color: var(--danger); }
.test-result pre {
  background: var(--surface2); padding: 12px; border-radius: var(--radius-sm);
  font-size: 12px; overflow-x: auto; max-height: 300px; overflow-y: auto;
}
.error-msg { color: var(--danger); font-size: 13px; margin-top: 8px; }
.duration { font-size: 12px; color: var(--text3); margin-top: 8px; }

.empty-state { text-align: center; padding: 80px 20px; color: var(--text3); }

/* Test panel */
.test-templates { display: flex; flex-wrap: wrap; gap: 6px; }
.test-template-btn {
  padding: 5px 10px; background: var(--surface2); border: 1px solid var(--border);
  border-radius: 16px; font-size: 12px; color: var(--text2); cursor: pointer;
  transition: all 0.15s; white-space: nowrap;
}
.test-template-btn:hover { border-color: var(--primary); color: var(--primary); background: #F5F3FF; }
.test-agent-hint {
  padding: 8px 12px; background: var(--surface2); border-radius: var(--radius-sm);
  font-size: 12px; color: var(--text3); margin-bottom: 12px; line-height: 1.6;
}
.test-input { font-size: 13px !important; line-height: 1.5; }
.test-json-error { color: var(--danger); font-size: 12px; margin-top: 6px; }
.btn-link {
  background: none; border: none; color: var(--accent); cursor: pointer;
  font-size: 12px; padding: 0; text-decoration: underline;
}
.btn-link:hover { color: var(--primary); }

/* Avatar */
.agent-avatar-img { width: 48px; height: 48px; border-radius: 50%; object-fit: cover; }
.avatar-upload-area { display: flex; align-items: center; gap: 16px; }
.avatar-preview {
  width: 80px; height: 80px; border-radius: 50%; overflow: hidden;
  border: 2px dashed var(--border); display: flex; align-items: center; justify-content: center;
  cursor: pointer; transition: border-color 0.2s; background: var(--surface2);
}
.avatar-preview:hover { border-color: var(--primary); }
.preset-avatars { margin-top: 12px; }
.preset-avatar-grid { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
.preset-avatar-item {
  width: 48px; height: 48px; border-radius: 50%; border: 2px solid var(--border);
  cursor: pointer; overflow: hidden; transition: all 0.15s; background: var(--surface2);
}
.preset-avatar-item:hover { border-color: var(--primary); transform: scale(1.1); }
.preset-avatar-item.active { border-color: var(--primary); box-shadow: 0 0 0 2px var(--primary); }
.preset-avatar-item img { width: 100%; height: 100%; object-fit: cover; }
.avatar-preview-img { width: 100%; height: 100%; object-fit: cover; }
.avatar-placeholder { font-size: 13px; color: var(--text3); text-align: center; }
.avatar-hint { font-size: 12px; color: var(--text3); }

/* Crop Modal */
.crop-modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center; z-index: 9999;
}
.crop-modal {
  background: var(--surface); border-radius: var(--radius); padding: 24px;
  width: 480px; box-shadow: 0 20px 60px rgba(0,0,0,0.3);
}
.crop-modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.crop-modal-header h3 { font-size: 16px; font-weight: 600; margin: 0; }
.crop-area { display: flex; justify-content: center; margin-bottom: 16px; }
.crop-area canvas { border-radius: var(--radius-sm); cursor: crosshair; max-width: 100%; }
.crop-actions { display: flex; justify-content: space-between; align-items: center; }
.crop-actions-right { display: flex; gap: 8px; }
.crop-zoom { display: flex; align-items: center; gap: 4px; }
.crop-zoom-btn {
  width: 32px; height: 32px; border-radius: 50%; border: 1px solid var(--border);
  background: var(--surface2); color: var(--text); font-size: 18px; font-weight: 600;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all 0.15s; line-height: 1;
}
.crop-zoom-btn:hover { border-color: var(--primary); color: var(--primary); }
.crop-zoom-label { font-size: 12px; color: var(--text3); min-width: 36px; text-align: center; }

/* Preset Chips */
.preset-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; align-items: center; }
.preset-label { font-size: 12px; color: var(--text3); margin-right: 4px; }
.preset-chip {
  padding: 4px 10px; background: var(--surface2); border: 1px solid var(--border);
  border-radius: 16px; font-size: 12px; color: var(--text2); cursor: pointer;
  transition: all 0.15s;
}
.preset-chip:hover { background: var(--primary); color: var(--primary-text); border-color: var(--primary); }

/* Role Presets */
.role-presets { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.role-preset-card {
  display: flex; align-items: flex-start; gap: 10px; padding: 12px;
  background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius-sm);
  cursor: pointer; transition: all 0.15s;
}
.role-preset-card:hover { border-color: var(--primary); background: #F5F3FF; }
.role-preset-icon { font-size: 24px; flex-shrink: 0; margin-top: 2px; }
.role-preset-name { font-size: 13px; font-weight: 600; color: var(--text); }
.role-preset-desc { font-size: 11px; color: var(--text3); margin-top: 2px; line-height: 1.4; }

.preset-card-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.preset-card-item {
  display: flex; align-items: flex-start; gap: 10px; padding: 12px;
  background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius-sm);
  cursor: pointer; transition: all 0.15s;
}
.preset-card-item:hover { border-color: var(--primary); background: #F5F3FF; }
.preset-card-icon { font-size: 24px; flex-shrink: 0; margin-top: 2px; }
.preset-card-name { font-size: 13px; font-weight: 600; color: var(--text); }
.preset-card-desc { font-size: 11px; color: var(--text3); margin-top: 2px; line-height: 1.4; }

/* Model selector */
.model-selector { display: flex; flex-direction: column; gap: 8px; }
.default-model-hint {
  padding: 8px 12px; background: #EEF2FF; color: #4F46E5;
  border-radius: var(--radius-sm); font-size: 13px;
}
.model-select {
  width: 100%; padding: 10px 14px; background: var(--surface2); border: 1px solid var(--border);
  border-radius: var(--radius-sm); color: var(--text); font-size: 14px;
}
.empty-icon { font-size: 48px; margin-bottom: 16px; }

/* Agent type toggle */
.agent-type-toggle { display: flex; gap: 8px; }
.type-btn {
  flex: 1; padding: 10px 16px; background: var(--surface2); border: 1px solid var(--border);
  border-radius: var(--radius-sm); font-size: 14px; font-weight: 500; color: var(--text2);
  cursor: pointer; transition: all 0.15s; text-align: center;
}
.type-btn:hover { border-color: var(--primary); }
.type-btn.active { background: var(--primary); color: var(--primary-text); border-color: var(--primary); }
.type-hint {
  margin-top: 8px; padding: 8px 12px; background: #FFF7ED; color: #C2410C;
  border-radius: var(--radius-sm); font-size: 12px; line-height: 1.5;
}
.agent-type-badge {
  padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;
}
.type-llm { background: #EEF2FF; color: #4F46E5; }
.type-proxy { background: #FFF7ED; color: #C2410C; }
.proxy-disabled-hint {
  padding: 12px 16px; background: var(--surface2); border-radius: var(--radius-sm);
  color: var(--text3); font-size: 13px; margin-bottom: 16px;
}
.proxy-disabled { opacity: 0.4; pointer-events: none; }
.field-mapping-hint {
  margin-top: 6px; font-size: 12px; color: var(--text3); line-height: 1.5;
}

.cm-editor-wrap {
  border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden;
}
.cm-editor-wrap .cm-editor { font-size: 13px; }
.cm-editor-wrap .cm-editor.cm-focused { outline: 2px solid var(--primary); }
.cm-test { border-color: var(--border); }
.cm-result { border-color: var(--border); background: var(--surface2); }
.cm-result .cm-editor { background: transparent; }

.toast {
  position: fixed; bottom: 24px; right: 24px; padding: 12px 20px;
  background: var(--text); color: var(--primary-text); border-radius: var(--radius-sm);
  font-size: 14px; z-index: 10000;
}
.toast-success { background: var(--success); }

.kb-section { margin-bottom: 20px; }
.kb-section h4 { margin: 0 0 12px; font-size: 15px; color: #374151; }
.kb-hint { font-weight: normal; font-size: 13px; color: #999; }
.kb-card { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; margin-bottom: 8px; }
.kb-card-readonly { border-left: 3px solid #3b82f6; }
.kb-card-header { display: flex; justify-content: space-between; align-items: center; }
.kb-card-info { flex: 1; }
.kb-card-name { font-weight: 500; font-size: 14px; }
.kb-card-meta { font-size: 12px; color: #888; margin-top: 2px; }
.kb-card-actions { display: flex; gap: 8px; align-items: center; }
.kb-docs { margin-top: 8px; padding-top: 8px; border-top: 1px solid #e5e7eb; }
.kb-doc-item { display: flex; align-items: center; justify-content: space-between; padding: 4px 0; font-size: 13px; }
.kb-doc-name { color: #374151; }
.kb-create-row { display: flex; gap: 8px; margin-bottom: 12px; }
.kb-create-row input { flex: 1; padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 13px; }
.toggle-label { display: flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; }
.toggle-label input[type="checkbox"] { width: 16px; height: 16px; cursor: pointer; }
.empty-hint { color: #999; font-size: 13px; padding: 4px 0; }
</style>

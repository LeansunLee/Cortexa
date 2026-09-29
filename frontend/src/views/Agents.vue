<template>
  <div class="agents-page">
    <!-- Agent List -->
    <div v-if="!editingAgent">
      <PageHeader><button class="btn btn-primary btn-page-action" v-if="can('agent.create')" @click="createNewAgent"><Plus :size="16" />新建智能体</button>
      </PageHeader>

      <div class="agents-grid" v-if="agents.length > 0">
        <div v-for="agent in agents" :key="agent.id" class="agent-card" :class="{ 'agent-card-menu-open': openAgentMenu === agent.id }" @click="editAgent(agent)">
          <div class="agent-header">
            <div class="agent-avatar">
              <AgentAvatar v-if="agent.avatar" :avatar="agent.avatar" class="agent-avatar-img" />
              <span v-else><Bot :size="16" /></span>
            </div>
            <div class="agent-info">
              <div class="agent-name">{{ agent.name }}</div>
              <div class="agent-role">{{ agent.role || '未设置角色' }}</div>
            </div>
            <span :class="['status-badge', 'status-' + agent.status]">{{ statusText(agent.status) }}</span>
          </div>
          <p class="agent-desc">{{ agent.description || '暂无描述' }}</p>
          <div class="agent-meta">
            <span class="agent-type-badge" :class="'type-' + (agent.agent_type || 'llm')">{{ (agent.agent_type || 'llm') === 'proxy' ? 'Proxy' : 'LLM' }}</span>
            <span v-if="agent.model && agent.agent_type !== 'proxy'">{{ agent.model }}</span>
            <span v-if="agent.agent_type === 'proxy' && agent.proxy_config?.endpoint">{{ agent.proxy_config.endpoint.substring(0, 30) }}...</span>
            <span>v{{ agent.current_version }}</span>
          </div>
          <div class="agent-actions">
            <button class="agent-btn-chat" @click.stop="chatWithAgent(agent)">
              <MessageSquare :size="15" /> 对话
            </button>
            <div class="agent-menu-wrap" @click.stop>
              <button class="agent-btn-more" @click="toggleAgentMenu(agent.id)">
                <MoreHorizontal :size="18" />
              </button>
              <div v-if="openAgentMenu === agent.id" class="agent-dropdown">
                <button class="agent-dropdown-item" @click="editAgent(agent); openAgentMenu = null">
                  <Edit :size="14" /> 编辑
                </button>
                <button class="agent-dropdown-item" v-if="can('agent.create')" @click="duplicateAgent(agent); openAgentMenu = null">
                  <Copy :size="14" /> 复制 Agent
                </button>
                <div class="agent-dropdown-divider"></div>
                <button v-if="can('agent.delete')" class="agent-dropdown-item danger" @click="deleteAgent(agent.id); openAgentMenu = null">
                  <Trash2 :size="14" /> 删除
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="empty-state">
        <div class="empty-icon"><Bot :size="16" /></div>
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
          <button class="btn btn-ghost" v-if="can('agent.update')" @click="saveAgent" :disabled="saving">
            {{ saving ? '保存中...' : '保存' }}
          </button>
          <button class="btn btn-primary" v-if="can('agent.publish')" @click="publishAgent" :disabled="publishing">
            {{ publishing ? '发布中...' : '发布' }}
          </button>
        </div>
      </div>

      <div class="editor-layout">
        <!-- 左侧导航 -->
        <div class="editor-nav">
          <div v-for="group in sectionGroups" :key="group.label" class="nav-group">
            <div class="nav-group-label">{{ group.label }}</div>
            <div v-for="section in group.items" :key="section.id"
                 :class="['nav-item', { active: currentSection === section.id }]"
                 @click="currentSection = section.id">
              <span class="nav-indicator"></span>
              <component :is="iconComponents[section.icon]" :size="16" />
              {{ section.name }}
            </div>
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
                  <AgentAvatar v-if="editingAgent.avatar" :avatar="editingAgent.avatar" class="avatar-preview-img" />
                  <span v-else class="avatar-placeholder">点击上传</span>
                </div>
                <input ref="avatarInput" type="file" accept="image/jpeg,image/png,image/gif,image/webp" style="display:none" @change="handleAvatarUpload" />
                <div class="avatar-hint">支持 JPG/PNG/GIF/WebP，最大 5MB</div>
              </div>
              <div class="preset-avatars">
                <span class="preset-label">预设头像：</span>
                <div class="preset-avatar-grid">
                  <button type="button" v-for="a in presetAvatars" :key="a.path" :class="['preset-avatar-item', { active: editingAgent.avatar === a.path }]"
                    @click="editingAgent.avatar = a.path" :title="a.label" :aria-pressed="editingAgent.avatar === a.path">
                    <AgentAvatar :avatar="a.path" />
                    <span>{{ a.label }}</span>
                  </button>
                </div>
              </div>
            </div>

            <!-- Avatar Crop Modal -->
            <div v-if="showCropModal" class="crop-modal-overlay" @click.self="cancelCrop">
              <div class="crop-modal">
                <div class="crop-modal-header">
                  <h3>裁剪头像</h3>
                  <button class="btn btn-ghost btn-sm" @click="cancelCrop"><AppIcon name="X" /></button>
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
              <label>Agent 名称 * <LlmContextHint :text="editingAgent.agent_type === 'proxy' ? '作为协作候选的名称提供给主 Agent 模型；Proxy 自身由外部系统执行。' : '写入本 Agent 的系统提示词，定义模型当前身份；参与协作时也作为候选名称提供给主 Agent。'" collaboration-text="作为候选身份提供给发起协作的 Agent，帮助其识别并选择协作者。" /></label>
              <input v-model="editingAgent.name" placeholder="例如：Peter、产品经理" />
            </div>
            <div class="form-group">
              <label>智能体类型</label>
              <div class="agent-type-toggle">
                <button :class="['type-btn', { active: (editingAgent.agent_type || 'llm') === 'llm' }]"
                  @click="editingAgent.agent_type = 'llm'">
                  LLM 智能体
                </button>
                <button :class="['type-btn', { active: editingAgent.agent_type === 'proxy' }]"
                  @click="editingAgent.agent_type = 'proxy'">
                  <Link :size="16" /> Proxy 代理
                </button>
              </div>
              <div class="type-hint" v-if="editingAgent.agent_type === 'proxy'">
                Proxy 将请求转发至外部 Agent API，推理、知识和工具由外部系统提供。协作上下文可先由平台整理，再将最终请求发送给外部 Agent。
              </div>
            </div>
            <div v-if="editingAgent.agent_type !== 'proxy'" class="type-hint">
              LLM 智能体由本平台调用模型，使用工作空间规则及人格、角色、职责等提示词，并可使用本地知识库和数据能力。
            </div>
            <div class="form-group">
              <label>能力简介（供协同发现） <LlmContextHint text="用于匹配协作候选；成为候选后，作为能力说明提供给发起协作的主 Agent 模型。不会加入本 Agent 自己的系统提示词。" collaboration-text="其他 Agent 根据这段简介发现并判断是否邀请本 Agent。" /></label>
              <textarea v-model="editingAgent.description" rows="3" placeholder="例如：擅长研究市场与竞品，可协助制定销售计划"></textarea>
            </div>
          </div>

          <!-- 人格 -->
          <div v-if="currentSection === 'personality' && editingAgent.agent_type !== 'proxy'" class="section">
            <h3>人格特征</h3>
            <div class="form-group">
              <label>Personality <LlmContextHint text="作为「人格特征」写入本 Agent 的系统提示词，影响回答的语气与行为风格。" /></label>
              <textarea v-model="editingAgent.personality" rows="5" 
                placeholder="描述智能体的性格特征，例如：&#10;- 严谨认真&#10;- 理性分析&#10;- 主动沟通&#10;- 专业高效"></textarea>
              <div class="preset-chips">
                <span class="preset-label">快速添加：</span>
                <button v-for="p in personalityPresets" :key="p" class="preset-chip" @click="appendPersonality(p)">+ {{ p }}</button>
              </div>
            </div>
          </div>

          <!-- 职责 -->
          <div v-if="currentSection === 'role' && editingAgent.agent_type !== 'proxy'" class="section">
            <h3>角色与职责</h3>
            <p class="section-desc">这里定义 Agent 自己如何执行任务；基础信息中的能力简介用于协同发现。</p>
            <div class="form-group">
              <label>业务角色（可选） <LlmContextHint text="作为「角色」写入本 Agent 的系统提示词，帮助模型理解当前扮演的业务身份。" collaboration-text="在 @ 协作候选列表中展示，也可按此角色名称搜索 Agent。" /></label>
              <input v-model="editingAgent.role" placeholder="例如：名称为 Peter 时填写「产品经理」" />
              <small class="field-usage-note">仅在名称未说明业务身份时填写；与 Agent 名称相同可留空。</small>
            </div>
            <div class="form-group">
              <label>执行职责 <LlmContextHint text="作为「职责」写入本 Agent 的系统提示词，指导模型处理任务；此字段不参与协作候选的词法匹配。" /></label>
              <textarea v-model="editingAgent.responsibilities" rows="5" 
                placeholder="写具体任务和执行要求，例如：分析销售数据、识别风险、输出行动建议"></textarea>
            </div>
            <div class="form-group">
              <label>角色与职责模板（点击填入）</label>
              <div class="role-presets">
                <div v-for="rp in rolePresets" :key="rp.role" class="role-preset-card" @click="applyRolePreset(rp)">
                  <div class="role-preset-icon"><component :is="iconComponents[rp.icon]" :size="18" /></div>
                  <div class="role-preset-info">
                    <div class="role-preset-name">{{ rp.role }}</div>
                    <div class="role-preset-desc">{{ rp.desc }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 工作边界 -->
          <div v-if="currentSection === 'boundary' && editingAgent.agent_type !== 'proxy'" class="section">
            <h3>工作边界</h3>
            <div class="form-group">
              <label>边界定义 <LlmContextHint text="作为「工作边界」写入本 Agent 的系统提示词，告诉模型可以做什么及哪些操作需谨慎。" /></label>
              <textarea v-model="editingAgent.boundaries" rows="5" 
                placeholder="明确智能体可以做什么，不可以做什么"></textarea>
            </div>
            <div class="form-group">
              <label>预设边界（点击自动填入）</label>
              <div class="preset-card-grid">
                <div v-for="bp in boundaryPresets" :key="bp.name" class="preset-card-item" @click="applyBoundaryPreset(bp)">
                  <div class="preset-card-icon"><component :is="iconComponents[bp.icon]" :size="18" /></div>
                  <div class="preset-card-info">
                    <div class="preset-card-name">{{ bp.name }}</div>
                    <div class="preset-card-desc">{{ bp.desc }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Proxy 配置 -->
          <div v-if="currentSection === 'proxy' && editingAgent.agent_type === 'proxy'" class="section">
            <h3><Link :size="18" /> Proxy 代理配置</h3>
            <p class="section-hint">连接外部 Agent。协作时可先由平台把任务和上下文整理成一段完整请求。</p>
            <div>
              <div class="form-group">
                <label>外部系统 Endpoint *</label>
                <input v-model="proxyCfg.endpoint" placeholder="https://api.example.com/v1/run" class="mono" />
              </div>

              <section class="prompt-resolution-card goal-proxy-contract">
                <h4>目标模式输入契约</h4>
                <label><input type="checkbox" :checked="proxyGoalContract.enabled" @change="setGoalContractEnabled($event.target.checked)" /> 允许作为目标协作参与者</label>
                <p class="section-hint">只发送契约允许的字段。完整对话、记忆和主 Agent 提示词不会进入请求；下方的自动整理、补充提示词和重试设置仅用于普通对话。</p>
                <template v-if="proxyGoalContract.enabled">
                  <div class="form-group"><label>输入预算（保守估算，256–8000）</label><input type="number" v-model.number="proxyGoalContract.input_budget" min="256" max="8000" /></div>
                  <p v-if="!schemaFields.length">请先在「输入输出 Schema」声明 object 输入字段和类型。</p>
                  <div v-for="field in schemaFields" :key="field.name" class="form-group">
                    <label>{{ field.name }} · 允许来源</label>
                    <label v-for="source in goalInputSources" :key="source.value"><input type="checkbox" :checked="(proxyGoalContract.fields[field.name] || []).includes(source.value)" @change="toggleGoalSource(field.name, source.value, $event.target.checked)" /> {{ source.label }}</label>
                  </div>
                  <p class="section-hint">任务原文优先使用本代理的分工，未填写时使用当前目标；Observation 只取指定事实字段或已有摘要。</p>
                  <label><input type="checkbox" v-model="editingAgent.collaboration.allow_incoming" /> 允许接收协作邀请</label>
                  <label><input type="checkbox" v-model="editingAgent.collaboration.discoverable" /> 允许被自主发现</label>
                </template>
              </section>
              <div class="prompt-resolution-card">
                <div class="resolution-config-head">
                  <div>
                    <h4>自动整理协作上下文</h4>
                    <p>适合只接收一段文字的 Proxy。平台先整理，外部 Agent 不会收到完整对话。</p>
                  </div>
                  <label class="capability-switch">
                    <input type="checkbox" :checked="proxyPromptResolution.enabled" @change="setPromptResolutionEnabled($event.target.checked)" />
                    <span class="capability-switch-track" aria-hidden="true"></span><span>{{ proxyPromptResolution.enabled ? '已开启' : '未开启' }}</span>
                  </label>
                </div>
                <div v-if="proxyPromptResolution.enabled" class="prompt-resolution-body">
                  <div class="form-group">
                    <label>整理要求 <LlmContextHint text="开启自动整理后，作为平台整理模型的系统指令，指导它把允许的协作上下文整理成发送给外部 Proxy 的请求。" collaboration-text="影响协作任务如何整理成请求并发送给外部 Proxy。" /></label>
                    <textarea v-model="proxyCfg.supplemental_prompt" rows="5" placeholder="例如：整理成可直接执行的 DMS 查询请求；保留明确的人名、事项和时间，不要编造信息。"></textarea>
                    <div class="field-mapping-hint">这段文字用于指导平台整理请求，不会连同完整上下文直接发送给外部 Agent。</div>
                  </div>
                  <div class="form-group compact-group">
                    <label>整理时可以参考 <LlmContextHint text="勾选的来源内容会按需提供给平台整理模型，帮助它生成发送给外部 Proxy 的请求；当前任务始终提供。" collaboration-text="决定协作请求整理时哪些对话、记忆或前序结果可以提供给外部 Proxy。" /></label>
                    <div class="simple-source-options">
                      <label v-for="source in promptSourceOptions" :key="source.value">
                        <input type="checkbox" :checked="proxyPromptResolution.allowed_sources.includes(source.value)" @change="togglePromptSource(source.value, $event.target.checked)" />
                        <span>{{ source.label }}</span>
                      </label>
                    </div>
                    <div class="field-mapping-hint">当前任务始终会使用，并且优先级最高。</div>
                  </div>
                </div>
              </div>

              <details class="proxy-advanced">
                <summary>高级连接设置</summary>
                <div class="proxy-advanced-body">
                  <div class="form-row">
                    <div class="form-group">
                      <label>请求方法</label>
                      <SearchSelect v-model="proxyCfg.method" :options="proxyMethodOptions" placeholder="选择请求方法" aria-label="请求方法" />
                    </div>
                    <div class="form-group">
                      <label>超时 (ms，最大 10 分钟)</label>
                      <input type="number" v-model.number="proxyCfg.timeout_ms" min="1000" max="600000" step="1000" />
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
                  <div v-if="!proxyPromptResolution.enabled" class="form-group">
                    <label>直接发送的补充提示词（兼容模式）</label>
                    <textarea v-model="proxyCfg.supplemental_prompt" rows="4" placeholder="留空则直接发送本轮输入"></textarea>
                    <div class="field-mapping-hint">未开启上下文整理时，此内容会直接拼接在本轮输入前。</div>
                  </div>
                  <div class="form-group">
                    <label>请求字段映射 (JSON)</label>
                    <div class="cm-editor-wrap">
                      <Codemirror v-model="proxyReqMappingStr" :extensions="cmExtensions" :style="{ height: '100px' }" />
                    </div>
                    <div class="field-mapping-hint">例如 { "query": "$.input" }：把整理后的请求发送到外部系统的 query 字段。</div>
                  </div>
                  <div class="form-group">
                    <label>响应字段映射 (JSON)</label>
                    <div class="cm-editor-wrap">
                      <Codemirror v-model="proxyRespMappingStr" :extensions="cmExtensions" :style="{ height: '100px' }" />
                    </div>
                    <div class="field-mapping-hint">例如 { "answer": "$.data.answer" }：提取外部回答供对话及协作使用。</div>
                  </div>
                </div>
              </details>
            </div>
          </div>

          <!-- Schema -->
          <div v-if="currentSection === 'schema'" class="section">
            <h3>输入输出 Schema</h3>
            <div class="form-group">
              <label>Input Schema (JSON) <LlmContextHint :text="editingAgent.agent_type === 'proxy' ? '目标协作时输入契约会作为能力说明提供给主 Agent 模型；启用结构化参数解析后，未解析字段的 Schema 会提供给平台解析模型。' : '本 Agent 作为协作候选时，输入契约会作为工具说明提供给主 Agent 模型，帮助它构造委托参数。'" collaboration-text="作为协作输入契约提供给发起协作的 Agent，指导它构造交给本 Agent 的任务参数。" /> <button class="btn-link" @click="formatInputSchema"><Edit :size="14" /> 格式化</button></label>
              <div class="cm-editor-wrap">
                <Codemirror v-model="inputSchemaStr" :extensions="cmExtensions" :style="{ height: '220px' }" />
              </div>
            </div>
            <div v-if="editingAgent.agent_type === 'proxy'" class="resolution-config">
              <div class="resolution-config-head">
                <div><h4>高级：结构化参数解析</h4><p>仅用于外部接口必须接收多个严格字段的场景；普通文本 Proxy 建议使用“自动整理协作上下文”。</p></div>
                <label class="capability-switch">
                  <input type="checkbox" :checked="proxyResolution.enabled" @change="setResolutionEnabled($event.target.checked)" />
                  <span class="capability-switch-track" aria-hidden="true"></span><span>{{ proxyResolution.enabled ? '已启用' : '未启用' }}</span>
                </label>
              </div>
              <div v-if="proxyResolution.enabled">
                <div class="form-group resolution-threshold"><label>最低可信度</label><input type="number" min="0" max="1" step="0.05" :value="proxyResolution.confidence_threshold" @input="updateResolutionThreshold($event.target.value)" /></div>
                <div v-if="schemaFields.length" class="resolution-fields">
                  <div v-for="field in schemaFields" :key="field.name" class="resolution-field">
                    <div class="resolution-field-title"><code>{{ field.name }}</code><span v-if="field.required" class="required-badge">必填</span></div>
                    <label>业务含义 <LlmContextHint text="写入 Input Schema 的字段描述；该字段需要模型解析时，会随契约提供给平台解析模型。" collaboration-text="作为协作输入参数说明提供给发起协作的 Agent，帮助它填写此字段。" /><input type="text" :value="field.description" @input="updateFieldDescription(field.name, $event.target.value)" placeholder="说明该字段在业务中的含义" /></label>
                    <label class="resolution-required"><input type="checkbox" :checked="field.required" @change="toggleSchemaRequired(field.name, $event.target.checked)" /> 必填字段 <LlmContextHint text="该字段需要模型解析时，是否必填会作为契约信息提供给平台解析模型。" collaboration-text="该参数的必填状态会展示给发起协作的 Agent，用于构造完整的协作请求。" /></label>
                    <label>解析模式 <LlmContextHint text="该字段需要模型解析时，解析模型会按这里选择的严格提取或语义推断方式处理。" collaboration-text="本 Agent 通过协作收到任务时，平台会按此模式解析该字段的参数值。" />
                      <SearchSelect
                        :model-value="fieldResolution(field.name).resolutionMode"
                        :options="resolutionModeOptions"
                        placeholder="选择解析模式"
                        aria-label="解析模式"
                        @change="value => updateFieldResolution(field.name, 'resolutionMode', value)"
                      />
                    </label>
                    <div class="resolution-source-label">允许来源 <LlmContextHint text="该字段需要模型解析时，允许来源列表和对应上下文会提供给平台解析模型；未勾选的来源不会提供。" collaboration-text="本 Agent 通过协作收到任务时，限制平台解析模型可从哪些上下文来源提取该参数。" /></div>
                    <div class="resolution-sources">
                      <label v-for="source in resolutionSources" :key="source.value"><input type="checkbox" :checked="fieldResolution(field.name).allowedSources.includes(source.value)" @change="toggleFieldSource(field.name, source.value, $event.target.checked)" />{{ source.label }}</label>
                    </div>
                    <label>解析说明 <LlmContextHint text="该字段需要模型解析时，作为字段契约的一部分提供给平台解析模型，指导它如何提取或推断值。" collaboration-text="本 Agent 通过协作收到任务时，指导平台如何从允许的协作上下文中提取或推断此参数。" /><textarea rows="2" :value="fieldResolution(field.name).resolutionHint" @input="updateFieldResolution(field.name, 'resolutionHint', $event.target.value)" placeholder="例如：将“本月”转换为 YYYY-MM"></textarea></label>
                  </div>
                </div>
                <div v-else class="empty-hint">请先在 Input Schema 的 properties 中定义字段。</div>
              </div>
            </div>
            <div class="form-group">
              <label>Output Schema (JSON) <button class="btn-link" @click="formatOutputSchema"><Edit :size="14" /> 格式化</button></label>
              <div class="cm-editor-wrap">
                <Codemirror v-model="outputSchemaStr" :extensions="cmExtensions" :style="{ height: '220px' }" />
              </div>
              <small class="field-usage-note">当前用于结果格式校验，不会作为系统提示词注入对话模型。</small>
            </div>
          </div>

          <!-- 模型 -->
          <div v-if="currentSection === 'model' && editingAgent.agent_type !== 'proxy'" class="section">
            <h3>模型配置</h3>
            <div class="form-group">
              <label>目标协作权限</label>
              <SearchSelect v-model="editingAgent.collaboration.autonomy" class="collaboration-autonomy-select" :options="autonomyOptions" aria-label="目标协作权限" :disabled="!can('agent.update')" />
              <small>作为此 Agent 的协作上限；对话默认不主动，用户可在工作空间与此 Agent 允许的范围内选择。</small>
            </div>
            <div class="form-group">
              <label><input type="checkbox" v-model="editingAgent.collaboration.allow_incoming" :disabled="!can('agent.update')" /> 允许其他 Agent 邀请协作</label>
              <label><input type="checkbox" v-model="editingAgent.collaboration.discoverable" :disabled="!can('agent.update')" /> 允许根据描述与能力被发现</label>
            </div>
            <section class="agent-budget-card" aria-labelledby="agent-budget-title">
              <div class="agent-budget-head">
                <div>
                  <h4 id="agent-budget-title"><Gauge :size="17" /> Runtime Budget <small>运行预算</small></h4>
                  <p>默认继承 Workspace；只勾选需要为当前 Agent 单独收紧的额度。</p>
                </div>
                <button type="button" class="btn btn-ghost" :disabled="runtimeBudgetLoading" @click="loadAgentBudget(editingAgent.id)">刷新额度</button>
              </div>
              <p v-if="runtimeBudgetError" class="agent-budget-error">{{ runtimeBudgetError }}</p>
              <template v-else-if="runtimeBudgetLoaded">
                <div class="agent-budget-grid">
                  <div v-for="field in runtimeBudgetFields" :key="field.key" class="agent-budget-field">
                    <label class="agent-budget-override">
                      <input v-model="runtimeBudgetSelected[field.key]" type="checkbox" :disabled="!can('agent.update')" />
                      <span>{{ field.label }} <small>{{ field.zh }}</small></span>
                    </label>
                    <input v-model.number="runtimeBudgetDraft[field.key]" type="number" step="1" :min="field.min" :max="runtimeWorkspaceBudget[field.key] === UNLIMITED_BUDGET ? undefined : runtimeWorkspaceBudget[field.key]" :disabled="!runtimeBudgetSelected[field.key] || !can('agent.update')" :aria-label="field.label" />
                    <small>Workspace Limit · 工作空间上限 {{ runtimeWorkspaceBudget[field.key] === UNLIMITED_BUDGET ? '不限' : runtimeWorkspaceBudget[field.key] }}</small>
                  </div>
                </div>
                <div class="agent-budget-actions">
                  <router-link v-if="can('workspace.manage')" to="/workspaces">调整 Workspace 上限</router-link>
                  <button v-if="can('agent.update')" type="button" class="btn btn-primary" :disabled="runtimeBudgetSaving" @click="saveAgentBudget">
                    {{ runtimeBudgetSaving ? '保存中…' : 'Save Runtime Budget · 保存预算' }}
                  </button>
                </div>
              </template>
            </section>
            <div class="form-group">
              <label>选择模型</label>
              <div class="model-selector">
                <div v-if="workspaceDefaultModel" class="default-model-hint">
                  工作空间默认模型：{{ workspaceDefaultModel }}
                </div>
                <SearchSelect v-model="editingAgent.model" class="model-select" :options="modelOptions" placeholder="使用工作空间默认模型" aria-label="选择模型" />
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label>Temperature</label>
                <input v-model.number="editingAgent.temperature" type="number" step="0.1" min="0" max="2" />
              </div>
              <div class="form-group">
                <label>最大输出词元</label>
                <input v-model.number="editingAgent.max_tokens" type="number" min="256" max="128000" />
              </div>
            </div>
            <div class="form-group">
              <label>System Prompt（可选，会自动从配置生成） <LlmContextHint text="作为「补充说明」附加到本 Agent 的系统提示词中；工作空间规则、人格、角色、职责与边界会分别自动组装。" /></label>
              <textarea v-model="editingAgent.system_prompt" rows="5"></textarea>
            </div>
          </div>

          <AgentResources v-if="editingAgent.agent_type !== 'proxy'" v-show="['knowledge', 'tools', 'data', 'memory'].includes(currentSection)" :key="editingAgent.id" :agent-id="editingAgent.id" :agent="editingAgent" mode="management" :section="currentSection" @bindings-change="updateResourceBindings">
            <template #tools-prefix>
            <section class="agent-search-panel" aria-labelledby="web-search-heading">
              <div class="capability-heading">
                <span class="capability-icon"><AppIcon name="Globe" :size="20" /></span>
                <div class="capability-heading-copy">
                  <h3 id="web-search-heading">联网搜索</h3>
                  <p>按需搜索公开网页，获取标题、摘要和来源链接</p>
                </div>
                <label class="capability-switch">
                  <span>{{ editingAgent.web_search_enabled ? '已开启' : '未开启' }}</span>
                  <input type="checkbox" role="switch" aria-label="允许智能体搜索公开网页" v-model="editingAgent.web_search_enabled" :disabled="!can('agent.update')" />
                  <span class="capability-switch-track" aria-hidden="true"></span>
                </label>
              </div>
              <div :class="['search-service-notice', { ready: webSearchStatus.configured }]" role="status">
                <AppIcon :name="webSearchStatus.configured ? 'CheckCircle' : 'Info'" :size="16" />
                <span>{{ webSearchStatus.configured ? `搜索服务已配置 · ${webSearchStatus.provider_name}` : (webSearchStatus.message || '搜索服务尚未配置') }}</span>
              </div>
              <div class="capability-footnote">
                <span>每轮最多搜索 3 次</span>
                <span>关键词会发送至搜索服务，请仅查询公开信息</span>
              </div>
            </section>

            </template>
          </AgentResources>

          <div v-if="currentSection === 'versions'" class="section">
            <h3>版本历史</h3>
            <button class="btn btn-primary btn-sm" v-if="can('agent.update')" @click="createVersion" style="margin-bottom: 16px">
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

        <!-- Proxy 输入整理预览 -->
        <div v-if="editingAgent.agent_type === 'proxy' && (proxyPromptResolution.enabled || proxyResolution.enabled)" class="editor-test">
          <div v-if="editingAgent.agent_type === 'proxy' && (proxyPromptResolution.enabled || proxyResolution.enabled)" class="resolver-test">
            <h3><AppIcon name="Compass" /> {{ proxyPromptResolution.enabled ? '上下文整理测试' : '结构化解析测试' }}</h3>
            <div class="form-group"><label>示例任务 <LlmContextHint text="仅点击「预览发送内容」时，作为当前任务提供给平台整理或解析模型；不会保存为 Agent 配置。" collaboration-text="仅用于预览协作请求最终发送给 Proxy 的内容，不会保存为 Agent 配置。" /></label><textarea v-model="resolutionTestTask" rows="3" placeholder="例如：查询刚才提到的区域本月销量"></textarea></div>
            <div class="form-group"><label>示例对话 <LlmContextHint text="仅预览时、且允许参考对话来源时，作为测试上下文提供给平台整理或解析模型；不会保存为 Agent 配置。" collaboration-text="仅用于预览协作请求如何使用允许的对话上下文，不会保存为 Agent 配置。" /></label><textarea v-model="resolutionTestContext" rows="5" placeholder="例如：用户：最近重点关注杭州区域。&#10;助手：好的，后续查询以杭州为主。"></textarea></div>
            <details class="resolver-advanced">
              <summary>高级测试数据</summary>
              <label>前序 Agent 输出（JSON） <LlmContextHint text="仅预览时、且允许参考前序 Agent 输出时，作为测试来源提供给平台整理或解析模型。" collaboration-text="仅用于预览协作请求如何引用上游 Agent 的结果，不会保存为 Agent 配置。" /><textarea v-model="resolutionTestPrevious" class="mono" rows="4"></textarea></label>
              <label>系统值（JSON） <LlmContextHint text="仅预览结构化参数解析且允许参考系统值时，作为测试来源提供给平台解析模型。" collaboration-text="仅用于预览协作参数解析如何使用系统值，不会保存为 Agent 配置。" /><textarea v-model="resolutionTestSystem" class="mono" rows="4"></textarea></label>
            </details>
            <div v-if="resolutionTestError" class="test-json-error"><AlertTriangle :size="14" /> {{ resolutionTestError }}</div>
            <button class="btn btn-ghost resolver-test-button" v-if="can('agent.update')" @click="runResolutionTest" :disabled="resolvingInput || !resolutionTestTask.trim()">{{ resolvingInput ? '整理中...' : '预览发送内容' }}</button>
            <div v-if="resolutionTestResult" class="test-result">
              <div :class="['result-status', resolutionTestResult.canInvoke ? 'success' : 'error']">{{ resolutionTestResult.canInvoke ? '可以发送给 Proxy Agent' : resolutionTestResult.message }}</div>
              <div v-if="proxyPromptResolution.enabled && resolutionTestResult.input?.input" class="resolved-prompt-preview">
                <label>最终发送内容</label>
                <div>{{ resolutionTestResult.input.input }}</div>
              </div>
              <details class="resolver-advanced result-details">
                <summary>查看完整解析结果</summary>
                <div class="cm-editor-wrap cm-result"><Codemirror :model-value="JSON.stringify(resolutionTestResult, null, 2)" :extensions="cmReadOnlyExtensions" :style="{ height: '260px' }" /></div>
              </details>
            </div>
          </div>
        </div>
      </div>
    </div>


  </div>
</template>

<script setup>
import { avatarUrl } from '../utils/avatar'
import AgentAvatar from '../components/AgentAvatar.vue'
import { can } from '../auth'
import AgentResources from '../components/AgentResources.vue'
import LlmContextHint from '../components/LlmContextHint.vue'
import {
  Bot, Link, Settings, Database, BookOpen, FileText, Folder, Upload, Trash2,
  Download, Copy, Search, Filter, RefreshCw, Save, Edit, Check, X, AlertTriangle,
  BarChart, Code, Shield, Lock, Target, Layers, Package, Tag, Zap, Compass,
  MessageSquare, Wrench, PieChart, Activity, Send, Bell, Mail, Star, Heart,
  User, Smile, Briefcase, Globe, BarChart3, Lightbulb, Brain, PenTool, Sparkles, MoreHorizontal,
  Scale, Rocket, HelpCircle, Palette, Mic, Users, Headphones, PenLine,
  Calendar, DollarSign, Award, Megaphone, TrendingUp, CircleDot, Archive, Eye, Plus, Gauge
} from 'lucide-vue-next'

const iconComponents = {
  User, Smile, Briefcase, Shield, Settings, Link, FileText, Bot, BookOpen, BarChart, Package,
  Globe, Search, BarChart3, Lightbulb, Brain, PenTool, Sparkles, MessageSquare,
  Scale, Rocket, Target, RefreshCw, HelpCircle, Zap, Wrench, Database,
  Palette, Mic, Users, Headphones, PenLine, Calendar, DollarSign, Award, Megaphone, TrendingUp,
  Palette, Mic, Users, Headphones, PenLine,
  Calendar, DollarSign, Award, CircleDot, Archive
}

import { ref, computed, onMounted, watch, nextTick, shallowRef } from 'vue'
import { Codemirror } from 'vue-codemirror'
import { json } from '@codemirror/lang-json'
import { oneDark } from '@codemirror/theme-one-dark'
import { agentApi, configApi } from '../api'
import axios from 'axios'

const agents = ref([])
const editingAgent = ref(null)
const runtimeBudgetLoaded = ref(false)
const runtimeBudgetLoading = ref(false)
const runtimeBudgetSaving = ref(false)
const runtimeBudgetError = ref('')
const runtimeWorkspaceBudget = ref({})
const runtimeBudgetDraft = ref({})
const runtimeBudgetSelected = ref({})
const UNLIMITED_BUDGET = 1000000000000000
const runtimeBudgetFields = [
  { key: 'duration', label: 'Max Duration', zh: '最长执行时间（秒）', min: 1 },
  { key: 'llm_calls', label: 'Max LLM Calls', zh: '模型调用次数', min: 0 },
  { key: 'tool_calls', label: 'Max Tool Calls', zh: '工具调用次数', min: 0 },
  { key: 'tool_iterations', label: 'Max Tool Iterations', zh: '工具执行轮次', min: 0 },
  { key: 'web_calls', label: 'Max Web Calls', zh: '网页调用次数', min: 0 },
  { key: 'agent_calls', label: 'Max Agent Calls', zh: '协作调用次数', min: 0 },
  { key: 'agent_depth', label: 'Max Agent Depth', zh: '协作层级', min: 0 },
  { key: 'context_tokens', label: 'Max Context Tokens', zh: '上下文词元', min: 256 },
  { key: 'output_tokens', label: 'Max Output Tokens', zh: '累计输出词元', min: 0 },
  { key: 'max_steps', label: 'Max Steps', zh: '目标步骤', min: 1 },
  { key: 'max_replans', label: 'Max Replans', zh: '重新规划次数', min: 0 },
  { key: 'max_failures', label: 'Max Failures', zh: '失败次数', min: 1 },
  { key: 'max_collaborators', label: 'Max Collaborators', zh: '协作 Agent 数量', min: 0 },
]
const autonomyOptions = [
  { value: 'INHERIT_WORKSPACE', label: '♧ Inherit Workspace · 继承工作空间' },
  { value: 'EXPLICIT_ONLY', label: '不主动 · 仅用户主动 @ 的 Agent 可以协作' },
  { value: 'ASK_BEFORE_COLLABORATION', label: '询问 · 需要其他 Agent 协作时询问用户' },
  { value: 'AUTONOMOUS', label: '主动 · 由 Agent 自行决策' },
]
const versions = ref([])
const providers = ref({})
const currentSection = ref('basic')
const proxyMethodOptions = [
  { value: 'POST', label: 'POST' },
  { value: 'GET', label: 'GET' },
  { value: 'PUT', label: 'PUT' },
]
const resolutionModeOptions = [
  { value: 'strict', label: 'strict · 仅显式参数' },
  { value: 'context', label: 'context · 提取明确上下文' },
  { value: 'infer', label: 'infer · 允许语义推断' },
]

const saving = ref(false)
const publishing = ref(false)
const resolvingInput = ref(false)
const resolutionTestTask = ref('')
const resolutionTestContext = ref('')
const resolutionTestPrevious = ref('[]')
const resolutionTestSystem = ref('{}')
const resolutionTestResult = ref(null)
const resolutionTestError = ref('')
const knowledgeBases = ref([])
const webSearchStatus = ref({ configured: false, message: '正在检查搜索服务配置…' })
const availableModels = ref([])
const workspaceDefaultModel = ref('')
const modelOptions = computed(() => [
  { value: '', label: '使用工作空间默认模型' },
  ...availableModels.value.map(provider => ({
    value: provider.name,
    label: provider.name + ' — ' + provider.model + ' (' + provider.kind + ')',
  })),
])
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
  { path: '/static/avatars/channel.svg', label: '渠道' },
  { path: '/static/avatars/brand.svg', label: '品牌' },
  { path: '/static/avatars/aftersales.svg', label: '售后' },
  { path: '/static/avatars/newretail.svg', label: '新零售' },
  { path: '/static/avatars/bald.svg', label: '光头' },
  { path: '/static/avatars/ops.svg', label: '运维' },
  { path: '/static/avatars/legal.svg', label: '法务' },
  { path: '/static/avatars/research.svg', label: '研究' },
  { path: '/static/avatars/pm.svg', label: '项目' },
]

const personalityPresets = [
  '严谨认真', '理性分析', '主动沟通', '专业高效', '耐心细致',
  '创新思维', '批判性思维', '同理心强', '结果导向', '善于总结',
  '幽默风趣', '客观中立', '风险意识', '学习能力强', '执行力强'
]

const rolePresets = [
  { role: '产品经理', icon: 'FileText', desc: '负责需求分析、产品规划、PRD撰写、优先级排序', responsibilities: '1. 需求收集与分析，输出PRD文档\n2. 产品路线图规划与版本管理\n3. 竞品分析与市场调研\n4. 跨团队沟通协调（设计、开发、测试）\n5. 用户反馈收集与数据分析\n6. 产品上线效果跟踪与迭代' },
  { role: '前端工程师', icon: 'Palette', desc: '负责Web/移动端界面开发、组件封装、性能优化', responsibilities: '1. 根据设计稿完成页面开发与联调\n2. 前端组件库建设与维护\n3. 前端性能优化（首屏加载、渲染性能）\n4. 兼容性处理与响应式适配\n5. 前端工程化建设（构建、部署、监控）\n6. 技术方案设计与代码评审' },
  { role: '后端工程师', icon: 'Settings', desc: '负责服务端架构、API设计、数据库优化', responsibilities: '1. 服务端架构设计与API接口开发\n2. 数据库设计与SQL优化\n3. 系统性能优化与高并发处理\n4. 代码质量保障（单测、集成测试）\n5. 线上问题排查与日志分析\n6. 技术文档编写与知识沉淀' },
  { role: '测试工程师', icon: 'Search', desc: '负责测试计划、用例设计、自动化测试', responsibilities: '1. 测试计划制定与测试用例设计\n2. 功能测试、回归测试、兼容性测试\n3. 自动化测试框架搭建与脚本编写\n4. 性能测试、安全测试\n5. Bug跟踪与质量报告输出\n6. 测试流程优化与工具建设' },
  { role: '数据分析师', icon: 'BarChart3', desc: '负责数据采集、分析建模、业务洞察', responsibilities: '1. 数据需求梳理与指标体系建设\n2. 数据清洗、ETL与报表开发\n3. 业务数据分析与专题分析\n4. A/B测试设计与效果评估\n5. 数据可视化看板搭建\n6. 业务洞察与策略建议输出' },
  { role: 'UI设计师', icon: 'Palette', desc: '负责界面视觉设计、交互原型、设计规范', responsibilities: '1. 产品界面视觉设计（Web/App）\n2. 交互原型设计与用户体验优化\n3. 设计规范与组件库维护\n4. 运营活动页面与banner设计\n5. 设计走查与开发还原度验收\n6. 设计趋势研究与创新能力提升' },
  { role: '内容运营', icon: 'PenLine', desc: '负责内容策划、文案撰写、用户增长', responsibilities: '1. 内容策划与选题规划\n2. 文案撰写（产品文案、营销文案）\n3. 内容审核与质量把控\n4. 用户运营策略制定与执行\n5. 数据分析与内容效果优化\n6. 社群运营与用户互动' },
  { role: '项目经理', icon: 'Calendar', desc: '负责项目计划、进度管控、风险管理', responsibilities: '1. 项目计划制定与WBS分解\n2. 进度跟踪与风险识别管理\n3. 资源协调与跨部门沟通\n4. 项目会议组织与纪要输出\n5. 项目复盘与经验总结\n6. 流程优化与工具引入' },
  { role: '渠道运营', icon: 'Link', desc: '负责渠道拓展、合作管理、流量增长', responsibilities: '1. 渠道拓展与合作伙伴开发\n2. 渠道合作协议谈判与签订\n3. 渠道数据分析与效果评估\n4. 渠道政策制定与优化\n5. 竞品渠道监测与情报收集\n6. 渠道活动策划与执行' },
  { role: '销售经理', icon: 'DollarSign', desc: '负责客户开发、商务谈判、业绩达成', responsibilities: '1. 客户开发与需求挖掘\n2. 商务谈判与合同签订\n3. 销售目标制定与分解\n4. 客户关系维护与续约管理\n5. 销售数据分析与预测\n6. 销售团队培训与赋能' },
  { role: '品牌策划', icon: 'Award', desc: '负责品牌定位、传播策略、品牌资产管理', responsibilities: '1. 品牌定位与价值主张提炼\n2. 品牌传播策略制定与执行\n3. 品牌视觉规范管理\n4. 品牌活动策划与落地\n5. 品牌舆情监测与危机应对\n6. 品牌效果评估与策略迭代' },
  { role: '营销策划', icon: 'Megaphone', desc: '负责营销方案、活动策划、推广投放', responsibilities: '1. 营销方案策划与预算管理\n2. 线上线下活动策划与执行\n3. 广告投放策略与效果优化\n4. 用户增长策略制定与落地\n5. 营销数据分析与ROI评估\n6. 跨部门协作推动营销目标达成' },
  { role: '人力资源', icon: 'Users', desc: '负责招聘、培训、绩效、员工关系', responsibilities: '1. 招聘需求分析与人才寻访\n2. 面试评估与录用决策\n3. 员工培训体系搭建与实施\n4. 绩效考核方案设计与执行\n5. 员工关系管理与文化活动\n6. 薪酬福利体系优化' },
  { role: '财务分析师', icon: 'TrendingUp', desc: '负责财务分析、预算管理、风控合规', responsibilities: '1. 财务报表分析与经营洞察\n2. 年度预算编制与执行监控\n3. 成本分析与降本增效建议\n4. 投资项目财务评估\n5. 税务筹划与合规管理\n6. 财务风险识别与预警' },
  { role: '客服主管', icon: 'Headphones', desc: '负责客户服务、工单管理、满意度提升', responsibilities: '1. 客服团队日常管理与排班\n2. 服务流程优化与SOP制定\n3. 客户投诉处理与升级机制\n4. 客户满意度调研与改善\n5. 客服数据分析与报表输出\n6. 知识库建设与培训赋能' },
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
  get: () => {
    if (!editingAgent.value) return {}
    return editingAgent.value.proxy_config ||= {}
  },
  set: (v) => { if (editingAgent.value) editingAgent.value.proxy_config = v }
})

const proxyGoalContract = computed(() => {
  const cfg = proxyCfg.value
  cfg.goal_contract ||= { enabled: false, input_budget: 4000, response_bytes: 128000, fields: {} }
  cfg.goal_contract.fields ||= {}
  return cfg.goal_contract
})
const goalInputSources = [
  { value: 'explicit', label: '用户填写的显式参数' }, { value: 'goal_task', label: '本次任务原文' },
  { value: 'observation_facts', label: '指定 Observation 的结构化事实' }, { value: 'observation_summary', label: '指定 Observation 的已有摘要' },
]
const setGoalContractEnabled = enabled => {
  proxyGoalContract.value.enabled = enabled
  if (enabled) for (const field of schemaFields.value) proxyGoalContract.value.fields[field.name] ||= ['explicit']
}
const toggleGoalSource = (field, source, enabled) => {
  const prior = proxyGoalContract.value.fields[field] || []
  proxyGoalContract.value.fields[field] = enabled ? [...new Set([...prior, source])] : prior.filter(value => value !== source)
}

const resolutionSources = [
  { value: 'current_task', label: '当前任务' },
  { value: 'conversation_context', label: '对话上下文' },
  { value: 'system', label: '系统值' },
  { value: 'previous_agent_output', label: '前序 Agent 输出' },
]

const promptSourceOptions = [
  { value: 'conversation_context', label: '最近对话' },
  { value: 'previous_agent_output', label: '前序 Agent 的结果' },
]

const proxyPromptResolution = computed(() => {
  const cfg = proxyCfg.value
  if (!cfg.prompt_resolution) {
    cfg.prompt_resolution = {
      enabled: false,
      version: 1,
      confidence_threshold: 0.7,
      allowed_sources: ['current_task', 'conversation_context', 'previous_agent_output'],
    }
  }
  cfg.prompt_resolution.allowed_sources ||= ['current_task', 'conversation_context', 'previous_agent_output']
  if (!cfg.prompt_resolution.allowed_sources.includes('current_task')) {
    cfg.prompt_resolution.allowed_sources.unshift('current_task')
  }
  return cfg.prompt_resolution
})

const proxyResolution = computed(() => {
  const cfg = proxyCfg.value
  if (!cfg.input_resolution) cfg.input_resolution = { enabled: false, version: 1, confidence_threshold: 0.8, fields: {} }
  cfg.input_resolution.fields ||= {}
  return cfg.input_resolution
})

const schemaFields = computed(() => {
  const schema = editingAgent.value?.input_schema || {}
  const required = new Set(schema.required || [])
  return Object.entries(schema.properties || {}).map(([name, definition]) => ({ name, description: definition?.description || '', required: required.has(name) }))
})

const fieldResolution = (name) => {
  const fields = proxyResolution.value.fields
  if (!fields[name]) fields[name] = { resolutionMode: 'strict', allowedSources: ['current_task'], resolutionHint: '' }
  fields[name].allowedSources ||= ['current_task']
  return fields[name]
}
const setPromptResolutionEnabled = (enabled) => {
  proxyPromptResolution.value.enabled = enabled
  if (enabled) proxyResolution.value.enabled = false
}
const togglePromptSource = (source, checked) => {
  const sources = proxyPromptResolution.value.allowed_sources
  proxyPromptResolution.value.allowed_sources = checked
    ? [...new Set([...sources, source])]
    : sources.filter(item => item !== source)
}
const setResolutionEnabled = (enabled) => {
  proxyResolution.value.enabled = enabled
  if (enabled) proxyPromptResolution.value.enabled = false
}
const updateResolutionThreshold = (value) => { proxyResolution.value.confidence_threshold = Math.max(0, Math.min(1, Number(value) || 0)) }
const updateFieldResolution = (name, key, value) => { fieldResolution(name)[key] = value }
const updateFieldDescription = (name, value) => { editingAgent.value.input_schema.properties[name].description = value }
const toggleSchemaRequired = (name, checked) => {
  const required = new Set(editingAgent.value.input_schema.required || [])
  checked ? required.add(name) : required.delete(name)
  editingAgent.value.input_schema.required = [...required]
}
const toggleFieldSource = (name, source, checked) => {
  const field = fieldResolution(name)
  field.allowedSources = checked ? [...new Set([...field.allowedSources, source])] : field.allowedSources.filter(item => item !== source)
}

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

const allSectionGroups = [
  { label: '基本', items: [
    { id: 'basic', icon: 'User', name: '基础信息' },
    { id: 'personality', icon: 'Smile', name: '人格' },
    { id: 'role', icon: 'Briefcase', name: '职责' },
    { id: 'boundary', icon: 'Shield', name: '工作边界' },
  ]},
  { label: '能力', items: [
    { id: 'proxy', icon: 'Link', name: 'Proxy 配置' },
    { id: 'schema', icon: 'FileText', name: 'Schema' },
    { id: 'model', icon: 'Bot', name: '模型配置' },
  ]},
  { label: '知识与数据', items: [
    { id: 'knowledge', icon: 'BookOpen', name: '知识库' },
    { id: 'tools', icon: 'Wrench', name: '工具' },
    { id: 'data', icon: 'BarChart', name: '数据' },
    { id: 'memory', icon: 'Brain', name: '记忆' },
  ]},
  { label: '系统', items: [
    { id: 'versions', icon: 'Package', name: '版本管理' },
  ]},
]
const sectionGroups = computed(() => allSectionGroups.map(group => ({
  ...group,
  items: group.items.filter(item => editingAgent.value?.agent_type === 'proxy'
    ? ['basic', 'proxy', 'schema', 'versions'].includes(item.id)
    : item.id !== 'proxy'),
})).filter(group => group.items.length))
watch(sectionGroups, groups => {
  if (!groups.some(group => group.items.some(item => item.id === currentSection.value))) {
    currentSection.value = 'basic'
  }
})

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
  window.dispatchEvent(new CustomEvent('toast', { detail: { message, type } }))
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
  editingAgent.value.role = editingAgent.value.name?.trim().toLocaleLowerCase() === rp.role.toLocaleLowerCase() ? '' : rp.role
  editingAgent.value.responsibilities = rp.responsibilities
  showToast('已填入「' + rp.role + '」预设内容')
}

// --- Boundary Presets ---
const boundaryPresets = [
  { icon: 'Shield', name: '保守型', desc: '严格按指令执行，不主动扩展任务范围', value: '【工作边界 - 保守型】\n可以做：\n- 严格按用户指令完成指定任务\n- 在已有知识范围内回答问题\n- 提供客观事实和数据\n\n不可以做：\n- 不主动扩展任务范围\n- 不执行未经确认的高风险操作\n- 不访问或修改未授权的资源' },
  { icon: 'Scale', name: '标准型', desc: '职责范围内主动思考，超出范围需确认', value: '【工作边界 - 标准型】\n可以做：\n- 在职责范围内主动分析和提供建议\n- 识别潜在问题并预警\n- 推荐优化方案\n\n需要确认：\n- 超出当前任务范围的额外操作\n- 涉及资金、权限变更的操作\n- 对外发布或通知类操作\n\n不可以做：\n- 未经确认删除重要数据\n- 绕过审批流程' },
  { icon: 'Rocket', name: '激进型', desc: '主动发现问题并解决，大胆提供建议', value: '【工作边界 - 激进型】\n可以做：\n- 主动发现问题并提出解决方案\n- 大胆给出创新性建议\n- 跨领域关联分析\n- 持续追问直到问题根因明确\n\n需要确认：\n- 直接执行影响生产环境的操作\n- 替代他人做决策\n\n不可以做：\n- 违反法律法规的操作\n- 泄露敏感信息' },
  { icon: 'Target', name: '协作型', desc: '主动协调资源，推动跨角色协作', value: '【工作边界 - 协作型】\n可以做：\n- 主动识别需要协作的环节\n- 推荐合适的协作角色或工具\n- 整合多方输入给出综合方案\n- 跟踪协作进度并提醒\n\n需要确认：\n- 代替其他角色做决策\n- 调整他人工作优先级\n\n不可以做：\n- 未经沟通直接分配任务给他人' },
  { icon: 'Shield', name: '合规型', desc: '严格遵守流程规范，留痕可审计', value: '【工作边界 - 合规型】\n可以做：\n- 按标准流程执行每一步\n- 记录操作日志和决策依据\n- 对照规范逐项检查\n\n需要确认：\n- 任何流程外的变通操作\n\n不可以做：\n- 跳过审批或检查环节\n- 未记录直接修改数据\n- 违反数据安全规范' },
]

const applyBoundaryPreset = (bp) => {
  if (!editingAgent.value) return
  editingAgent.value.boundaries = bp.value
  showToast('已填入「' + bp.name + '」边界预设')
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
    const { data } = await agentApi.listModels()
    providers.value = Object.fromEntries((data.providers || []).map(p => [p.name, p]))
  } catch (e) {
    console.error(e)
  }
}

const normalizeAgent = agent => ({ ...agent, collaboration: {
  autonomy: 'INHERIT_WORKSPACE', allow_incoming: true, discoverable: true, ...(agent.collaboration || {}),
} })

const loadAgentBudget = async id => {
  if (!id) return
  runtimeBudgetLoading.value = true
  runtimeBudgetLoaded.value = false
  runtimeBudgetError.value = ''
  try {
    const { data } = await agentApi.runtimeBudget(id)
    if (editingAgent.value?.id !== id) return
    runtimeWorkspaceBudget.value = data.workspace_budget
    runtimeBudgetSelected.value = Object.fromEntries(runtimeBudgetFields.map(field => [field.key, Object.hasOwn(data.budget || {}, field.key)]))
    runtimeBudgetDraft.value = Object.fromEntries(runtimeBudgetFields.map(field => [field.key,
      data.budget?.[field.key] ?? (data.workspace_budget[field.key] === UNLIMITED_BUDGET ? '' : data.workspace_budget[field.key])
    ]))
    runtimeBudgetLoaded.value = true
  } catch (e) {
    if (editingAgent.value?.id === id) runtimeBudgetError.value = e.response?.data?.detail || '运行预算读取失败，请重试'
  } finally {
    runtimeBudgetLoading.value = false
  }
}

const saveAgentBudget = async () => {
  if (!editingAgent.value?.id || !runtimeBudgetLoaded.value) return
  const budget = {}
  for (const field of runtimeBudgetFields) {
    if (!runtimeBudgetSelected.value[field.key]) continue
    const value = runtimeBudgetDraft.value[field.key]
    if (value === '' || value == null || !Number.isSafeInteger(Number(value)) || Number(value) < field.min || Number(value) > runtimeWorkspaceBudget.value[field.key]) {
      showToast(`${field.label} 必须为 ${field.min}–${runtimeWorkspaceBudget.value[field.key] === UNLIMITED_BUDGET ? '不限' : runtimeWorkspaceBudget.value[field.key]} 的整数`, 'error')
      return
    }
    budget[field.key] = Number(value)
  }
  runtimeBudgetSaving.value = true
  try {
    const agentId = editingAgent.value.id
    await agentApi.saveRuntimeBudget(agentId, Object.keys(budget).length ? budget : null)
    await loadAgentBudget(agentId)
    showToast('运行预算已保存')
  } catch (e) {
    showToast(e.response?.data?.detail || '运行预算保存失败', 'error')
  } finally {
    runtimeBudgetSaving.value = false
  }
}

const createNewAgent = async () => {
  const ws = currentWorkspace()
  if (!ws) { alert('请先选择工作空间'); return }
  try {
    const { data } = await agentApi.create(ws, { name: '新智能体', agent_type: 'llm' })
    editingAgent.value = normalizeAgent(data)
    loadAgentBudget(data.id)
    await loadAgents()
  } catch (e) {
    alert('创建失败: ' + (e.response?.data?.detail || e.message))
  }
}

const editAgent = (agent) => {
  editingAgent.value = normalizeAgent(agent)
  currentSection.value = 'basic'
  loadAgentBudget(agent.id)
  loadVersions(agent.id)
}

const saveAndExit = async () => {
  if (can('agent.update')) await saveAgent()
  editingAgent.value = null
  loadAgents()
}

const saveAgent = async () => {
  if (!editingAgent.value) return
  saving.value = true
  try {
    const { id, ...data } = editingAgent.value
    const result = await agentApi.update(id, data)
    editingAgent.value = normalizeAgent(result.data)
    showToast(result.data.status === 'draft' ? '草稿已保存，发布后可供用户使用' : '保存成功')
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
    if (can('agent.update')) await agentApi.update(id, saveData)
    
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

const runResolutionTest = async () => {
  if (!editingAgent.value?.id) return
  resolvingInput.value = true
  resolutionTestResult.value = null
  resolutionTestError.value = ''
  try {
    let conversationContext = resolutionTestContext.value.trim()
    if (conversationContext) {
      try { conversationContext = JSON.parse(conversationContext) } catch { /* 普通文本可直接用于简易整理模式 */ }
    } else {
      conversationContext = []
    }
    const { data } = await agentApi.resolveInput(editingAgent.value.id, {
      task: resolutionTestTask.value,
      conversation_context: conversationContext,
      previous_agent_output: JSON.parse(resolutionTestPrevious.value || '[]'),
      system: JSON.parse(resolutionTestSystem.value || '{}'),
      input_schema: editingAgent.value.input_schema || {},
      proxy_config: editingAgent.value.proxy_config || {},
    })
    resolutionTestResult.value = data
  } catch (e) {
    resolutionTestError.value = e instanceof SyntaxError ? `JSON 格式错误：${e.message}` : (e.response?.data?.detail || e.message)
  } finally {
    resolvingInput.value = false
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

const openAgentMenu = ref(null)
const toggleAgentMenu = (agentId) => {
  openAgentMenu.value = openAgentMenu.value === agentId ? null : agentId
}

// Close menu on outside click
if (typeof document !== 'undefined') {
  document.addEventListener('click', () => { openAgentMenu.value = null })
}

const chatWithAgent = (agent) => {
  localStorage.setItem('chatAgentId', agent.id)
  window.location.href = '/chat'
}

const duplicateAgent = async (agent) => {
  try {
    const payload = {
      name: agent.name + ' (副本)',
      description: agent.description,
      role: agent.role,
      personality: agent.personality,
      responsibilities: agent.responsibilities,
      boundaries: agent.boundaries,
      behavior: agent.behavior,
      model: agent.model,
      agent_type: agent.agent_type,
      avatar: agent.avatar,
      knowledge_base_ids: agent.knowledge_base_ids,
      tags: agent.tags,
    }
    await agentApi.create(payload)
    await loadAgents()
    showToast('智能体已复制')
  } catch (e) {
    showToast('复制失败', 'error')
  }
}

function updateResourceBindings(patch) {
  Object.assign(editingAgent.value, patch)
}

onMounted(() => {
  agentApi.searchStatus().then(({ data }) => { webSearchStatus.value = data }).catch(() => { webSearchStatus.value = { configured: false, message: '搜索服务状态读取失败，请刷新重试' } })
  loadAgents()
  loadProviders()
  loadAvailableModels()
  window.addEventListener('workspace-changed', loadAgents)
})

</script>

<style scoped>
.agents-page { height: var(--page-viewport-height); min-height: 0; display: flex; flex-direction: column; }

/* Agent List View */
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-header h1 { font-size: 24px; font-weight: 700; margin: 0; }
.page-header .subtitle { font-size: 14px; color: var(--text3); margin: 4px 0 0; }
.agents-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; padding-bottom: 32px; }
.agent-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 20px; cursor: pointer; transition: all var(--transition);
}
.agent-card:hover { border-color: var(--accent); box-shadow: var(--shadow-md); transform: translateY(-1px); }
/* Glass isolation/backdrop and hover transforms create a stacking context per card.
   Raise the owning card while its menu is open, even after the pointer leaves it. */
.agent-card-menu-open { position: relative; z-index: 2; }
.agent-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.agent-avatar {
  width: 80px; padding: 8px 4px; border-radius: 12px;
  display: flex; flex-direction: column; align-items: center; gap: 6px;
  background: var(--surface); color: var(--text2); font: inherit; font-size: 12px;
  background: var(--primary-light); display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.agent-avatar-img { width: 100%; height: 100%; object-fit: cover; }
.agent-avatar span { font-size: 22px; }
.agent-info { flex: 1; min-width: 0; }
.agent-name { font-weight: 600; font-size: 15px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.agent-role { font-size: 12px; color: var(--text3); margin-top: 2px; }
.agent-desc { font-size: 13px; color: var(--text2); line-height: 1.5; margin-bottom: 12px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.agent-meta { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.agent-meta span { font-size: 11px; color: var(--text3); }
.agent-type-badge { padding: 2px 8px; border-radius: var(--radius-xs); font-weight: 500; font-size: 11px; }
.agent-type-badge.type-llm { background: var(--accent-light); color: var(--primary); }
.agent-type-badge.type-proxy { background: color-mix(in srgb,#F59E0B 16%,transparent); color: light-dark(#92400E,#FBBF24); }
.agent-actions {
  display: flex; align-items: center; justify-content: space-between;
  margin-top: 14px; padding-top: 14px;
  border-top: 1px solid var(--surface2);
}
.agent-btn-chat {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 6px 14px; height: 32px;
  background: var(--primary); color: #fff; border: none;
  border-radius: 8px; font-size: 12px; font-weight: 600;
  cursor: pointer; transition: all 0.15s;
}
.agent-btn-chat:hover { background: var(--primary-hover); }
.agent-btn-more {
  display: flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; padding: 0;
  background: var(--surface2); border: 1px solid var(--border); border-radius: 8px;
  color: var(--text2); cursor: pointer; transition: all 0.12s;
}
.agent-btn-more:hover { background: var(--primary-light); color: var(--text); border-color: var(--primary); }
.agent-menu-wrap { position: relative; }
.agent-dropdown {
  position: absolute; top: calc(100% + 6px); right: 0; z-index: 50;
  min-width: 160px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 4px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.1);
}
.agent-dropdown-item {
  display: flex; align-items: center; gap: 8px; width: 100%;
  padding: 8px 12px; border: none; background: none; border-radius: 8px;
  font-size: 13px; color: var(--text2); cursor: pointer; text-align: left;
  transition: background 0.1s;
}
.agent-dropdown-item:hover { background: var(--surface2); }
.agent-dropdown-item.danger { color: var(--danger); }
.agent-dropdown-item.danger:hover { background: var(--danger-bg); }
.agent-dropdown-divider { height: 1px; background: var(--border); margin: 4px 0; }
.empty-state { text-align: center; padding: 60px 20px; color: var(--text3); }
.empty-icon { font-size: 48px; margin-bottom: 12px; }

/* Header */
.editor-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 24px; border-bottom: 1px solid var(--border);
  background: var(--surface); min-height: 64px;
}
.btn-back {
  background: none; border: none; color: var(--text2); cursor: pointer;
  font-size: 14px; padding: 6px 12px; border-radius: var(--radius-xs);
  transition: all var(--transition);
}
.btn-back:hover { color: var(--text); background: var(--surface2); }
.editor-title { display: flex; align-items: center; gap: 10px; }
.editor-title h2 { font-size: 18px; font-weight: 600; margin: 0; color: var(--text); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; }
.status-dot.draft { background: #F59E0B; }
.status-dot.active { background: #10B981; }
.status-dot.disabled { background: #9CA3AF; }
.status-text { font-size: 13px; color: var(--text3); }
.editor-actions { display: flex; gap: 10px; }

/* Buttons */
.btn {
  padding: 9px 18px; border-radius: 9px; border: none; cursor: pointer;
  font-size: 14px; font-weight: 500; transition: all var(--transition);
  display: inline-flex; align-items: center; gap: 6px;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: var(--primary); color: #fff; }
.btn-primary:hover:not(:disabled) { background: var(--primary-hover); }
.btn-outline { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
.btn-outline:hover:not(:disabled) { background: var(--surface2); border-color: var(--text3); }
.btn-ghost { background: transparent; color: var(--text2); }
.btn-ghost:hover { background: var(--surface2); color: var(--text); }
.btn-sm { padding: 5px 12px; font-size: 13px; }
.btn-xs { padding: 3px 8px; font-size: 12px; }
.btn-danger { background: transparent; color: var(--danger); border: 1px solid color-mix(in srgb,var(--danger) 35%,var(--border)); }
.btn-danger:hover { background: var(--danger-bg); }

/* Layout */
.editor-layout { display: flex; flex: 1; overflow: hidden; }

/* Settings Nav */
.editor-nav {
  width: 200px; border-right: 1px solid var(--border); background: var(--surface);
  padding: 16px 12px; overflow-y: auto; flex-shrink: 0;
}
.nav-group { margin-bottom: 20px; }
.nav-group-label {
  font-size: 11px; font-weight: 600; color: var(--text3); text-transform: uppercase;
  letter-spacing: 0.5px; padding: 0 12px; margin-bottom: 6px;
}
.editor-nav .nav-item {
  display: flex; align-items: center; gap: 10px; padding: 9px 12px;
  border-radius: var(--radius-sm); cursor: pointer; font-size: 14px;
  color: var(--text2); transition: all var(--transition); position: relative;
  margin-bottom: 2px;
}
.editor-nav .nav-item:hover { background: var(--surface2); color: var(--text); }
.editor-nav .nav-item.active {
  background: var(--primary-light); color: var(--primary); font-weight: 600;
}
.nav-indicator {
  width: 3px; height: 0; background: var(--primary); border-radius: 2px;
  position: absolute; left: 0; transition: height var(--transition);
}
.editor-nav .nav-item.active .nav-indicator { height: 20px; }

/* Main Content */
.editor-content { flex: 1; min-width: 0; overflow-y: auto; padding: 28px 32px; background: var(--bg); }
.field-usage-note { display: block; margin-top: 6px; color: var(--text3); font-size: 12px; line-height: 1.5; }
.section { width: 100%; min-width: 0; max-width: none; }
.section h3 {
  font-size: 18px; line-height: 26px; font-weight: 650; color: var(--text); margin: 0 0 16px;
}
.section-desc { font-size: 13px; line-height: 22px; overflow-wrap: anywhere; color: var(--text2); margin: 0 0 20px; }

/* Form */
.form-group { margin-bottom: 20px; }
.form-group label {
  display: block; font-size: 13px; font-weight: 500; color: var(--text); margin-bottom: 6px;
}
.form-group input:not([type="checkbox"]):not([type="radio"]), .form-group textarea {
  width: 100%; padding: 10px 14px; border: 1px solid var(--border); border-radius: 10px;
  font-size: 14px; box-sizing: border-box; background: var(--surface); color: var(--text);
  transition: all var(--transition); height: 44px;
}
.form-group textarea { height: auto; min-height: 120px; }
.form-group input:not([type="checkbox"]):not([type="radio"]):focus, .form-group textarea:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(139,92,246,0.1);
}
.form-group input[type="checkbox"], .form-group input[type="radio"] {
  width: 16px; height: 16px; margin: 0 7px 0 0; vertical-align: -3px;
  accent-color: var(--primary); cursor: pointer;
}
.form-group .mono { font-family: 'SF Mono', 'Consolas', monospace; font-size: 13px; }
.form-row { display: flex; gap: 16px; }
.form-row .form-group { flex: 1; min-width: 0; }

/* Tags */
.tag {
  display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px;
  background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius-xs);
  font-size: 12px; color: var(--text2);
}
.tag button { background: none; border: none; color: var(--text3); cursor: pointer; padding: 0; font-size: 14px; }

/* Avatar */
.avatar-upload-area { display: flex; align-items: center; gap: 16px; margin-bottom: 12px; }
.avatar-preview {
  width: 72px; height: 72px; border-radius: 20px; overflow: hidden;
  background: var(--primary-light); display: flex; align-items: center; justify-content: center;
  cursor: pointer; transition: all var(--transition); border: 2px solid var(--border);
  flex-shrink: 0;
}
.avatar-preview:hover { border-color: var(--accent); }
.avatar-preview-img { width: 100%; height: 100%; object-fit: cover; }
.avatar-placeholder { font-size: 13px; color: var(--text3); text-align: center; line-height: 1.3; }
.avatar-hint { font-size: 12px; color: var(--text3); }
.preset-avatars { margin-top: 8px; }
.preset-label { font-size: 12px; color: var(--text3); margin-bottom: 8px; display: block; }
.preset-avatar-grid { display: flex; gap: 8px; flex-wrap: wrap; }
.preset-avatar-item {
  width: 48px; height: 48px; border-radius: 14px; overflow: hidden;
  cursor: pointer; border: 2px solid transparent; transition: all var(--transition);
}
.preset-avatar-item:hover { border-color: var(--accent); transform: scale(1.05); }
.preset-avatar-item.active { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(124,58,237,0.15); }
.preset-avatar-item img { width: 48px; height: 48px; border-radius: 12px; object-fit: cover; }
.preset-avatar-item:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }

/* Agent Type Toggle */
.agent-type-toggle { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 8px; }
.type-btn {
  flex: 1 1 140px; display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; padding: 12px 16px; border: 1px solid var(--border); border-radius: var(--radius);
  background: var(--surface); color: var(--text); cursor: pointer; text-align: left; transition: all var(--transition);
}
.type-btn:hover { border-color: var(--accent); }
.type-btn.active { border-color: var(--primary); background: var(--accent-light); }
.type-btn .type-title { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
.type-btn .type-desc { font-size: 12px; color: var(--text3); }
.type-hint { font-size: 12px; line-height: 20px; color: var(--text2); padding: 8px 0; }

/* Preset Chips */
.preset-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.preset-label { font-size: 12px; color: var(--text3); margin-bottom: 4px; display: block; }
.preset-chip {
  padding: 5px 12px; border: 1px solid var(--border); border-radius: var(--radius-xs);
  background: var(--surface); cursor: pointer; font-size: 12px; color: var(--text2);
  transition: all var(--transition);
}
.preset-chip:hover { border-color: var(--accent); color: var(--primary); background: var(--accent-light); }

/* Role Presets */
.role-presets { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(200px, 100%), 1fr)); gap: 8px; margin-top: 8px; }
.role-preset-card {
  display: flex; align-items: center; gap: 10px; padding: 10px 12px;
  border: 1px solid var(--border); border-radius: var(--radius-sm); cursor: pointer;
  transition: all var(--transition); background: var(--surface); color: var(--text);
}
.role-preset-card:hover { border-color: var(--accent); background: var(--accent-light); }
.role-preset-icon { font-size: 20px; }
.role-preset-name { font-size: 13px; font-weight: 500; }
.role-preset-desc { font-size: 11px; color: var(--text3); }

/* Preset Cards */
.preset-card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(220px, 100%), 1fr)); gap: 8px; margin-top: 8px; }
.preset-card-item {
  display: flex; align-items: center; gap: 10px; padding: 10px 12px;
  border: 1px solid var(--border); border-radius: var(--radius-sm); cursor: pointer;
  transition: all var(--transition); background: var(--surface); color: var(--text);
}
.preset-card-item:hover { border-color: var(--accent); background: var(--accent-light); }
.preset-card-icon { font-size: 18px; }
.preset-card-name { font-size: 13px; font-weight: 500; }
.preset-card-desc { font-size: 11px; color: var(--text3); }

/* Proxy */
.proxy-disabled { opacity: 0.5; pointer-events: none; }
.proxy-disabled-hint { font-size: 13px; color: var(--text3); padding: 12px; background: var(--surface2); border-radius: var(--radius-sm); margin-bottom: 16px; }
.field-mapping-hint { font-size: 12px; color: var(--text3); margin-top: 6px; }
.prompt-resolution-card { margin: 4px 0 18px; padding: 16px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface2); }
.prompt-resolution-card h4 { margin: 0; font-size: 15px; }
.prompt-resolution-card .resolution-config-head p { margin: 4px 0 0; color: var(--text3); font-size: 12px; line-height: 18px; }
.prompt-resolution-body { margin-top: 16px; }
.prompt-resolution-body .form-group:last-child { margin-bottom: 0; }
.compact-group { margin-bottom: 0; }
.simple-source-options { display: flex; flex-wrap: wrap; gap: 8px; }
.simple-source-options label { display: inline-flex; align-items: center; gap: 7px; margin: 0; padding: 8px 11px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface); color: var(--text2); cursor: pointer; }
.simple-source-options input { width: 15px; height: 15px; margin: 0; accent-color: var(--primary); }
.proxy-advanced { margin-bottom: 20px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
.proxy-advanced > summary { padding: 12px 14px; color: var(--text2); font-size: 13px; cursor: pointer; }
.proxy-advanced[open] > summary { color: var(--primary); }
.proxy-advanced-body { padding: 12px 14px 0; border-top: 1px solid var(--border); }
.resolution-config { margin: 20px 0; padding: 16px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface2); }
.resolution-config-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.resolution-config h4 { margin: 0; font-size: 15px; }
.resolution-config-head p { margin: 4px 0 0; color: var(--text3); font-size: 12px; line-height: 18px; }
.resolution-threshold { width: 180px; margin-top: 16px; }
.resolution-fields { display: grid; gap: 10px; margin-top: 12px; }
.resolution-field { padding: 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
.resolution-field-title { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.resolution-field-title code { color: var(--primary); font-weight: 600; }
.required-badge { padding: 1px 6px; border-radius: 5px; color: var(--danger); background: var(--danger-bg); font-size: 10px; }
.resolution-field > label { display: block; margin-top: 9px; color: var(--text2); font-size: 12px; }
.resolution-field textarea, .resolution-field input[type="text"] { width: 100%; margin-top: 5px; }
.resolution-field :deep(.search-select-trigger) { width: 100%; margin-top: 5px; }
.resolution-field > .resolution-required { display: flex; align-items: center; gap: 5px; }
.resolution-field > .resolution-required input { width: auto; margin: 0; }
.resolution-source-label { margin-top: 9px; color: var(--text2); font-size: 12px; }
.resolution-sources { display: flex; flex-wrap: wrap; gap: 6px 12px; margin-top: 5px; }
.resolution-sources label { display: flex; align-items: center; gap: 4px; color: var(--text2); font-size: 11px; }
.resolver-test { margin: 0; }
.resolver-advanced { margin: 8px 0 12px; color: var(--text2); font-size: 12px; }
.resolver-advanced summary { margin-bottom: 10px; color: var(--primary); cursor: pointer; }
.resolver-advanced label { display: block; margin-top: 8px; }
.resolver-advanced textarea { width: 100%; margin-top: 5px; }
.resolver-test-button { width: 100%; }

/* Model */
.agent-budget-card { margin: 12px 0 24px; padding: 16px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
.agent-budget-head, .agent-budget-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.agent-budget-head h4 { display: flex; align-items: center; gap: 7px; margin: 0; font-size: 15px; }
.agent-budget-head h4 small { color: var(--text3); font-size: 12px; font-weight: 400; }
.agent-budget-head p { margin: 6px 0 0; color: var(--text2); font-size: 12px; }
.agent-budget-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 16px; }
.agent-budget-field { display: grid; gap: 6px; min-width: 0; }
.agent-budget-override { display: flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 600; cursor: pointer; }
.agent-budget-override input { width: 16px; height: 16px; margin: 0; flex: none; accent-color: var(--primary); }
.agent-budget-override small { color: var(--text3); font-weight: 400; }
.agent-budget-field > input { width: 100%; height: 36px; padding: 6px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--text); box-sizing: border-box; }
.agent-budget-field > input:disabled { background: var(--surface2); color: var(--text3); }
.agent-budget-field > small { color: var(--text3); font-size: 11px; }
.agent-budget-actions { margin-top: 18px; }
.agent-budget-actions a { color: var(--primary); font-size: 12px; }
.agent-budget-error { color: var(--danger); font-size: 12px; }
.model-selector { margin-bottom: 12px; }
.collaboration-autonomy-select :deep(.search-select-trigger) { font-size: 14px; }
.default-model-hint { font-size: 12px; color: var(--text3); margin-bottom: 6px; padding: 6px 10px; background: var(--accent-light); border-radius: var(--radius-xs); }
.model-select { width: 100%; }
.model-select :deep(.search-select-trigger) { min-height: 38px; }

/* Versions */
.version-item { padding: 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); margin-bottom: 8px; background: var(--surface); }
.version-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.version-number { font-weight: 600; font-size: 14px; }
.version-meta { font-size: 12px; color: var(--text3); }
.version-notes { font-size: 13px; color: var(--text2); margin-top: 6px; }
.badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 500; }
.badge-active { background: var(--success-bg); color: var(--success); }
.badge-published { background: var(--accent-light); color: var(--primary); }
.empty-hint { color: var(--text3); font-size: 13px; padding: 12px 0; }

/* Test Panel */
.editor-test {
  width: 380px; border-left: 1px solid var(--border); background: var(--surface);
  padding: 20px; overflow-y: auto; flex-shrink: 0;
}
.editor-test h3 { font-size: 16px; font-weight: 600; margin: 0 0 16px; color: var(--text); }
.test-json-error { font-size: 12px; color: var(--danger); margin-top: 6px; }
.test-result { margin-top: 16px; }
.test-result h4 { font-size: 14px; font-weight: 600; margin: 0 0 8px; }
.result-status { padding: 8px 12px; border-radius: var(--radius-xs); font-size: 13px; font-weight: 500; margin-bottom: 8px; }
.result-status.success { background: var(--success-bg); color: var(--success); }
.result-status.error { background: var(--danger-bg); color: var(--danger); }
.error-msg { font-size: 13px; color: var(--danger); margin-top: 6px; }
.duration { font-size: 12px; color: var(--text3); margin-top: 6px; }

/* Knowledge Base */
.kb-section > .knowledge-card { margin-top: 14px; }
.kb-section { margin-bottom: 24px; }
.kb-section h4 { margin: 0 0 12px; font-size: 15px; color: var(--text); display: flex; align-items: center; gap: 6px; }
.kb-hint { font-weight: normal; font-size: 13px; color: var(--text3); }
.kb-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; margin-bottom: 10px; transition: box-shadow 0.15s; }
.kb-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.kb-card-readonly { border-left: 3px solid var(--primary); }
.kb-card-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.kb-card-info { flex: 1; min-width: 0; }
.kb-card-name { font-weight: 500; font-size: 14px; display: flex; align-items: center; gap: 6px; }
.kb-card-meta { font-size: 12px; color: var(--text3); margin-top: 2px; }
.kb-card-actions { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
.kb-docs { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border); }
.kb-doc-item { display: flex; align-items: center; justify-content: space-between; padding: 6px 8px; font-size: 13px; border-radius: 6px; }
.kb-doc-item:hover { background: var(--surface2); }
.kb-doc-name { color: var(--text); display: flex; align-items: center; gap: 6px; }
.kb-create-row { display: flex; gap: 8px; margin-bottom: 14px; }
.kb-create-row input { flex: 1; padding: 8px 12px; border: 1px solid var(--border); border-radius: var(--radius-xs); font-size: 13px; }
.toggle-label { display: flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; padding: 4px 10px; border-radius: 6px; transition: background 0.15s; }
.toggle-label:hover { background: var(--surface2); }
.toggle-label input[type="checkbox"] { width: 16px; height: 16px; cursor: pointer; accent-color: var(--primary); }

/* Upload Progress */
.upload-progress-wrap { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; }
.upload-progress-text { font-size: 11px; color: var(--text3); font-weight: 600; white-space: nowrap; }
.upload-progress-bar { flex: 1; height: 6px; background: var(--surface2); border-radius: 3px; overflow: hidden; min-width: 60px; }
.upload-progress-fill { height: 100%; background: linear-gradient(90deg, var(--primary), var(--primary-hover, #9333ea)); border-radius: 3px; transition: width 0.3s ease; }
.upload-progress-file { font-size: 11px; color: var(--text3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 140px; }

/* Data Binding */
.section-hint { color: var(--text3); font-size: 13px; margin: -8px 0 16px; }
.data-bind-section { margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--border); }
.data-bind-section h4 { margin: 0 0 10px; font-size: 14px; color: var(--text); }
.type-badge { font-size: 11px; padding: 2px 6px; border-radius: 4px; font-weight: 600; margin-right: 6px; }
.type-postgres { background: color-mix(in srgb,#3B82F6 16%,transparent); color: light-dark(#1D4ED8,#60A5FA); }
.type-mysql { background: color-mix(in srgb,#F59E0B 16%,transparent); color: light-dark(#92400E,#FBBF24); }
.type-api { background: color-mix(in srgb,#6366F1 16%,transparent); color: light-dark(#4338CA,#A5B4FC); }
.status-badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.status-active { background: var(--success-bg); color: var(--success); }
.status-inactive { background: var(--surface2); color: var(--text2); }
.status-error { background: var(--danger-bg); color: var(--danger); }

/* Crop Modal */
.modal-overlay { position: fixed; inset: 0; background: var(--overlay); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal { background: var(--surface); color: var(--text); border:1px solid var(--border); border-radius: var(--radius); padding: 24px; width: 520px; max-width: 90vw; max-height: 85vh; overflow-y: auto; box-shadow: var(--shadow-md); }
.modal-wide { width: 680px; }
.modal h3 { margin: 0 0 16px; font-size: 18px; font-weight: 600; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }

/* CM Editor */
.cm-editor-wrap { border-radius: var(--radius-sm); overflow: hidden; border: 1px solid var(--border); }

.cm-result { max-height: 200px; }
.btn-link { background: none; border: none; color: var(--primary); cursor: pointer; font-size: 13px; padding: 0; }
.btn-link:hover { text-decoration: underline; }

/* Toast (legacy fallback) */
.empty-state { text-align: center; padding: 60px 20px; color: var(--text3); }
.empty-icon { font-size: 48px; margin-bottom: 12px; }

/* ===== Memory Section ===== */
.memory-filters { display: flex; gap: 6px; margin-bottom: 12px; }
.mem-filter-btn {
  padding: 5px 14px; border: 1px solid var(--border); background: var(--surface);
  border-radius: 8px; font-size: 12px; color: var(--text2); cursor: pointer;
  transition: all 0.15s;
}
.mem-filter-btn:hover { border-color: var(--border); }
.mem-filter-btn.active { background: var(--primary); color: #fff; border-color: var(--primary); }

.memory-item {
  padding: 12px 14px; border: 1px solid var(--border); border-radius: 10px;
  margin-bottom: 8px; background: var(--surface); position: relative;
}
.memory-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.memory-header-right { display: flex; align-items: center; gap: 6px; margin-left: auto; }
.memory-type-badge {
  font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 6px;
}
.type-semantic { background: color-mix(in srgb,#3B82F6 16%,transparent); color: light-dark(#1D4ED8,#60A5FA); }
.type-focus { background: color-mix(in srgb,#8B5CF6 16%,transparent); color: light-dark(#6D28D9,#C4B5FD); }
.type-episodic { background: color-mix(in srgb,#F59E0B 16%,transparent); color: light-dark(#B45309,#FBBF24); }
.memory-importance { font-size: 11px; color: var(--text3); }
.memory-time { font-size: 11px; color: var(--text3); white-space: nowrap; }
.memory-content { font-size: 13px; color: var(--text2); line-height: 1.6; }
.memory-actions {
  display: flex; gap: 2px;
  opacity: 0; transition: opacity 0.15s;
}
.memory-item:hover .memory-actions { opacity: 1; }
.mem-action-btn {
  background: none; border: none; color: var(--text3); cursor: pointer;
  padding: 4px; border-radius: 4px;
}
.mem-action-btn:hover { color: var(--danger); background: var(--danger-bg); }
.edit-btn:hover { color: var(--primary); background: var(--primary-light); }
.memory-new { margin-bottom: 12px; }
.memory-new-header { margin-bottom: 8px; }
.mem-add-btn {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 5px 12px; border: 1px dashed var(--border); background: var(--surface);
  border-radius: 8px; font-size: 12px; color: var(--text2); cursor: pointer;
  transition: all 0.15s;
}
.mem-add-btn:hover { border-color: var(--primary); color: var(--primary); }
.memory-new-form {
  padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px;
  background: var(--surface);
}
.memory-new-row { display: flex; gap: 8px; }
.memory-new-select {
  padding: 6px 10px; border: 1px solid var(--border); border-radius: 8px;
  font-size: 12px; color: var(--text); background: var(--surface); flex-shrink: 0;
}
.memory-new-input {
  flex: 1; padding: 6px 10px; border: 1px solid var(--border); border-radius: 8px;
  font-size: 13px; color: var(--text); background: var(--surface);
}
.memory-new-input:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 2px rgba(99,102,241,0.15); }
.memory-new-actions { display: flex; justify-content: flex-end; margin-top: 8px; }
.mem-add-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.memory-importance-control { display: flex; align-items: center; gap: 10px; margin: 10px 0; font-size: 12px; color: var(--text2); }
.memory-importance-control input { flex: 1; min-width: 80px; max-width: 220px; accent-color: var(--primary); }
.memory-importance-control output { min-width: 36px; font-variant-numeric: tabular-nums; }
.memory-edit-options { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; margin-bottom: 8px; }
.memory-edit-options .memory-importance-control { flex: 1; min-width: 180px; }
.memory-item:focus-within .memory-actions { opacity: 1; }
.memory-edit { margin-top: 4px; }
.memory-edit-input {
  width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px;
  font-size: 13px; color: var(--text); resize: vertical; font-family: inherit;
  line-height: 1.5; background: var(--surface);
}
.memory-edit-input:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 2px rgba(99,102,241,0.15); }
.memory-edit-actions { display: flex; gap: 6px; margin-top: 6px; }
.mem-edit-save {
  padding: 4px 14px; background: var(--primary); color: #fff; border: none;
  border-radius: 6px; font-size: 12px; cursor: pointer;
}
.mem-edit-save:hover { opacity: 0.9; }
.mem-edit-cancel {
  padding: 4px 14px; background: var(--surface2); color: var(--text2); border: none;
  border-radius: 6px; font-size: 12px; cursor: pointer;
}
.mem-edit-cancel:hover { background: var(--border); }

.preview-modal { background: var(--surface); border-radius: 12px; width: 800px; max-width: 90vw; max-height: 85vh; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }
.preview-header { display: flex; align-items: center; gap: 12px; padding: 16px 20px; border-bottom: 1px solid var(--border); }
.preview-title { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 15px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.preview-meta { display: flex; gap: 12px; font-size: 12px; color: var(--text3); flex-shrink: 0; }
.preview-badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; }
.badge-success { background: var(--success-bg); color: var(--success); }
.badge-warning { background: color-mix(in srgb,#F59E0B 16%,transparent); color: light-dark(#92400E,#FBBF24); }
.preview-body { flex: 1; overflow: auto; padding: 20px; min-height: 200px; max-height: calc(85vh - 60px); }
.preview-loading { text-align: center; padding: 40px; color: var(--text3); }
.preview-unsupported { text-align: center; padding: 40px; color: var(--text3); }
.preview-image-wrap { text-align: center; }
.preview-image { max-width: 100%; max-height: 70vh; object-fit: contain; }
.preview-text { white-space: pre-wrap; word-wrap: break-word; font-family: 'SF Mono', 'Consolas', monospace; font-size: 13px; line-height: 1.6; margin: 0; background: var(--surface2); padding: 16px; border-radius: 8px; border: 1px solid var(--border); }
.kb-doc-actions { display: flex; gap: 4px; }
.preview-pdf-wrap { width: 100%; height: 100%; }
.preview-pdf-iframe { width: 100%; height: calc(85vh - 80px); border: none; border-radius: 8px; }

/* Tool configuration: scoped panels, compact rows, and distinct service state. */
.section.capabilities-layout { max-width: none; display: grid; gap: 20px; }
.agent-search-panel { min-width: 0; padding: 20px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm); }
.capability-heading { display: flex; align-items: center; gap: 12px; margin-bottom: 18px; }
.capability-icon { width: 40px; height: 40px; flex: 0 0 40px; display: grid; place-items: center; color: var(--primary); background: var(--primary-light); border-radius: 10px; }
.capability-heading-copy { flex: 1; min-width: 0; }
.agent-search-panel .capability-heading h3 { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0; padding: 0; border: 0; font-size: 16px; line-height: 24px; font-weight: 650; }
.capability-heading-copy p { margin: 4px 0 0; color: var(--text2); font-size: 13px; line-height: 20px; }
.capability-count { display: inline-flex; align-items: center; padding: 1px 7px; border-radius: 5px; background: var(--surface2); color: var(--text2); font-size: 11px; line-height: 20px; font-weight: 500; }
.capability-switch { display: flex; position: relative; align-items: center; gap: 8px; flex-shrink: 0; color: var(--text2); font-size: 12px; cursor: pointer; }
.capability-switch input { position: absolute; right: 0; width: 38px; height: 24px; margin: 0; opacity: 0; cursor: pointer; }
.capability-switch-track { display: block; width: 38px; height: 22px; border-radius: 12px; background: var(--border); pointer-events: none; transition: background .15s; }
.capability-switch-track::after { content: ''; display: block; width: 16px; height: 16px; margin: 3px; border-radius: 50%; background: #fff; box-shadow: 0 1px 3px #0002; transition: transform .15s; }
.capability-switch input:checked + .capability-switch-track { background: var(--primary); }
.capability-switch input:checked + .capability-switch-track::after { transform: translateX(16px); }
.capability-switch input:focus-visible + .capability-switch-track { outline: 2px solid var(--primary); outline-offset: 3px; }
.capability-switch input:disabled { cursor: not-allowed; }
.capability-switch input:disabled + .capability-switch-track { opacity: .5; }
.search-service-notice { display: flex; align-items: flex-start; gap: 8px; padding: 10px 12px; border: 1px solid color-mix(in srgb,#F59E0B 35%,var(--border)); border-radius: 8px; background: color-mix(in srgb,#F59E0B 10%,var(--surface)); color: light-dark(#926119,#FBBF24); font-size: 12px; line-height: 20px; }
.search-service-notice svg { flex-shrink: 0; margin-top: 2px; }
.search-service-notice.ready { color: var(--success); background: var(--success-bg); border-color: color-mix(in srgb,var(--success) 35%,var(--border)); }
.capability-footnote { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 5px 20px; margin-top: 12px; color: var(--text2); font-size: 11px; line-height: 18px; }
.capability-list { border: 1px solid var(--border); border-radius: 9px; overflow: hidden; }
.capability-row { display: flex; align-items: center; gap: 12px; min-height: 66px; padding: 12px 14px; }
.capability-row + .capability-row { border-top: 1px solid var(--border); }
.capability-row-icon { flex-shrink: 0; color: var(--text3); }
.capability-row-copy { flex: 1; min-width: 0; }
.capability-row-title { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; color: var(--text); font-size: 14px; font-weight: 550; line-height: 22px; overflow-wrap: anywhere; }
.capability-row-description { margin-top: 2px; color: var(--text2); font-size: 12px; line-height: 18px; overflow-wrap: anywhere; }
.capability-row > button, .capability-row > .status-badge { flex-shrink: 0; }
.capability-unbind { color: var(--text2); }
.capability-unbind:hover { color: var(--danger); background: var(--danger-bg); }
.capability-available { margin-top: 16px; }
.capability-available summary { display: flex; align-items: center; justify-content: space-between; gap: 8px; cursor: pointer; color: var(--primary); font-size: 13px; line-height: 24px; list-style: none; }
.capability-available summary::-webkit-details-marker { display: none; }
.capability-available summary > span { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.capability-available summary:focus-visible { outline: 2px solid var(--primary); outline-offset: 3px; border-radius: 4px; }
.capability-available[open] summary { margin-bottom: 12px; }
.capability-available[open] summary > svg { transform: rotate(180deg); }
.capability-bottom-note { margin: 12px 0 0; color: var(--text3); font-size: 12px; line-height: 20px; }
.capability-empty { padding: 18px 14px; border: 1px dashed var(--border); border-radius: 8px; color: var(--text2); font-size: 13px; line-height: 20px; }
@media (max-width: 700px) {
  .agent-search-panel { padding: 16px; }
  .capability-heading { flex-wrap: wrap; gap: 10px; }
  .capability-heading-copy { flex-basis: calc(100% - 50px); }
  .capability-switch { margin-left: auto; }
  .capability-row { padding: 10px; gap: 8px; }
}

@media (max-width: 1100px) {
  .editor-nav { width: 160px; padding: 12px 8px; }
  .editor-content { padding: 24px; }
  .editor-layout { flex-wrap: wrap; }
  .editor-test { width: 100%; max-height: 300px; border-left: 0; border-top: 1px solid var(--border); }
}
@media (max-width: 700px) {
  .editor-layout { flex-direction: column; flex-wrap: nowrap; }
  .form-row { flex-direction: column; gap: 0; }
  .btn { white-space: nowrap; flex-shrink: 0; }
  .editor-nav { width: 100%; border-right: 0; border-bottom: 1px solid var(--border); display: flex; gap: 12px; overflow-x: auto; overflow-y: hidden; padding: 8px; }
  .nav-group { margin: 0; flex-shrink: 0; display: flex; gap: 4px; }
  .nav-group-label { display: none; }
  .editor-nav .nav-item { white-space: nowrap; margin-bottom: 0; }
  .editor-content { padding: 16px; }
  .editor-header { flex-wrap: wrap; gap: 12px; padding: 12px; }
  .editor-title { min-width: 0; flex: 1 0 100%; order: -1; justify-content: flex-start; }.editor-title h2 { overflow-wrap: anywhere; }
  .editor-title .status-badge { flex-shrink: 0; white-space: nowrap; }
  .editor-actions { margin-left: auto; }
  .agents-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>

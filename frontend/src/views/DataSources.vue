<template>
  <div class="data-sources-page">
    <!-- Tabs -->
    <div class="data-tabs" aria-label="数据管理分类">
      <button v-for="t in tabs" :key="t.id" :class="['data-tab-button', { active: activeTab === t.id }]" @click="activeTab = t.id">
        <component :is="iconMap[t.icon]" :size="15" style="margin-right:5px" /> {{ t.name }}
      </button>
    </div>

    <!-- ===== 数据源 ===== -->
    <div v-if="activeTab === 'sources'" class="tab-content">
      <div class="section-header">
        <h3>数据源</h3>
        <button class="btn btn-primary btn-sm" @click="showCreateSource = true">+ 新建数据源</button>
      </div>
      <div v-if="sources.length === 0" class="empty-hint">暂无数据源</div>
      <div v-for="ds in sources" :key="ds.id" class="card">
        <div class="card-header">
          <div>
            <div class="card-name">
              <span :class="['type-badge', 'type-' + ds.type]">{{ ds.type.toUpperCase() }}</span>
              {{ ds.name }}
            </div>
            <div class="card-meta">{{ ds.config?.host || '-' }}:{{ ds.config?.port || '' }} / {{ ds.config?.database || '-' }}</div>
          </div>
          <div class="card-actions">
            <span :class="['status-badge', 'status-' + ds.status]">{{ statusText(ds.status) }}</span>
            <button class="btn btn-ghost btn-sm" @click="editSource(ds)"><Edit :size="14" /> 编辑</button>
            <button class="btn btn-danger btn-sm" @click="deleteSource(ds.id)">删除</button>
          </div>
        </div>
        <div v-if="ds._testResult" :class="['test-result', ds._testResult.success ? 'success' : 'error']">
          {{ ds._testResult.message }}
        </div>
      </div>

      <!-- Create Source Modal -->
      <div v-if="showCreateSource" class="modal-overlay" @click.self="showCreateSource = false">
        <div class="modal">
          <h3>新建数据源</h3>
          <div class="form-group">
            <label>名称 *</label>
            <input v-model="newSource.name" placeholder="例如：销售数据库" />
          </div>
          <div class="form-group">
            <label>类型 *</label>
            <SearchSelect v-model="newSource.type" :options="sourceTypeOptions" placeholder="选择数据源类型" aria-label="新建数据源类型" />
          </div>
          <div class="form-group">
            <label>描述</label>
            <textarea v-model="newSource.description" rows="2"></textarea>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>Host *</label>
              <input v-model="newSource.config.host" placeholder="localhost" />
            </div>
            <div class="form-group">
              <label>Port *</label>
              <input v-model.number="newSource.config.port" :placeholder="newSource.type === 'mysql' ? '3306' : '5432'" />
            </div>
          </div>
          <div class="form-group">
            <label>Database *</label>
            <input v-model="newSource.config.database" placeholder="数据库名" />
          </div>
          <div class="form-group">
            <label>凭证</label>
            <SearchSelect v-model="newSource.credential_id" :options="credentialOptions" placeholder="无凭证" aria-label="新建数据源凭证" />
          </div>
          <div class="modal-actions">
            <button class="btn btn-ghost" @click="showCreateSource = false">取消</button>
            <button class="btn btn-primary" @click="createSource" :disabled="!newSource.name">创建</button>
          </div>
        </div>
      </div>

      <!-- Edit Source Modal -->
      <div v-if="editingSource" class="modal-overlay" @click.self="editingSource = null">
        <div class="modal">
          <h3>编辑数据源</h3>
          <div class="form-group">
            <label>名称</label>
            <input v-model="editingSource.name" />
          </div>
          <div class="form-group">
            <label>类型</label>
            <SearchSelect v-model="editingSource.type" :options="sourceTypeOptions" placeholder="选择数据源类型" aria-label="编辑数据源类型" />
          </div>
          <div class="form-group">
            <label>描述</label>
            <textarea v-model="editingSource.description" rows="2"></textarea>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>Host</label>
              <input v-model="editingSource.config.host" />
            </div>
            <div class="form-group">
              <label>Port</label>
              <input v-model.number="editingSource.config.port" />
            </div>
          </div>
          <div class="form-group">
            <label>Database</label>
            <input v-model="editingSource.config.database" />
          </div>
          <div class="form-group">
            <label>凭证</label>
            <SearchSelect v-model="editingSource.credential_id" :options="editCredentialOptions" placeholder="无凭证" aria-label="编辑数据源凭证" />
          </div>
          <div v-if="editingSource._testResult" :class="['edit-test-result', editingSource._testResult.success ? 'success' : 'error']">
            {{ editingSource._testResult.message }}
          </div>
          <div v-if="editingSource._syncResult" class="edit-test-result" :class="editingSource._syncResult.success ? 'success' : 'error'" style="margin-top:4px">
            {{ editingSource._syncResult.message }}
          </div>
          <div class="modal-actions">
            <button class="btn btn-ghost" @click="testEditSource" :disabled="editingSource._testing">
              {{ editingSource._testing ? '测试中...' : '测试连接' }}
            </button>
            <button class="btn btn-ghost" @click="syncEditSource" :disabled="editingSource._syncing">
              <AppIcon name="RefreshCw" /> {{ editingSource._syncing ? '同步中...' : '同步结构' }}
            </button>
            <button class="btn btn-ghost" @click="viewEditSchema"><FileText :size="14" /> 查看Schema</button>
            <button class="btn btn-ghost" @click="editingSource = null">取消</button>
            <button class="btn btn-primary" @click="saveSource">保存</button>
          </div>
        </div>
      </div>

      <!-- Schema Viewer Modal -->
      <div v-if="showSchemaViewer" class="modal-overlay" @click.self="showSchemaViewer = false">
        <div class="modal modal-wide">
          <h3>Schema — {{ schemaViewerName }}</h3>
          <div v-if="schemaLoading" class="empty-hint">加载中...</div>
          <div v-else>
            <div v-if="schemaData.length === 0" class="empty-hint">无 Schema 数据</div>
            <div v-else class="schema-table">
              <div class="schema-row schema-header">
                <span class="sch-col-table">表名</span>
                <span class="sch-col-col">列名</span>
                <span class="sch-col-type">类型</span>
              </div>
              <div v-for="(row, i) in schemaData" :key="i" class="schema-row">
                <span class="sch-col-table">{{ row.table_name }}</span>
                <span class="sch-col-col">{{ row.column_name || '-' }}</span>
                <span class="sch-col-type">{{ row.data_type || '-' }}</span>
              </div>
            </div>
          </div>
          <div class="modal-actions">
            <button class="btn btn-ghost" @click="showSchemaViewer = false">关闭</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== 凭证 ===== -->
    <div v-if="activeTab === 'credentials'" class="tab-content">
      <div class="section-header">
        <h3>凭证管理</h3>
        <button class="btn btn-primary btn-sm" @click="showCreateCred = true">+ 新建凭证</button>
      </div>
      <div v-if="credentials.length === 0" class="empty-hint">暂无凭证</div>
      <div v-for="c in credentials" :key="c.id" class="card card-sm">
        <div class="card-header">
          <div>
            <div class="card-name"><Key :size="15" /> {{ c.name }}</div>
            <div class="card-meta">{{ c.type }}</div>
          </div>
          <div class="card-actions">
            <button class="btn btn-ghost btn-sm" @click="editCredential(c)"><Edit :size="14" /> 编辑</button>
            <button class="btn btn-danger btn-sm" @click="deleteCredential(c.id)">删除</button>
          </div>
        </div>
      </div>

      <div v-if="showCreateCred" class="modal-overlay" @click.self="showCreateCred = false">
        <div class="modal">
          <h3>新建凭证</h3>
          <div class="form-group">
            <label>名称 *</label>
            <input v-model="newCred.name" placeholder="例如：销售库只读账号" />
          </div>
          <div class="form-group">
            <label>类型 *</label>
            <SearchSelect v-model="newCred.type" :options="credentialTypeOptions" placeholder="选择凭证类型" aria-label="新建凭证类型" />
          </div>
          <div v-if="newCred.type === 'password'">
            <div class="form-row">
              <div class="form-group">
                <label>用户名 *</label>
                <input v-model="newCred.data.username" />
              </div>
              <div class="form-group">
                <label>密码 *</label>
                <input type="password" v-model="newCred.data.password" />
              </div>
            </div>
          </div>
          <div v-else-if="newCred.type === 'token'">
            <div class="form-group">
              <label>访问令牌 *</label>
              <input v-model="newCred.data.token" type="password" />
            </div>
          </div>
          <div v-else>
            <div class="form-group">
              <label>API Key *</label>
              <input v-model="newCred.data.api_key" type="password" />
            </div>
          </div>
          <div class="modal-actions">
            <button class="btn btn-ghost" @click="showCreateCred = false">取消</button>
            <button class="btn btn-primary" @click="createCredential" :disabled="!newCred.name">创建</button>
          </div>
        </div>
      </div>
    </div>

      <!-- Edit Credential Modal -->
      <div v-if="editingCred" class="modal-overlay" @click.self="editingCred = null">
        <div class="modal">
          <h3>编辑凭证</h3>
          <div class="form-group">
            <label>名称</label>
            <input v-model="editingCred.name" />
          </div>
          <div class="form-group">
            <label>类型</label>
            <SearchSelect v-model="editingCred.type" :options="credentialTypeOptions" placeholder="选择凭证类型" aria-label="编辑凭证类型" />
          </div>
          <div v-if="editingCred.type === 'password'">
            <div class="form-row">
              <div class="form-group">
                <label>用户名</label>
                <input v-model="editingCred._data.username" />
              </div>
              <div class="form-group">
                <label>密码（留空不修改）</label>
                <input type="password" v-model="editingCred._data.password" placeholder="留空则不修改密码" />
              </div>
            </div>
          </div>
          <div v-else-if="editingCred.type === 'token'">
            <div class="form-group">
              <label>访问令牌（留空不修改）</label>
              <input v-model="editingCred._data.token" type="password" placeholder="留空则不修改" />
            </div>
          </div>
          <div v-else>
            <div class="form-group">
              <label>API Key（留空不修改）</label>
              <input v-model="editingCred._data.api_key" type="password" placeholder="留空则不修改" />
            </div>
          </div>
          <div class="modal-actions">
            <button class="btn btn-ghost" @click="editingCred = null">取消</button>
            <button class="btn btn-primary" @click="saveCredential">保存</button>
          </div>
        </div>
      </div>

    <!-- ===== 数据能力 ===== -->
    <!-- ===== 数据能力 ===== -->
    <div v-if="activeTab === 'capabilities'" class="tab-content">
      <div class="section-header">
        <h3>数据能力</h3>
        <button class="btn btn-primary btn-sm" @click="showCreateCap = true">+ 新建能力</button>
      </div>
      <div v-if="capabilities.length === 0" class="empty-hint">暂无数据能力</div>
      <div v-for="cap in capabilities" :key="cap.id" class="card capability-card">
        <div class="card-header">
          <div>
            <div class="card-name"><Zap :size="15" /> {{ cap.name }}</div>
            <div class="card-meta">
              数据源: {{ getSourceName(cap.data_source_id) }}
            </div>
          </div>
          <div class="card-actions">
            <span :class="['status-badge', 'status-' + cap.status]">{{ cap.status === 'active' ? '启用' : '禁用' }}</span>
            <button class="btn btn-ghost btn-sm" @click="toggleCapability(cap)">{{ cap.status === 'active' ? '禁用' : '启用' }}</button>
            <button class="btn btn-ghost btn-sm" @click="editCapability(cap)"><Edit :size="14" /> 编辑</button>
            <button class="btn btn-danger btn-sm" @click="deleteCapability(cap.id)">删除</button>
          </div>
        </div>
      </div>

      <div v-if="showCreateCap" class="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="create-capability-title">
        <div class="modal modal-wide">
          <div class="modal-heading">
            <h3 id="create-capability-title">新建数据能力</h3>
            <button type="button" class="modal-close" aria-label="关闭新建数据能力弹窗" @click="showCreateCap = false">×</button>
          </div>
          <div class="form-group">
            <label>名称 *</label>
            <input v-model="newCap.name" placeholder="例如：查询月度销售额" />
          </div>
          <div class="form-group">
            <label>补充提示词</label>
            <textarea v-model="newCap.description" rows="3" placeholder="说明工具适用场景、默认筛选条件、业务值映射及回答要求；用户明确的条件优先于默认值。"></textarea>
            <small>调用该数据工具时会注入给 Agent，用于说明查询口径、字段含义和回答约束。</small>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>数据源 *</label>
              <SearchSelect v-model="newCap.data_source_id" :options="dataSourceOptions" placeholder="请选择" aria-label="新建数据能力数据源" />
            </div>
            <div class="form-group">
              <label>类型</label>
              <SearchSelect v-model="newCap.type" :options="capabilityTypeOptions" placeholder="选择能力类型" aria-label="新建数据能力类型" />
            </div>
          </div>
          <div class="form-group">
            <label>原始 SQL *</label>
            <textarea aria-label="原始 SQL" v-model="newCap.original_sql" rows="5" class="mono" placeholder="SELECT * FROM orders WHERE month = '2026-09'"></textarea>
            <InputSchemaGenerator :name="newCap.name" :description="newCap.description" :original-sql="newCap.original_sql" :query-template="newCap.query_template" :data-source-id="newCap.data_source_id" :input-schema="newCap.input_schema_str" @apply="applySqlDraft(newCap, $event)" />
          </div>
          <div class="form-group">
            <label>改写 SQL *</label>
            <textarea aria-label="改写 SQL" v-model="newCap.query_template" rows="5" class="mono" placeholder="SELECT * FROM orders WHERE (:month IS NULL OR month = :month)"></textarea>
          </div>
          <div class="form-group">
            <label>输入 Schema (JSON)</label>
            <textarea aria-label="输入 Schema (JSON)" v-model="newCap.input_schema_str" rows="3" class="mono" placeholder='{"type":"object","properties":{"month":{"type":"string"}}}'></textarea>
            <small>仅 SQL 中以 <code>:month</code> 形式实际引用的参数会暴露给 Agent；Schema 字段名需与 SQL 占位符一致。</small>
          </div>
          <div class="form-group">
            <label>输出 Schema (JSON)</label>
            <textarea v-model="newCap.output_schema_str" rows="3" class="mono"></textarea>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>最大行数</label>
              <input type="number" v-model.number="newCap.row_limit" min="1" max="10000" />
            </div>
            <div class="form-group">
              <label>超时(秒)</label>
              <input type="number" v-model.number="newCap.timeout_seconds" min="1" max="300" />
            </div>
          </div>
          <div class="modal-actions">
            <button class="btn btn-ghost" @click="showCreateCap = false">取消</button>
            <button class="btn btn-primary" @click="createCapability" :disabled="!newCap.name || !newCap.data_source_id">创建</button>
          </div>
        </div>
      </div>
    </div>

      <!-- Edit Capability Modal -->
      <div v-if="editingCap" class="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="edit-capability-title">
        <div class="modal modal-wide">
          <div class="modal-heading">
            <h3 id="edit-capability-title">编辑数据能力</h3>
            <button type="button" class="modal-close" aria-label="关闭编辑数据能力弹窗" @click="editingCap = null">×</button>
          </div>
          <div class="form-group">
            <label>名称 *</label>
            <input v-model="editingCap.name" />
          </div>
          <div class="form-group">
            <label>补充提示词</label>
            <textarea v-model="editingCap.description" rows="3" placeholder="说明工具适用场景、默认筛选条件、业务值映射及回答要求；用户明确的条件优先于默认值。"></textarea>
            <small>调用该数据工具时会注入给 Agent，用于说明查询口径、字段含义和回答约束。</small>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>数据源 *</label>
              <SearchSelect v-model="editingCap.data_source_id" :options="dataSourceOptions" placeholder="请选择" aria-label="编辑数据能力数据源" />
            </div>
            <div class="form-group">
              <label>类型</label>
              <SearchSelect v-model="editingCap.type" :options="capabilityTypeOptions" placeholder="选择能力类型" aria-label="编辑数据能力类型" />
            </div>
          </div>
          <div class="form-group">
            <label>原始 SQL *</label>
            <textarea aria-label="原始 SQL" v-model="editingCap.original_sql" rows="5" class="mono" placeholder="SELECT * FROM orders WHERE month = '2026-09'"></textarea>
            <InputSchemaGenerator :name="editingCap.name" :description="editingCap.description" :original-sql="editingCap.original_sql" :query-template="editingCap.query_template" :data-source-id="editingCap.data_source_id" :input-schema="editingCap.input_schema_str" @apply="applySqlDraft(editingCap, $event)" />
          </div>
          <div class="form-group">
            <label>改写 SQL *</label>
            <textarea aria-label="改写 SQL" v-model="editingCap.query_template" rows="5" class="mono" placeholder="SELECT * FROM orders WHERE (:month IS NULL OR month = :month)"></textarea>
          </div>
          <div class="form-group">
            <label>输入 Schema (JSON)</label>
            <textarea aria-label="输入 Schema (JSON)" v-model="editingCap.input_schema_str" rows="3" class="mono" placeholder='{"type":"object","properties":{"month":{"type":"string"}}}'></textarea>
            <small>仅 SQL 中以 <code>:month</code> 形式实际引用的参数会暴露给 Agent；Schema 字段名需与 SQL 占位符一致。</small>
          </div>
          <div class="form-group">
            <label>输出 Schema (JSON)</label>
            <textarea v-model="editingCap.output_schema_str" rows="3" class="mono"></textarea>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>最大行数</label>
              <input type="number" v-model.number="editingCap.row_limit" min="1" max="10000" />
            </div>
            <div class="form-group">
              <label>超时(秒)</label>
              <input type="number" v-model.number="editingCap.timeout_seconds" min="1" max="300" />
            </div>
          </div>
          <div class="modal-actions">
            <button class="btn btn-ghost" @click="editingCap = null">取消</button>
            <button class="btn btn-primary" @click="saveCapability" :disabled="!editingCap.name || !editingCap.data_source_id">保存</button>
          </div>
        </div>
      </div>

    <!-- ===== 查询日志 ===== -->
    <div v-if="activeTab === 'queries'" class="tab-content">
      <div class="section-header">
        <h3>查询审计日志</h3>
        <button class="btn btn-ghost btn-sm" @click="loadQueries"><AppIcon name="RefreshCw" /> 刷新</button>
      </div>
      <div v-if="queries.length === 0" class="empty-hint">暂无查询记录</div>
      <div v-for="q in queries" :key="q.id" class="card card-sm">
        <div class="card-header">
          <div>
            <div class="card-name">
              <span :class="['status-badge', 'status-' + q.status]">{{ q.status }}</span>
              {{ getCapName(q.data_capability_id) }}
            </div>
            <div class="card-meta">
              {{ q.source || '-' }} · {{ q.duration_ms || 0 }}ms · {{ new Date(q.created_at).toLocaleString('zh-CN') }}
            </div>
          </div>
        </div>
        <div v-if="q.error_message" class="error-msg">{{ q.error_message }}</div>
      </div>
    </div>


  </div>
</template>

<script setup>
import { Database, Plus, Trash2, Edit, Check, X, RefreshCw, Server, Key, Zap, FileText, Search, Play, Plug } from 'lucide-vue-next'

import { ref, computed, onMounted } from 'vue'
import { dataApi } from '../api'
import InputSchemaGenerator from '../components/InputSchemaGenerator.vue'

const tabs = [
  { id: 'sources', icon: 'Server', name: '数据源' },
  { id: 'credentials', icon: 'Key', name: '凭证' },
  { id: 'capabilities', icon: 'Zap', name: '数据能力' },
  { id: 'queries', icon: 'FileText', name: '查询日志' },
]
const iconMap = { Server, Key, Zap, FileText }
const activeTab = ref('sources')

const sources = ref([])
const credentials = ref([])
const capabilities = ref([])
const queries = ref([])

const showCreateSource = ref(false)
const showCreateCred = ref(false)
const showCreateCap = ref(false)
const editingSource = ref(null)
const editingCred = ref(null)
const editingCap = ref(null)
const showSchemaViewer = ref(false)
const schemaData = ref([])
const schemaLoading = ref(false)
const schemaViewerName = ref('')

const newSource = ref({ name: '', type: 'postgres', description: '', config: { host: '', port: 5432, database: '' }, credential_id: '' })
const newCred = ref({ name: '', type: 'password', data: { username: '', password: '' } })
const newCap = ref({ name: '', description: '', data_source_id: '', type: 'predefined_query', original_sql: '', query_template: '', input_schema_str: '{}', output_schema_str: '{}', row_limit: 1000, timeout_seconds: 30 })

const sourceTypeOptions = [
  { value: 'postgres', label: 'PostgreSQL' },
  { value: 'mysql', label: 'MySQL' },
  { value: 'api', label: 'API' },
]
const credentialTypeOptions = [
  { value: 'password', label: '用户名密码' },
  { value: 'token', label: '访问令牌' },
  { value: 'api_key', label: 'API Key' },
]
const capabilityTypeOptions = [
  { value: 'predefined_query', label: '预定义查询' },
]
const credentialOptions = computed(() => [
  { value: '', label: '无凭证' },
  ...credentials.value.map(c => ({ value: c.id, label: c.name + ' (' + c.type + ')' })),
])
const editCredentialOptions = computed(() => [
  { value: null, label: '无凭证' },
  ...credentials.value.map(c => ({ value: c.id, label: c.name + ' (' + c.type + ')' })),
])
const dataSourceOptions = computed(() => [
  { value: '', label: '请选择', disabled: true },
  ...sources.value.map(ds => ({ value: ds.id, label: ds.name })),
])

function validateSqlSchema(form) {
  if (!form.query_template?.trim()) throw new Error('请先填写 SQL')
  const schema = JSON.parse(form.input_schema_str || '{}')
  if (!schema || Array.isArray(schema) || typeof schema !== 'object') throw new Error('输入 Schema 必须是 JSON 对象')
  const properties = schema.properties || {}
  const names = [...new Set([...form.query_template.matchAll(/(?<!:):([A-Za-z_][A-Za-z0-9_]*)/g)].map(m => m[1]))]
  if (names.length !== Object.keys(properties).length || names.some(n => !Object.hasOwn(properties, n))) throw new Error('SQL 参数与输入 Schema 字段不一致，请修正后再保存')
}

function applySqlDraft(form, draft) { form.query_template = draft.query_template; form.input_schema_str = draft.input_schema }

const showToast = (msg, type = 'success') => {
  window.dispatchEvent(new CustomEvent('toast', { detail: { message: msg, type } }))
}

const statusText = (s) => ({ active: '活跃', inactive: '未激活', error: '错误', testing: '测试中' }[s] || s)
const getSourceName = (id) => sources.value.find(s => s.id === id)?.name || '-'
const getCapName = (id) => capabilities.value.find(c => c.id === id)?.name || '-'

// --- Load ---
const loadSources = async () => {
  try { const { data } = await dataApi.listSources(); sources.value = data } catch {}
}
const loadCredentials = async () => {
  try { const { data } = await dataApi.listCredentials(); credentials.value = data } catch {}
}
const loadCapabilities = async () => {
  try { const { data } = await dataApi.listCapabilities(); capabilities.value = data } catch {}
}
const loadQueries = async () => {
  try { const { data } = await dataApi.listQueries(); queries.value = data } catch {}
}

// --- Source ---
const createSource = async () => {
  try {
    const payload = { ...newSource.value }
    if (!payload.credential_id) delete payload.credential_id
    await dataApi.createSource(payload)
    showCreateSource.value = false
    newSource.value = { name: '', type: 'postgres', description: '', config: { host: '', port: 5432, database: '' }, credential_id: '' }
    await loadSources()
    showToast('数据源创建成功')
  } catch (e) { showToast('创建失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

const testSource = async (ds) => {
  ds._testing = true
  ds._testResult = null
  try {
    const { data } = await dataApi.testSource(ds.id)
    ds._testResult = data
    ds.status = data.success ? 'active' : 'error'
  } catch (e) { ds._testResult = { success: false, message: '请求失败' } }
  ds._testing = false
}

const syncSchema = async (ds) => {
  ds._syncing = true
  try {
    const { data } = await dataApi.syncSchema(ds.id)
    showToast(data.message)
  } catch (e) { showToast('同步失败: ' + (e.response?.data?.detail || e.message), 'error') }
  ds._syncing = false
}

const viewSchema = async (ds) => {
  schemaViewerName.value = ds.name
  schemaLoading.value = true
  showSchemaViewer.value = true
  try {
    const { data } = await dataApi.getSchema(ds.id)
    schemaData.value = data
  } catch { schemaData.value = [] }
  schemaLoading.value = false
}

const deleteSource = async (id) => {
  if (!confirm('确定删除该数据源？')) return
  try { await dataApi.deleteSource(id); await loadSources(); showToast('已删除') } catch { showToast('删除失败', 'error') }
}

// --- Credential ---
const createCredential = async () => {
  try {
    await dataApi.createCredential(newCred.value)
    showCreateCred.value = false
    newCred.value = { name: '', type: 'password', data: { username: '', password: '' } }
    await loadCredentials()
    showToast('凭证创建成功')
  } catch (e) { showToast('创建失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

const deleteCredential = async (id) => {
  if (!confirm('确定删除该凭证？')) return
  try { await dataApi.deleteCredential(id); await loadCredentials(); showToast('已删除') } catch { showToast('删除失败', 'error') }
}

// --- Capability ---
const createCapability = async () => {
  try {
    validateSqlSchema(newCap.value)
    const payload = {
      ...newCap.value,
      input_schema: JSON.parse(newCap.value.input_schema_str || '{}'),
      output_schema: JSON.parse(newCap.value.output_schema_str || '{}'),
    }
    delete payload.input_schema_str
    delete payload.output_schema_str
    await dataApi.createCapability(payload)
    showCreateCap.value = false
    newCap.value = { name: '', description: '', data_source_id: '', type: 'predefined_query', original_sql: '', query_template: '', input_schema_str: '{}', output_schema_str: '{}', row_limit: 1000, timeout_seconds: 30 }
    await loadCapabilities()
    showToast('数据能力创建成功')
  } catch (e) { showToast('创建失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

const deleteCapability = async (id) => {
  if (!confirm('确定删除该数据能力？')) return
  try { await dataApi.deleteCapability(id); await loadCapabilities(); showToast('已删除') } catch { showToast('删除失败', 'error') }
}

const toggleCapability = async (cap) => {
  const nextStatus = cap.status === 'active' ? 'inactive' : 'active'
  try {
    await dataApi.updateCapabilityStatus(cap.id, nextStatus)
    await loadCapabilities()
    showToast(nextStatus === 'active' ? '数据能力已启用' : '数据能力已禁用')
  } catch (e) { showToast('状态更新失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

const editCapability = (cap) => {
  editingCap.value = {
    ...JSON.parse(JSON.stringify(cap)),
    original_sql: cap.original_sql || cap.query_template || '',
    input_schema_str: JSON.stringify(cap.input_schema || {}, null, 2),
    output_schema_str: JSON.stringify(cap.output_schema || {}, null, 2),
  }
}

const saveCapability = async () => {
  try {
    validateSqlSchema(editingCap.value)
    const payload = {
      name: editingCap.value.name,
      description: editingCap.value.description,
      data_source_id: editingCap.value.data_source_id,
      type: editingCap.value.type,
      query_template: editingCap.value.query_template,
      original_sql: editingCap.value.original_sql,
      input_schema: JSON.parse(editingCap.value.input_schema_str || '{}'),
      output_schema: JSON.parse(editingCap.value.output_schema_str || '{}'),
      row_limit: editingCap.value.row_limit,
      timeout_seconds: editingCap.value.timeout_seconds,
    }
    await dataApi.updateCapability(editingCap.value.id, payload)
    editingCap.value = null
    await loadCapabilities()
    showToast('数据能力更新成功')
  } catch (e) { showToast('更新失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

// --- Edit Source ---
const editSource = (ds) => {
  editingSource.value = JSON.parse(JSON.stringify(ds))
}
const syncEditSource = async () => {
  if (!editingSource.value || !editingSource.value.id) return
  editingSource.value._syncing = true
  editingSource.value._syncResult = null
  try {
    const { data } = await dataApi.syncSchema(editingSource.value.id)
    editingSource.value._syncResult = { success: true, message: data.message }
  } catch (e) {
    editingSource.value._syncResult = { success: false, message: '同步失败: ' + (e.response?.data?.detail || e.message) }
  }
  editingSource.value._syncing = false
}

const viewEditSchema = async () => {
  if (!editingSource.value || !editingSource.value.id) return
  schemaViewerName.value = editingSource.value.name
  schemaLoading.value = true
  showSchemaViewer.value = true
  try {
    const { data } = await dataApi.getSchema(editingSource.value.id)
    schemaData.value = data
  } catch { schemaData.value = [] }
  schemaLoading.value = false
}

const testEditSource = async () => {
  if (!editingSource.value) return
  editingSource.value._testing = true
  editingSource.value._testResult = null
  try {
    // Save first if it's a new record (no id yet)
    if (!editingSource.value.id) {
      showToast('请先保存数据源', 'error')
      editingSource.value._testing = false
      return
    }
    const { data } = await dataApi.testSource(editingSource.value.id)
    editingSource.value._testResult = data
  } catch (e) {
    editingSource.value._testResult = { success: false, message: '请求失败' }
  }
  editingSource.value._testing = false
}

const saveSource = async () => {
  try {
    const { id, ...payload } = editingSource.value
    await dataApi.updateSource(id, payload)
    editingSource.value = null
    await loadSources()
    showToast('数据源更新成功')
  } catch (e) { showToast('更新失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

// --- Edit Credential ---
const editCredential = async (c) => {
  editingCred.value = { ...c, _data: { username: '', password: '', token: '', api_key: '' } }
}
const saveCredential = async () => {
  try {
    const payload = { name: editingCred.value.name, type: editingCred.value.type, data: editingCred.value._data }
    // Remove empty password/token/key to keep original
    if (editingCred.value.type === 'password' && !payload.data.password) delete payload.data.password
    if (editingCred.value.type === 'token' && !payload.data.token) delete payload.data.token
    if (editingCred.value.type === 'api_key' && !payload.data.api_key) delete payload.data.api_key
    await dataApi.updateCredential(editingCred.value.id, payload)
    editingCred.value = null
    await loadCredentials()
    showToast('凭证更新成功')
  } catch (e) { showToast('更新失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

onMounted(() => { loadSources(); loadCredentials(); loadCapabilities(); loadQueries() })
</script>

<style scoped>
.data-sources-page { }
.page-header { margin-bottom: 20px; }
.page-header h1 { margin: 0; font-size: 24px; }
.subtitle { color: var(--text2); margin: 4px 0 0; font-size: 14px; }
.data-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 20px; }
.data-tab-button { padding: 10px 18px; border: none; background: transparent; cursor: pointer; font-size: 14px; color: var(--text2); border-bottom: 2px solid transparent; }
.data-tab-button.active { color: var(--primary); border-bottom-color: var(--primary); font-weight: 500; }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.section-header h3 { margin: 0; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; }
.card-sm { padding: 10px 14px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.card-name { font-weight: 600; font-size: 15px; }
.card-meta { font-size: 12px; color: var(--text3); margin-top: 2px; }
.card-actions { display: flex; gap: 6px; align-items: center; }
.type-badge { font-size: 11px; padding: 2px 6px; border-radius: 4px; font-weight: 600; }
.type-postgres { background: #dbeafe; color: #1d4ed8; }
:root[data-theme="dark"] .type-postgres { background: rgba(59, 130, 246, .16); color: #93c5fd; }
.type-mysql { background: #fef3c7; color: #92400e; }
:root[data-theme="dark"] .type-mysql { background: rgba(245, 158, 11, .16); color: #fcd34d; }
.type-api { background: #e0e7ff; color: #4338ca; }
:root[data-theme="dark"] .type-api { background: rgba(99, 102, 241, .18); color: #a5b4fc; }
.status-badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.status-active { background: var(--success-bg); color: var(--success); }
.status-inactive { background: var(--surface2); color: var(--text3); }
.status-error { background: var(--danger-bg); color: var(--danger); }
.test-result { margin-top: 8px; padding: 8px 12px; border-radius: 6px; font-size: 13px; }
.test-result.success { background: var(--success-bg); color: var(--success); }
.test-result.error { background: var(--danger-bg); color: var(--danger); }
.test-result-block { margin-top: 10px; padding: 10px; background: var(--surface2); border-radius: 8px; }
.result-status { font-weight: 500; font-size: 13px; }
.result-status.success { color: var(--success); }
.result-status.error { color: var(--danger); }
.result-meta { font-size: 12px; color: var(--text3); margin-top: 4px; }
.error-msg { color: var(--danger); font-size: 13px; margin-top: 4px; }
.empty-hint { color: var(--text3); font-size: 13px; padding: 12px 0; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal { background: var(--surface); color: var(--text); border-radius: 8px; padding: 24px; width: 520px; max-width: 90vw; max-height: 85vh; overflow-y: auto; box-shadow: 0 16px 48px rgba(0,0,0,.2); }
.modal-wide { width: 680px; }
.modal h3 { margin: 0 0 16px; }
.modal-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
.modal-heading h3 { margin: 0; }
.modal-close { border: 0; background: transparent; color: var(--text3); border-radius: 6px; width: 30px; height: 30px; font-size: 22px; line-height: 1; cursor: pointer; }
.modal-close:hover { background: var(--surface2); color: var(--text); }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.form-group { margin-bottom: 12px; }
.form-group label { display: block; font-weight: 500; margin-bottom: 4px; font-size: 13px; }
.form-group input, .form-group textarea { width: 100%; padding: 7px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; box-sizing: border-box; }
.form-group :deep(.search-select-trigger) { min-height: 35px; padding: 7px 10px; border-radius: 6px; font-size: 13px; }
.form-group .mono { font-family: 'SF Mono', 'Consolas', monospace; font-size: 12px; }
.form-row { display: flex; gap: 12px; }
.form-row .form-group { flex: 1; }
.btn { padding: 7px 14px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; }
.btn-primary { background: var(--primary); color: #fff; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-ghost { background: transparent; color: var(--text2); border: 1px solid var(--border); }
.btn-danger { background: transparent; color: var(--danger); border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent); }
.btn-sm { padding: 4px 10px; font-size: 12px; }
.schema-table { max-height: 400px; overflow-y: auto; border: 1px solid var(--border); border-radius: 6px; }
.schema-row { display: flex; padding: 6px 10px; font-size: 13px; border-bottom: 1px solid var(--border); }
.schema-row.schema-header { font-weight: 600; background: var(--surface2); position: sticky; top: 0; }
.sch-col-table { flex: 2; }
.sch-col-col { flex: 2; }
.sch-col-type { flex: 1; color: var(--text3); }
/* Page tabs use the same underline treatment as Access, without raised button materials. */
.data-sources-page .data-tabs{display:flex;gap:8px;overflow-x:auto;max-width:100%;border-bottom:1px solid var(--border);margin-bottom:24px;scrollbar-width:thin}
.data-sources-page .data-tab-button{position:relative;display:inline-flex;align-items:center;flex:0 0 auto;min-height:44px;padding:10px 14px;border:0;border-radius:8px 8px 0 0;background:transparent;box-shadow:none;color:var(--text2);white-space:nowrap;font-weight:500;backdrop-filter:none;transform:none}
.data-sources-page .data-tab-button:hover{background:var(--surface2);color:var(--text)}
.data-sources-page .data-tab-button.active{background:transparent;color:var(--navigation-color,var(--primary));font-weight:600;box-shadow:none}
.data-sources-page .data-tab-button.active::after{content:"";position:absolute;left:14px;right:14px;bottom:0;height:2px;border-radius:2px;background:currentColor}
.data-sources-page .data-tab-button:focus-visible{outline:2px solid var(--navigation-color,var(--primary));outline-offset:-3px}
.data-sources-page .card-header{display:flex;flex-wrap:wrap;align-items:flex-start;gap:14px 24px}
.data-sources-page .capability-card .card-header{align-items:center}
.data-sources-page .card-header>div:first-child{flex:1 1 320px;min-width:0;max-width:100%}
.data-sources-page .card-name,.data-sources-page .card-meta{overflow-wrap:anywhere;line-height:1.6}
.data-sources-page .card-description{margin:6px 0 0;font-size:13px;line-height:1.65;color:var(--text2);white-space:pre-line;overflow-wrap:anywhere}
.data-sources-page .card-actions{flex:0 0 auto;max-width:100%;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.data-sources-page .card-actions>button,.data-sources-page .card-actions>.status-badge{flex:0 0 auto;white-space:nowrap}
.data-sources-page .card-actions>button{display:inline-flex;align-items:center;justify-content:center;gap:5px;min-height:32px}
.data-sources-page .card-actions svg{flex-shrink:0}
.data-sources-page .card-actions .btn-ghost{color:var(--text2);border-color:var(--border)}
@media(max-width:640px){.data-sources-page .data-tabs{gap:4px}.data-sources-page .data-tab-button{padding-inline:12px}.data-sources-page .card-actions{width:100%}}
</style>

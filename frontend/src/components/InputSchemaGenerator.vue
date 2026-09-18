<template>
  <section class="sql-assistant" aria-label="SQL 测试与改写">
    <div class="assistant-actions">
      <button type="button" class="btn btn-ghost" :disabled="testingOriginal || busy || !dataSourceId || !originalSql?.trim()" @click="testOriginal">
        <Play :size="14" /> {{ testingOriginal ? '测试中...' : '测试' }}
      </button>
      <button type="button" class="btn btn-primary" :disabled="busy || testingOriginal || !dataSourceId || !originalSql?.trim()" @click="generate">
        <Sparkles :size="14" /> {{ busy ? '改写中...' : '改写' }}
      </button>
    </div>
    <p class="assistant-hint">原始 SQL 必须先测试通过，系统会根据查询目标生成参数化 SQL 和输入 Schema。</p>
    <p v-if="error" role="alert" class="sql-error">{{ error }}</p>
    <div v-if="originalResult" class="draft-result original-result" aria-live="polite">
      <p v-if="!originalResult.success" role="alert" class="sql-error">{{ originalResult.error }}</p>
      <p v-else class="sql-success">原始 SQL 可正常执行，返回 {{ originalResult.row_count }} 行，耗时 {{ originalResult.duration_ms }} ms。</p>
    </div>

    <div v-if="draft" class="sql-draft">
      <div class="draft-title"><strong>改写结果</strong><span>请检查后应用，应用后仍需保存数据能力。</span></div>
      <p v-if="draft.explanation" class="draft-explanation">{{ draft.explanation }}</p>
      <label>改写 SQL
        <textarea v-model="draft.query_template" class="mono" rows="6" aria-label="改写 SQL 草稿" />
      </label>
      <label>输入 Schema
        <textarea v-model="draft.schemaText" class="mono" rows="6" aria-label="输入 Schema 草稿" />
      </label>
      <p v-if="schemaError" role="alert" class="sql-error">{{ schemaError }}</p>
      <div v-if="!schemaError && parsedSchema && Object.keys(parsedSchema.properties).length" class="parameter-form" aria-label="SQL 入参">
        <div class="parameter-form-title">SQL 入参</div>
        <label v-for="(field,key) in parsedSchema.properties" :key="key" class="parameter-field">
          <span>{{ key }} <small>{{ field.description }}{{ parsedSchema.required.includes(key) ? ' · 必填' : ' · 可选' }}</small></span>
          <select v-if="field.type === 'boolean'" v-model="values[key]" :aria-label="'测试参数 ' + key">
            <option value="">未提供</option><option value="true">true</option><option value="false">false</option>
          </select>
          <input v-else v-model="values[key]" :type="field.type === 'string' ? 'text' : 'number'" :step="field.type === 'integer' ? '1' : 'any'" :aria-label="'测试参数 ' + key" :placeholder="parsedSchema.required.includes(key) ? '请填写' : '留空表示不提供（NULL）'" />
        </label>
      </div>
      <div class="assistant-actions draft-actions">
        <button type="button" class="btn btn-ghost" :disabled="testing || !!schemaError" @click="testDraft">试运行 SQL</button>
        <button type="button" class="btn btn-primary" :disabled="testing || !!schemaError" @click="apply">应用 SQL 和 Schema</button>
        <button type="button" class="btn btn-ghost" :disabled="testing" @click="discard">取消改写</button>
      </div>
      <div v-if="draftResult" class="draft-result" aria-live="polite">
        <p v-if="!draftResult.success" role="alert" class="sql-error">{{ draftResult.error }}</p>
        <template v-else>
          <p class="sql-success">查询成功，返回 {{ draftResult.row_count }} 行，耗时 {{ draftResult.duration_ms }} ms{{ draftResult.truncated ? '，仅显示前 50 行' : '' }}。</p>
          <p v-if="!draftResult.rows.length" class="test-hint">查询成功，暂无符合条件的数据。</p>
          <div v-else class="preview-table"><table><thead><tr><th v-for="(column,index) in draftResult.columns" :key="index">{{ column }}</th></tr></thead><tbody><tr v-for="(row,index) in draftResult.rows" :key="index"><td v-for="(cell,column) in row" :key="column">{{ display(cell) }}</td></tr></tbody></table></div>
        </template>
      </div>
    </div>

    <div v-if="applied" role="status" class="applied-hint">SQL 和输入 Schema 已同时填入表单；点击保存后生效。</div>
  </section>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { Play, Sparkles } from 'lucide-vue-next'
import api from '../api'

const props = defineProps({ name: String, description: String, originalSql: String, queryTemplate: String, dataSourceId: String, inputSchema: String })
const emit = defineEmits(['apply'])
const busy = ref(false), testing = ref(false), testingOriginal = ref(false), error = ref(''), draft = ref(null), values = ref({}), draftResult = ref(null), originalResult = ref(null), applied = ref(false)
let generation = 0, testVersion = 0

const activeSql = computed(() => draft.value?.query_template ?? props.queryTemplate ?? '')
const activeSchema = computed(() => draft.value?.schemaText ?? props.inputSchema ?? '{}')
const parsedSchema = computed(() => {
  try { const schema = JSON.parse(activeSchema.value); if (!schema || Array.isArray(schema) || typeof schema !== 'object') return null; return { type: 'object', properties: {}, required: [], additionalProperties: false, ...schema } } catch { return null }
})
const schemaError = computed(() => {
  const schema = parsedSchema.value
  if (!schema) return '输入 Schema 不是有效的 JSON 对象，请先修正。'
  if (schema.type !== 'object' || !schema.properties || Array.isArray(schema.properties) || typeof schema.properties !== 'object' || !Array.isArray(schema.required)) return 'Schema 需要 object 类型、properties 对象和 required 数组。'
  for (const [key, field] of Object.entries(schema.properties)) if (!field || !['string', 'integer', 'number', 'boolean'].includes(field.type)) return '参数 ' + key + ' 的类型暂不支持。'
  const names = [...new Set([...activeSql.value.matchAll(/(?<!:):([A-Za-z_][A-Za-z0-9_]*)/g)].map(match => match[1]))]
  if (names.length !== Object.keys(schema.properties).length || names.some(name => !Object.hasOwn(schema.properties, name))) return 'SQL 占位符与 Schema 字段不一致，请修正后再试运行或应用。'
  if (schema.required.some(name => !Object.hasOwn(schema.properties, name))) return 'required 包含未定义的参数。'
  return ''
})

watch(() => [props.name, props.description, props.originalSql, props.queryTemplate, props.dataSourceId, props.inputSchema], () => { generation += 1; draft.value = null; draftResult.value = null; originalResult.value = null; applied.value = false; error.value = '' })
watch([activeSql, activeSchema, () => props.dataSourceId], () => { testVersion += 1; testing.value = false; draftResult.value = null; values.value = {} }, { flush: 'sync' })

const message = e => typeof e.response?.data?.detail === 'string' ? e.response.data.detail : '操作失败，请检查 SQL 与 Schema 后重试。'
async function testOriginal () {
  if (testingOriginal.value) return
  testingOriginal.value = true; error.value = ''; originalResult.value = null
  try { const { data } = await api.post('/data/capabilities/test-sql', { data_source_id: props.dataSourceId, query_template: props.originalSql }, { timeout: 22000 }); originalResult.value = data } catch (e) { originalResult.value = { success: false, error: message(e) } } finally { testingOriginal.value = false }
}
async function generate () {
  if (busy.value) return
  const version = ++generation
  busy.value = true; error.value = ''; draft.value = null; originalResult.value = null
  try { const { data } = await api.post('/data/capabilities/parameterize-sql', { name: props.name || '', description: props.description || '', query_template: props.originalSql, data_source_id: props.dataSourceId }, { timeout: 70000 }); if (version === generation) draft.value = { ...data, schemaText: JSON.stringify(data.input_schema, null, 2) } } catch (e) { if (version === generation) error.value = message(e) } finally { if (version === generation) busy.value = false }
}
function buildParams (schema) {
  const params = {}
  for (const [key, field] of Object.entries(schema.properties)) {
    const raw = values.value[key]
    if (raw === undefined || raw === '') { if (schema.required.includes(key)) throw new Error('请填写必填参数：' + key); params[key] = null }
    else if (field.type === 'boolean') params[key] = raw === 'true'
    else if (field.type === 'string') params[key] = String(raw)
    else { params[key] = Number(raw); if (!Number.isFinite(params[key]) || (field.type === 'integer' && !Number.isInteger(params[key]))) throw new Error('参数 ' + key + ' 需要有效的' + (field.type === 'integer' ? '整数' : '数字')) }
  }
  return params
}
async function testDraft () {
  if (testing.value || schemaError.value) return
  error.value = ''; draftResult.value = null
  let params
  try { params = buildParams(parsedSchema.value) } catch (e) { error.value = e.message; return }
  const version = ++testVersion
  testing.value = true
  try { const { data } = await api.post('/data/capabilities/test-draft', { data_source_id: props.dataSourceId, query_template: activeSql.value, input_schema: parsedSchema.value, params }, { timeout: 22000 }); if (version === testVersion) draftResult.value = data } catch (e) { if (version === testVersion) draftResult.value = { success: false, error: message(e) } } finally { if (version === testVersion) testing.value = false }
}
async function apply () { if (schemaError.value) return; emit('apply', { query_template: draft.value.query_template, input_schema: JSON.stringify(parsedSchema.value, null, 2) }); draft.value = null; draftResult.value = null; await nextTick(); applied.value = true }
function discard () { draft.value = null; draftResult.value = null; error.value = '' }
const display = value => value === null ? 'NULL' : typeof value === 'object' ? JSON.stringify(value) : String(value)
</script>

<style scoped>
.sql-assistant{border-top:1px solid var(--border);padding-top:10px;margin-top:8px;color:var(--text);min-width:0}.assistant-actions{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0}.sql-assistant button{display:inline-flex;align-items:center;gap:5px}.assistant-hint,.test-hint,.draft-title span{display:block;color:var(--text3);font-size:12px;line-height:1.6;margin:6px 0}.sql-error{color:var(--danger);font-size:13px;line-height:1.6}.sql-success{color:var(--success);font-size:13px}.sql-draft{padding:12px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;margin-top:12px}.draft-title{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}.draft-explanation{font-size:13px;line-height:1.6;white-space:pre-wrap}.sql-assistant label{display:grid;gap:5px;margin:10px 0;font-size:13px}.sql-assistant textarea,.sql-assistant input,.sql-assistant select{width:100%;box-sizing:border-box;background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px;font:inherit}.sql-assistant textarea{font-family:monospace;font-size:12px}.parameter-form{border-top:1px solid var(--border);margin-top:12px;padding-top:10px}.parameter-form-title{font-size:13px;font-weight:600}.parameter-field{margin:8px 0!important}.parameter-field span{font-size:13px}.parameter-field small{display:block;color:var(--text3);font-size:12px;font-weight:400;margin-top:2px}.draft-actions{margin-top:12px}.draft-result{font-size:13px;overflow-wrap:anywhere}.preview-table{max-height:280px;overflow:auto;border:1px solid var(--border)}.preview-table table{border-collapse:collapse;min-width:100%}.preview-table th,.preview-table td{padding:8px;white-space:pre-wrap;min-width:100px;max-width:300px;border-bottom:1px solid var(--border);text-align:left;overflow-wrap:anywhere}.preview-table th{background:var(--surface2);position:sticky;top:0}.applied-hint{margin-top:8px;color:var(--success);font-size:13px}
</style>

import assert from 'node:assert/strict'
import { test, after } from 'node:test'
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import { createRenderer, nextTick } from 'vue'
const output = await mkdtemp(new URL('../.knowledge-tests-', import.meta.url).pathname)
for (const name of ['KnowledgeUpload', 'ConfirmDialog', 'DocumentPreview', 'PushDocumentDialog', 'DocumentValidityDialog', 'DocumentSummaryDialog', 'TextDocumentEditorDialog', 'CreateTextDocDialog', 'KnowledgeBaseCard']) {
  const source = await readFile(new URL(`../src/components/knowledge/${name}.vue`, import.meta.url), 'utf8')
  // CSS transitions and the shared directory picker have separate browser coverage.
  const { descriptor } = parse(source.replaceAll('<Transition ', '<Transition :css="false" '))
  const code = compileScript(descriptor, { id: name, inlineTemplate: true }).content
    .replace("import { knowledgeApi } from '../../api'", "const knowledgeApi = new Proxy({}, { get: (_, key) => (...args) => globalThis.__knowledgeTestApi[key](...args) })")
    .replaceAll('.vue\'', '.mjs\'')
    .replace("import SearchSelect from '../SearchSelect.mjs'", "const SearchSelect = { render() { return null } }")
    .replace("import { auth } from '../../auth'", "const auth = { user: { id: 'tester' } }")
  await writeFile(`${output}/${name}.mjs`, code)
}
await writeFile(`${output}/documentStatus.js`, await readFile(new URL('../src/components/knowledge/documentStatus.js', import.meta.url), 'utf8'))
await writeFile(`${output}/MarkdownEditor.mjs`, "import { h } from 'vue'\nexport default { props: { modelValue: { type: String, default: '' } }, emits: ['update:modelValue'], render() { return h('textarea', { value: this.modelValue, 'aria-label': 'Markdown 文档编辑器', 'onUpdate:modelValue': value => this.$emit('update:modelValue', value) }) } }")
after(() => rm(output, { recursive: true, force: true }))
const createNode = (type, text = '') => ({ type, text, children: [], props: {}, style: {}, parent: null, focus() {}, scrollTo() {}, getRootNode() { return globalThis.document }, addEventListener() {}, removeEventListener() {}, querySelector() { return null }, querySelectorAll() { return [] } })
const body = createNode('body')
globalThis.Document = class {}
globalThis.document = Object.assign(new Document(), { activeElement: { focus() {} }, addEventListener() {}, removeEventListener() {} })
globalThis.window = { dispatchEvent() {} }
globalThis.CustomEvent = class {}
const renderer = createRenderer({
  createElement: type => createNode(type), createText: text => createNode('text', text), createComment: text => createNode('comment', text),
  setText: (el, text) => el.text = text, setElementText: (el, text) => el.text = text,
  parentNode: el => el.parent, nextSibling: el => el.parent?.children[el.parent.children.indexOf(el) + 1] || null,
  patchProp: (el, key, prev, value) => el.props[key] = value, querySelector: () => body,
  insert(el, parent, anchor) { if (el.parent) this.remove(el); el.parent = parent; const index = parent.children.indexOf(anchor); parent.children.splice(index < 0 ? parent.children.length : index, 0, el) },
  remove(el) { if (el.parent) { const index = el.parent.children.indexOf(el); if (index >= 0) el.parent.children.splice(index, 1); el.parent = null } },
})
const flush = async () => { for (let i = 0; i < 20; i++) await nextTick() }
const all = (root, predicate) => [...(predicate(root) ? [root] : []), ...root.children.flatMap(child => all(child, predicate))]
const textContent = el => el.text + el.children.map(textContent).join('')
const button = (root, label) => all(root, el => el.type === 'button' && (textContent(el).trim() === label || el.props['aria-label'] === label))[0]
async function mount(name, props, api) {
  globalThis.__knowledgeTestApi = api
  const component = (await import(`${output}/${name}.mjs?test=${Math.random()}`)).default
  if (name === 'KnowledgeBaseCard') props = { canManage: !props.readonly, canUse: !props.readonly, ...props }
  const errors = [], root = createNode('root'), app = renderer.createApp(component, props)
  app.config.errorHandler = e => errors.push(e)
  app.mount(root); await flush()
  return { root, app, errors }
}

test('upload reports byte progress, processing, partial failures, duplicate names, and retry', async () => {
  const pending = []
  const state = await mount('KnowledgeUpload', { kbId: 'kb' }, { uploadFile: (id, file, progress) => new Promise((resolve, reject) => pending.push({ progress, resolve, reject })) })
  const input = all(state.root, el => el.type === 'input')[0]
  input.props.onChange({ target: { files: [{ name: 'same.txt', size: 10 }, { name: 'same.txt', size: 10 }], value: 'chosen' } })
  await flush()
  pending[0].progress({ loaded: 5, total: 10 }); await flush()
  assert.ok(all(state.root, el => el.text === '50%').length)
  pending[0].progress({ loaded: 10, total: 10 }); await flush()
  assert.ok(all(state.root, el => el.text === '服务器处理中…').length)
  pending.shift().resolve({}); await flush()
  pending.shift().reject(new Error('offline')); await flush()
  assert.ok(all(state.root, el => el.text === '已上传').length)
  assert.ok(all(state.root, el => el.text === '失败').length)
  assert.ok(button(state.root, '重试'))
  button(state.root, '重试').props.onClick(); await flush(); pending.shift().resolve({}); await flush()
  assert.equal(all(state.root, el => el.text === '已上传').length, 2)
  assert.deepEqual(state.errors, []); state.app.unmount()
})

test('preview loads only the current page and allows next-page navigation', async () => {
  const requests = []
  const state = await mount('DocumentPreview', { kbId: 'kb', docId: 'doc', name: 'file.pdf' }, {
    previewDoc: async () => ({ data: { name: 'file.pdf', kind: 'pdf', status: 'ready', page_count: 3 } }),
    previewPage: async (kb, doc, page) => { requests.push(page); return { data: new Blob(['image']) } },
  })
  assert.deepEqual(requests, [1])
  button(body, '下一页').props.onClick(); await flush()
  assert.deepEqual(requests, [1, 2])
  assert.deepEqual(state.errors, []); state.app.unmount()
})

test('markdown text documents render in preview and save the original source', async () => {
  const updates = []
  const state = await mount('DocumentPreview', { kbId: 'kb', docId: 'doc', name: 'guide.md' }, {
    previewDoc: async () => ({ data: { name: 'guide.md', kind: 'text', status: 'ready', page_count: 1, download_available: false } }),
    previewPage: async () => ({ data: { content: '# 标题\n\n**正文**' } }),
    getDocContent: async () => ({ data: { content: '# 标题\n\n**正文**' } }),
    updateDocContent: async (...args) => { updates.push(args); return { data: { name: 'guide.md' } } },
  })
  assert.ok(all(body, el => el.type === 'article' && String(el.props.innerHTML || '').includes('<h1>标题</h1>')).length)
  button(body, '编辑').props.onClick(); await flush()
  assert.equal(button(body, '预览'), undefined)
  assert.equal(button(body, '源码'), undefined)
  const editor = all(body, el => el.type === 'textarea')[0]
  editor.props['onUpdate:modelValue']('# 新标题\n\n**新正文**'); await flush()
  assert.equal(all(body, el => el.type === 'textarea').length, 1)
  button(body, '保存').props.onClick(); await flush()
  assert.deepEqual(updates, [['kb', 'doc', '# 新标题\n\n**新正文**']])
  assert.ok(all(body, el => el.type === 'article' && String(el.props.innerHTML || '').includes('<h1>新标题</h1>')).length)
  assert.equal(all(body, el => el.type === 'strong' && el.text === '暂时无法预览').length, 0)
  assert.deepEqual(state.errors, []); state.app.unmount()
})

test('txt documents use the same markdown preview and editor', async () => {
  const updates = []
  const state = await mount('DocumentPreview', { kbId: 'kb', docId: 'doc', name: 'guide.txt' }, {
    previewDoc: async () => ({ data: { name: 'guide.txt', kind: 'text', status: 'ready', page_count: 1, download_available: false } }),
    previewPage: async () => ({ data: { content: '# TXT 标题\n\n**正文**' } }),
    getDocContent: async () => ({ data: { content: '# TXT 标题\n\n**正文**' } }),
    updateDocContent: async (...args) => { updates.push(args); return { data: { name: 'guide.txt', status: 'active', metadata_json: { size: 24, content_type: 'text/plain' } } } },
  })
  assert.ok(all(body, el => el.type === 'article' && String(el.props.innerHTML || '').includes('<h1>TXT 标题</h1>')).length)
  button(body, '编辑').props.onClick(); await flush()
  assert.equal(button(body, '预览'), undefined)
  assert.equal(button(body, '源码'), undefined)
  const editor = all(body, el => el.type === 'textarea')[0]
  editor.props['onUpdate:modelValue']('# TXT 新标题\n\n- 新正文'); await flush()
  assert.equal(all(body, el => el.type === 'textarea').length, 1)
  button(body, '保存').props.onClick(); await flush()
  assert.deepEqual(updates, [['kb', 'doc', '# TXT 新标题\n\n- 新正文']])
  assert.ok(all(body, el => el.type === 'article' && String(el.props.innerHTML || '').includes('<h1>TXT 新标题</h1>')).length)
  assert.equal(all(body, el => el.type === 'strong' && el.text === '暂时无法预览').length, 0)
  assert.deepEqual(state.errors, []); state.app.unmount()
})

test('markdown creation exposes preview and sends source without trimming it', async () => {
  const calls = []
  const state = await mount('CreateTextDocDialog', { kbId: 'kb' }, {
    addDoc: async (...args) => { calls.push(args); return { data: {} } },
  })
  const inputs = all(body, el => el.type === 'input')
  inputs[0].props.onInput({ target: { value: 'guide.md' } }); await flush()
  assert.equal(button(body, '预览'), undefined)
  const textareas = all(body, el => el.type === 'textarea')
  textareas[0].props['onUpdate:modelValue']('\n# 标题\n'); await flush()
  button(body, '创建文档').props.onClick(); await flush()
  assert.deepEqual(calls, [['kb', { name: 'guide.md', content: '\n# 标题\n' }]])
  assert.deepEqual(state.errors, []); state.app.unmount()
})

test('txt creation exposes markdown preview and sends the source unchanged', async () => {
  const calls = []
  const state = await mount('CreateTextDocDialog', { kbId: 'kb' }, {
    addDoc: async (...args) => { calls.push(args); return { data: {} } },
  })
  const inputs = all(body, el => el.type === 'input')
  inputs[0].props.onInput({ target: { value: 'guide.txt' } }); await flush()
  assert.equal(button(body, '预览'), undefined)
  all(body, el => el.type === 'textarea')[0].props['onUpdate:modelValue']('\n# TXT 标题\n\n**正文**'); await flush()
  button(body, '创建文档').props.onClick(); await flush()
  assert.deepEqual(calls, [['kb', { name: 'guide.txt', content: '\n# TXT 标题\n\n**正文**' }]])
  assert.deepEqual(state.errors, []); state.app.unmount()
})

test('confirmation dialog is inert until an explicit confirmation', async () => {
  let confirmed = 0, cancelled = 0
  const state = await mount('ConfirmDialog', { title: '删除文档？', message: '删除测试文件', onConfirm: () => confirmed++, onCancel: () => cancelled++ }, {})
  assert.equal(confirmed, 0)
  button(body, '取消').props.onClick(); assert.equal(cancelled, 1); assert.equal(confirmed, 0)
  button(body, '确认删除').props.onClick(); assert.equal(confirmed, 1)
  assert.deepEqual(state.errors, []); state.app.unmount()
})

test('knowledge card never calls delete API before confirming, and readonly cards omit mutation controls', async () => {
  let deletes = 0
  const state = await mount('KnowledgeBaseCard', { kb: { id: 'kb', name: '测试库' } }, {
    detail: async () => ({ data: { documents: [{ id: 'doc', name: 'note.txt' }] } }),
    deleteDoc: async () => { deletes++ },
  })
  button(state.root, '更多文件操作 note.txt').props.onClick(); await flush()
  button(state.root, '删除文件').props.onClick(); await flush()
  assert.equal(deletes, 0)
  button(body, '取消').props.onClick(); await flush(); assert.equal(deletes, 0)
  button(state.root, '更多文件操作 note.txt').props.onClick(); await flush()
  button(state.root, '删除文件').props.onClick(); await flush()
  await button(body, '确认删除').props.onClick(); await flush(); assert.equal(deletes, 1)
  assert.deepEqual(state.errors, []); state.app.unmount()
  const readonly = await mount('KnowledgeBaseCard', { kb: { id: 'kb', name: '共享库' }, readonly: true }, globalThis.__knowledgeTestApi)
  assert.equal(button(readonly.root, '删除 note.txt'), undefined)
  assert.equal(button(readonly.root, '删除知识库'), undefined)
  assert.equal(all(readonly.root, el => el.type === 'input' && el.props.type === 'file').length, 0)
  assert.deepEqual(readonly.errors, []); readonly.app.unmount()
})

test('knowledge cards show status and let editable cards toggle it', async () => {
  const kb = { id: 'kb', name: '测试库', status: 'active' }
  const calls = []
  const state = await mount('KnowledgeBaseCard', { kb }, {
    detail: async () => ({ data: { documents: [] } }),
    updateStatus: async (...args) => { calls.push(args); return { data: { ...kb, status: 'disabled' } } },
  })
  assert.ok(all(state.root, el => el.text === '已启用').length)
  button(state.root, '更多知识库操作').props.onClick(); await flush()
  button(state.root, '禁用知识库').props.onClick(); await flush()
  assert.deepEqual(calls, [['kb', 'disabled']])
  assert.ok(all(state.root, el => el.text === '已禁用').length)
  button(state.root, '更多知识库操作').props.onClick(); await flush()
  assert.ok(button(state.root, '启用知识库'))
  state.app.unmount()

  const readonly = await mount('KnowledgeBaseCard', { kb: { id: 'kb', name: '共享库', status: 'disabled' }, readonly: true }, {
    detail: async () => ({ data: { documents: [] } }),
  })
  assert.ok(all(readonly.root, el => el.text === '已禁用').length)
  assert.equal(button(readonly.root, '启用知识库'), undefined)
  assert.deepEqual(readonly.errors, []); readonly.app.unmount()
})

test('cards start collapsed and bulk delete confirms exactly the cross-page selection', async () => {
  let docs = Array.from({ length: 12 }, (_, i) => ({ id: `doc${i}`, name: `${i}.txt` }))
  const calls = []
  const state = await mount('KnowledgeBaseCard', { kb: { id: 'kb', name: '测试库' } }, {
    detail: async () => ({ data: { documents: docs } }),
    batchDeleteResources: async (kb, ids) => { calls.push(ids); docs = docs.filter(doc => !ids.includes(doc.id)) },
  })
  const toggle = all(state.root, el => el.type === 'button' && el.props['aria-expanded'] !== undefined)[0]
  assert.equal(toggle.props['aria-expanded'], false)
  assert.equal(all(state.root, el => el.props.class === 'card-content')[0].style.display, 'none')
  toggle.props.onClick(); await flush()
  all(state.root, el => el.props['aria-label'] === '选择 0.txt')[0].props.onChange({ target: { checked: true } })
  button(state.root, '下一页').props.onClick(); await flush()
  all(state.root, el => el.props['aria-label'] === '选择 11.txt')[0].props.onChange({ target: { checked: true } }); await flush()
  button(state.root, '批量删除').props.onClick(); await flush()
  assert.equal(calls.length, 0)
  assert.ok(all(body, el => el.type === 'p' && el.text.includes('0.txt') && el.text.includes('11.txt')).length)
  button(body, '取消').props.onClick(); await flush(); assert.equal(calls.length, 0)
  button(state.root, '批量删除').props.onClick(); await flush()
  button(body, '确认删除').props.onClick(); await flush()
  assert.deepEqual(calls, [['doc0', 'doc11']])
  assert.equal(docs.length, 10)
  assert.deepEqual(state.errors, []); state.app.unmount()
})

test('push dialog only offers same-workspace public targets and requires an explicit choice', async () => {
  const calls = [], pushed = []
  const state = await mount('PushDocumentDialog', { kb: { id: 'private', workspace_id: 'ws' }, doc: { id: 'source', name: 'file.pdf' }, onPushed: id => pushed.push(id) }, {
    list: async () => ({ data: [{ id: 'public', name: '公共库', workspace_id: 'ws', agent_id: null }, { id: 'other', name: '其他空间', workspace_id: 'other' }, { id: 'private2', name: '私有库', workspace_id: 'ws', agent_id: 'agent' }] }),
    pushDoc: async (...args) => { calls.push(args); return { status: 201 } },
  })
  const choices = all(body, el => el.type === 'input' && el.props.type === 'radio')
  assert.equal(choices.length, 1)
  assert.equal(button(body, '确认推送').props.disabled, true)
  choices[0].props.onChange(); await flush()
  button(body, '确认推送').props.onClick(); await flush()
  assert.deepEqual(calls, [['private', 'source', 'public']])
  assert.deepEqual(pushed, ['public'])
  assert.deepEqual(state.errors, []); state.app.unmount()
})

test('readonly shared cards support single and cross-page ZIP downloads', async () => {
  const calls = [], saved = []
  const originalTimeout = globalThis.setTimeout
  globalThis.setTimeout = callback => { callback(); return 0 }
  document.body = { appendChild() {} }
  document.createElement = () => ({ click() { saved.push(this.download) }, remove() {} })
  const state = await mount('KnowledgeBaseCard', { kb: { id: 'kb', name: '共享库' }, readonly: true }, {
    detail: async () => ({ data: { documents: Array.from({ length: 12 }, (_, i) => ({ id: `doc${i}`, name: `${i}.txt` })) } }),
    downloadDoc: async (...args) => { calls.push(args); return { data: new Blob(['original']) } },
    batchDownloadDocs: async (...args) => { calls.push(args); return { data: new Blob(['zip']) } },
  })
  try {
    button(state.root, '展开').props.onClick(); await flush()
    button(state.root, '更多文件操作 0.txt').props.onClick(); await flush()
    await button(state.root, '下载').props.onClick(); await flush()
    all(state.root, el => el.props['aria-label'] === '选择 0.txt')[0].props.onChange({ target: { checked: true } })
    button(state.root, '下一页').props.onClick(); await flush()
    all(state.root, el => el.props['aria-label'] === '选择 11.txt')[0].props.onChange({ target: { checked: true } }); await flush()
    await button(state.root, '批量下载').props.onClick(); await flush()
    assert.deepEqual(calls, [['kb', 'doc0'], ['kb', ['doc0', 'doc11']]])
    assert.deepEqual(saved, ['0.txt', '共享库.zip'])
    assert.equal(button(state.root, '批量删除'), undefined)
    assert.deepEqual(state.errors, [])
  } finally { state.app.unmount(); globalThis.setTimeout = originalTimeout }
})

test('expired documents stay previewable and downloadable while administrators can renew them', async () => {
  const updates = []
  const state = await mount('KnowledgeBaseCard', { kb: { id: 'kb', name: '测试库' } }, {
    detail: async () => ({ data: { documents: [{ id: 'expired', name: 'policy.pdf', valid_until: '2000-01-01' }] } }),
    updateDocValidity: async (...args) => { updates.push(args); return { data: { id: 'expired', name: 'policy.pdf', valid_until: null } } },
  })
  assert.ok(all(state.root, el => el.text === '已过期 · 有效期至 2000-01-01').length)
  assert.ok(all(state.root, el => el.type === 'button' && String(el.props.class || '').includes('preview-action')).length)
  button(state.root, '更多文件操作 policy.pdf').props.onClick(); await flush()
  assert.ok(button(state.root, '下载'))
  button(state.root, '续期').props.onClick(); await flush()
  const dialog = all(body, el => el.props.class === 'validity-dialog').at(-1)
  const forever = all(dialog, el => el.type === 'input' && el.props.type === 'radio' && el.props.value === 'forever')[0]
  forever.props['onUpdate:modelValue']('forever'); await flush()
  dialog.props.onSubmit({ preventDefault() {} }); await flush()
  assert.deepEqual(updates, [['kb', 'expired', null]])
  assert.ok(all(state.root, el => el.text === '永久有效').length)
  assert.deepEqual(state.errors, []); state.app.unmount()
})

test('summary hides legacy binary bytes, offers image extraction, and preserves manual text', async () => {
  const content = 'iVBORw0KGgoAAAANSUhEUg encoded PNG ...[全文已存储到文件系统]'
  const cases = [
    { name: 'image.png', metadata_json: { encoding: 'base64', summary_status: 'unsupported' }, hidden: true, retry: true },
    { name: 'file.docx', metadata_json: { encoding: 'base64', summary_status: 'unsupported' }, hidden: true, retry: true },
    { name: 'image.png', metadata_json: { encoding: 'base64', summary_source: 'manual', summary_status: 'ready' }, hidden: false, retry: true },
  ]
  for (const item of cases) {
    let queued = 0
    const state = await mount('DocumentSummaryDialog', { kbId: 'kb', doc: { id: 'doc', content, ...item }, onQueued: () => queued++ }, { extractDoc: async () => ({ data: { status: 'pending' } }) })
    assert.equal(all(body, el => el.text.includes(content)).length > 0, !item.hidden)
    assert.equal(all(body, el => el.text === '已生成').length, 0)
    const retry = all(body, el => el.type === 'button' && all(el, child => child.text.includes('自动生成摘要')).length)[0]
    assert.equal(!!retry, item.retry)
    if (retry) { await retry.props.onClick(); await flush(); assert.equal(queued, 1) }
    button(body, item.hidden ? '手动填写' : '编辑').props.onClick(); await flush()
    const editor = all(body, el => el.type === 'textarea')[0]
    assert.equal(editor.value, item.hidden ? '' : content)
    assert.deepEqual(state.errors, []); state.app.unmount()
  }
})
